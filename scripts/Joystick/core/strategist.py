"""
strategist.py — Active Intelligence Layer for Joystick Bot

The Strategist sits between the balance snapshot and engine execution in bot.py.
It evaluates all engines, tracks cumulative P&L, and produces a Recommendation
that the bot either auto-executes or presents to the operator for approval.

Architecture:
  bot.py cycle:
    1. Balance snapshot (Multicall3)
    2. Strategist.evaluate(balances, engines)   <-- HERE
       -> reads all engine.is_ready() + roi()
       -> checks P&L history, fund allocation
       -> returns Recommendation(engine, rationale, confidence)
    3. If interactive: print recommendation, wait for approval
       If auto: execute if confidence > threshold
    4. Engine.execute()
    5. Strategist.record(result)                <-- HERE
    6. Compound profits

Persistent state: data/strategist_state.json — survives restarts.

Usage:
    from .core.strategist import Strategist

    strat = Strategist(engines, interactive=True)
    rec = strat.evaluate(balances)
    if rec.approved:
        result = rec.engine.execute(dry_run=False)
        strat.record(rec.engine.name, result)
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engines.base import EngineBase, EngineResult

log = logging.getLogger("joystick.strategist")

_JOYSTICK_DIR = Path(__file__).parent.parent
_STATE_FILE = _JOYSTICK_DIR / "data" / "strategist_state.json"


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Recommendation:
    """Single-cycle recommendation from the Strategist."""
    engine: "EngineBase | None"   # None = skip cycle
    rationale: str                # Human-readable explanation
    confidence: str               # "HIGH", "MEDIUM", "LOW", "SKIP"
    roi: float = 0.0             # Expected ROI multiplier
    profit_est: float = 0.0      # Estimated profit in PLS
    gas_est: float = 0.0         # Estimated gas cost in PLS
    risk_notes: list[str] = field(default_factory=list)
    approved: bool = False        # Set True after operator approval or auto-approve


@dataclass
class EngineStats:
    """Cumulative per-engine statistics."""
    total_runs: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_profit_pls: float = 0.0
    total_gas_pls: float = 0.0
    last_run_epoch: float = 0.0
    last_profit_pls: float = 0.0
    consecutive_failures: int = 0
    best_profit_pls: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.total_successes / self.total_runs if self.total_runs > 0 else 0.0

    @property
    def net_pls(self) -> float:
        return self.total_profit_pls - self.total_gas_pls

    @property
    def avg_profit_pls(self) -> float:
        return self.total_profit_pls / self.total_successes if self.total_successes > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "total_runs": self.total_runs,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "total_profit_pls": round(self.total_profit_pls, 6),
            "total_gas_pls": round(self.total_gas_pls, 6),
            "last_run_epoch": self.last_run_epoch,
            "last_profit_pls": round(self.last_profit_pls, 6),
            "consecutive_failures": self.consecutive_failures,
            "best_profit_pls": round(self.best_profit_pls, 6),
        }

    @staticmethod
    def from_dict(d: dict) -> "EngineStats":
        return EngineStats(**{k: d[k] for k in EngineStats.__dataclass_fields__ if k in d})


# ── Strategist ────────────────────────────────────────────────────────────────

class Strategist:
    """
    Active intelligence layer. Evaluates engines, tracks P&L, recommends actions.

    Modes:
      interactive=True:  Prints recommendation, waits for operator Y/N
      interactive=False: Auto-approves if confidence >= auto_threshold
    """

    AUTO_THRESHOLD = "MEDIUM"  # Auto-approve at this confidence or above
    CONFIDENCE_ORDER = {"SKIP": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}

    def __init__(self, engines: list["EngineBase"], interactive: bool = False):
        self.engines = engines
        self.interactive = interactive
        self.stats: dict[str, EngineStats] = {}
        self.session_start = time.time()
        self.cycles_run = 0
        self.total_session_profit = 0.0
        self._load_state()

    # ── Core evaluate method ──────────────────────────────────────────────────

    def evaluate(self, balances: dict) -> Recommendation:
        """
        Evaluate all engines and return a single Recommendation.

        Called once per cycle, after balance snapshot, before engine execution.
        """
        self.cycles_run += 1
        pls_bal = balances.get("pls", 0) / 1e18

        # Gather candidates: ready, not disabled, with simulation data
        candidates = []
        for engine in self.engines:
            if engine.is_disabled():
                continue
            if not engine.is_ready():
                continue

            try:
                profit_wei, gas_wei = engine.simulate()
                profit_pls = profit_wei / 1e18
                gas_pls = gas_wei / 1e18
                roi = profit_wei / gas_wei if gas_wei > 0 else 0.0
            except Exception:
                profit_pls, gas_pls, roi = 0.0, 0.0, 0.0

            stats = self.stats.get(engine.name, EngineStats())
            candidates.append((engine, profit_pls, gas_pls, roi, stats))

        if not candidates:
            return Recommendation(
                engine=None,
                rationale="No engines ready this cycle",
                confidence="SKIP",
            )

        # Score and rank candidates
        scored = []
        for engine, profit_pls, gas_pls, roi, stats in candidates:
            score, confidence, risks = self._score_candidate(
                engine, profit_pls, gas_pls, roi, stats, pls_bal
            )
            scored.append((score, engine, profit_pls, gas_pls, roi, confidence, risks))

        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0]
        _, engine, profit_pls, gas_pls, roi, confidence, risks = best

        # Build rationale
        runner_up = scored[1][1].name if len(scored) > 1 else "none"
        rationale = self._build_rationale(
            engine, profit_pls, gas_pls, roi, confidence,
            self.stats.get(engine.name, EngineStats()),
            runner_up, pls_bal,
        )

        rec = Recommendation(
            engine=engine,
            rationale=rationale,
            confidence=confidence,
            roi=roi,
            profit_est=profit_pls,
            gas_est=gas_pls,
            risk_notes=risks,
        )

        # Approval
        if self.interactive:
            rec.approved = self._prompt_operator(rec)
        else:
            rec.approved = self._auto_approve(rec)

        return rec

    # ── Record outcome ────────────────────────────────────────────────────────

    def record(self, engine_name: str, result: "EngineResult") -> None:
        """Record engine execution result into persistent stats."""
        if engine_name not in self.stats:
            self.stats[engine_name] = EngineStats()

        s = self.stats[engine_name]
        s.total_runs += 1
        s.last_run_epoch = time.time()

        if result.success:
            s.total_successes += 1
            s.consecutive_failures = 0
            profit = result.profit_wei / 1e18
            gas = result.gas_wei / 1e18
            s.total_profit_pls += profit
            s.total_gas_pls += gas
            s.last_profit_pls = profit - gas
            s.best_profit_pls = max(s.best_profit_pls, profit - gas)
            self.total_session_profit += profit - gas
        else:
            s.total_failures += 1
            s.consecutive_failures += 1
            s.last_profit_pls = 0.0

        self._save_state()

    # ── Scoring internals ─────────────────────────────────────────────────────

    def _score_candidate(
        self,
        engine: "EngineBase",
        profit_pls: float,
        gas_pls: float,
        roi: float,
        stats: EngineStats,
        pls_balance: float,
    ) -> tuple[float, str, list[str]]:
        """
        Score a candidate engine. Returns (score, confidence, risk_notes).

        Score components:
          - ROI weight (primary)
          - Win rate bonus (historical reliability)
          - Recency penalty (don't spam the same engine)
          - Strategic bonus (Beat/LAU run even at 0 profit)
          - Risk penalties
        """
        risks = []
        score = 0.0

        # 1. ROI weight (0-10 points)
        score += min(roi, 10.0)

        # 2. Win rate bonus (0-3 points)
        if stats.total_runs >= 3:
            score += stats.win_rate * 3.0
        else:
            score += 1.5  # Benefit of the doubt for new engines

        # 3. Consecutive failure penalty (-2 per failure)
        if stats.consecutive_failures > 0:
            score -= stats.consecutive_failures * 2.0
            risks.append(f"{stats.consecutive_failures} consecutive failures")

        # 4. Strategic engines get a floor score (Beat, LAU advance game state)
        if engine.name in ("Beat", "LAU") and score < 1.0:
            score = max(score, 1.0)
            if profit_pls <= gas_pls:
                risks.append("Strategic run (no direct profit)")

        # 5. Gas affordability check
        if gas_pls > 0 and gas_pls > pls_balance * 0.1:
            risks.append(f"Gas ({gas_pls:.1f} PLS) is >{10}% of balance")
            score -= 1.0

        # 6. Profit/loss check
        if profit_pls <= gas_pls and engine.name not in ("Beat", "LAU"):
            risks.append("Unprofitable (profit <= gas)")
            score -= 5.0

        # Confidence mapping
        if score >= 5.0 and not risks:
            confidence = "HIGH"
        elif score >= 2.0:
            confidence = "MEDIUM"
        elif score >= 0.0:
            confidence = "LOW"
        else:
            confidence = "SKIP"

        return score, confidence, risks

    def _build_rationale(
        self,
        engine: "EngineBase",
        profit_pls: float,
        gas_pls: float,
        roi: float,
        confidence: str,
        stats: EngineStats,
        runner_up: str,
        pls_balance: float,
    ) -> str:
        """Build a human-readable rationale string."""
        net = profit_pls - gas_pls
        parts = [
            f"Recommend: {engine.name} [{confidence}]",
            f"  Est. profit: {profit_pls:.4f} PLS | Gas: {gas_pls:.4f} PLS | Net: {net:.4f} PLS | ROI: {roi:.2f}x",
        ]

        if stats.total_runs > 0:
            parts.append(
                f"  History: {stats.total_successes}/{stats.total_runs} wins "
                f"({stats.win_rate:.0%}) | Cumulative net: {stats.net_pls:.4f} PLS"
            )

        parts.append(f"  PLS balance: {pls_balance:.1f} | Runner-up: {runner_up}")
        parts.append(
            f"  Session P&L: {self.total_session_profit:.4f} PLS over {self.cycles_run} cycles"
        )

        return "\n".join(parts)

    # ── Approval logic ────────────────────────────────────────────────────────

    def _auto_approve(self, rec: Recommendation) -> bool:
        """Auto-approve if confidence meets threshold."""
        rec_level = self.CONFIDENCE_ORDER.get(rec.confidence, 0)
        threshold_level = self.CONFIDENCE_ORDER.get(self.AUTO_THRESHOLD, 2)
        approved = rec_level >= threshold_level
        if not approved:
            log.info("Auto-skip: %s confidence=%s (threshold=%s)",
                     rec.engine.name if rec.engine else "none",
                     rec.confidence, self.AUTO_THRESHOLD)
        return approved

    def _prompt_operator(self, rec: Recommendation) -> bool:
        """Print recommendation and wait for operator Y/N."""
        print()
        print("=" * 60)
        print("  STRATEGIST RECOMMENDATION")
        print("=" * 60)
        print(rec.rationale)
        if rec.risk_notes:
            print(f"  Risks: {', '.join(rec.risk_notes)}")
        print("=" * 60)

        if rec.confidence == "SKIP":
            print("  -> Auto-skipping (no viable engine)")
            return False

        try:
            answer = input("  Execute? [Y/n/q] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False

        if answer == "q":
            raise KeyboardInterrupt("Operator quit")
        return answer in ("", "y", "yes")

    # ── Persistent state ──────────────────────────────────────────────────────

    def _load_state(self) -> None:
        """Load persistent stats from disk."""
        if not _STATE_FILE.exists():
            return
        try:
            with open(_STATE_FILE) as f:
                data = json.load(f)
            for name, sd in data.get("engine_stats", {}).items():
                self.stats[name] = EngineStats.from_dict(sd)
            log.info("Loaded strategist state: %d engines tracked", len(self.stats))
        except Exception as exc:
            log.warning("Failed to load strategist state: %s", exc)

    def _save_state(self) -> None:
        """Persist stats to disk."""
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "engine_stats": {name: s.to_dict() for name, s in self.stats.items()},
            "last_save_epoch": time.time(),
            "total_session_profit": round(self.total_session_profit, 6),
        }
        try:
            with open(_STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            log.warning("Failed to save strategist state: %s", exc)

    # ── Status / diagnostics ──────────────────────────────────────────────────

    def print_status(self) -> None:
        """Print strategist state summary."""
        print(f"\n{'━' * 50}")
        print("  Strategist Status")
        print(f"{'━' * 50}")
        print(f"  Mode:           {'Interactive' if self.interactive else 'Auto'}")
        print(f"  Auto threshold: {self.AUTO_THRESHOLD}")
        print(f"  Session P&L:    {self.total_session_profit:.4f} PLS")
        print(f"  Cycles run:     {self.cycles_run}")
        print()

        if not self.stats:
            print("  No engine history yet.")
        else:
            print(f"  {'Engine':<15} {'Runs':>5} {'Wins':>5} {'Rate':>6} "
                  f"{'Net PLS':>10} {'Best':>10} {'Last':>10}")
            print(f"  {'-' * 15} {'-' * 5} {'-' * 5} {'-' * 6} "
                  f"{'-' * 10} {'-' * 10} {'-' * 10}")
            for name, s in sorted(self.stats.items()):
                print(f"  {name:<15} {s.total_runs:>5} {s.total_successes:>5} "
                      f"{s.win_rate:>5.0%} {s.net_pls:>10.4f} "
                      f"{s.best_profit_pls:>10.4f} {s.last_profit_pls:>10.4f}")

        print(f"{'━' * 50}\n")
