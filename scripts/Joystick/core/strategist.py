"""
strategist.py — Active Intelligence Layer V2 for Joystick Bot

The Strategist sits between the balance snapshot and engine execution in bot.py.
It evaluates all engines, tracks cumulative P&L, and produces a CycleRecommendation
with up to 3 actions (one per wallet: Joey, Minter, Seller).

V2 Improvements:
  Phase A: Auto-discover engine roster (no hardcoded display list)
  Phase B: Removed stale DSS PAIR_UNCONFIRMED flag
  Phase C: SimResult dataclass integration
  Phase D: Rotation penalty (prevent engine monopolization)
  Phase E: GasOracle integration
  Phase F: Cross-engine dependency map (unlock bonuses)

Architecture:
  bot.py cycle:
    1. Balance snapshot (Multicall3)
    2. Parallel simulate (all 8 engines via ThreadPoolExecutor)
    3. Strategist.evaluate(balances, sim_results)   <-- HERE
       -> partitions by wallet_role
       -> scores each candidate
       -> returns CycleRecommendation with 3 Recommendations
    4. Parallel wallet execution
    5. Strategist.record(result)                    <-- HERE
    6. Sweep check

Persistent state: data/strategist_state.json — survives restarts.

Usage:
    from .core.strategist import Strategist

    strat = Strategist(engines, interactive=True)
    rec = strat.evaluate(balances, sim_results, gas_oracle)
    # rec.joey, rec.minter, rec.seller — each a Recommendation or None
"""
import json
import logging

from .log_names import get_logger
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engines.base import EngineBase, EngineResult, SimResult
    from .gas_oracle import GasOracle

log = get_logger("joystick.strategist")

_JOYSTICK_DIR = Path(__file__).parent.parent
_STATE_FILE = _JOYSTICK_DIR / "data" / "strategist_state.json"

# Validator goal — 32 million PLS
VALIDATOR_GOAL_PLS = 32_000_000

# Strategic engines — always valid to run regardless of profit or rotation
STRATEGIC_ENGINES = {"Beat", "LAU"}

# Revenue engines — get a score floor of 2.0 when profitable (ensures MEDIUM confidence)
# These are proven income generators that shouldn't be blocked by RPC jitter
REVENUE_ENGINES = {"DSS"}

# ── Cross-Engine Dependency Map (Phase F) ─────────────────────────────────────
# When an engine+mode unlocks another engine, score the unlock bonus.
UNLOCK_MAP: dict[tuple[str, str], list[str]] = {
    ("PHR3AK", "arm"):    ["SpineRunner"],   # ARM acquires OZZY → E7 unlocked
    ("PHR3AK", "deploy"): ["Arb"],           # new V4 pair → new arb edge
    ("PHR3AK", "stitch"): ["Arb"],           # new LP pair → new arb edge
    ("DSS", "harvest"):   ["Arb"],           # harvestCycle burns LP → permanent arb edges for RAZOR
}

# Default unlock bonus for engines with no historical data
DEFAULT_UNLOCK_BONUS = 2.0


# ── Data types ────────────────────────────────────────────────────────────────

class Confidence(Enum):
    SKIP = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class Recommendation:
    """Single-wallet recommendation from the Strategist."""
    engine: "EngineBase | None"   # None = skip this wallet
    rationale: str                # Human-readable explanation
    confidence: str               # "HIGH", "MEDIUM", "LOW", "SKIP"
    wallet_role: str = ""         # "joey", "minter", "seller"
    roi: float = 0.0             # Expected ROI multiplier
    profit_est: float = 0.0      # Estimated profit in PLS
    gas_est: float = 0.0         # Estimated gas cost in PLS
    pool_impact_pct: float = 0.0 # Estimated slippage/pool impact 0.0-100.0
    risk_notes: list[str] = field(default_factory=list)
    approved: bool = False        # Set True after operator approval or auto-approve


@dataclass
class CycleRecommendation:
    """Multi-wallet recommendation output from Strategist V2."""
    joey:     Recommendation | None
    minter:   Recommendation | None
    seller:   Recommendation | None
    rationale: str = ""

    @property
    def active_count(self) -> int:
        return sum(1 for r in [self.joey, self.minter, self.seller]
                   if r and r.approved)

    def all_recommendations(self) -> list[Recommendation]:
        """Return all non-None recommendations."""
        return [r for r in [self.joey, self.minter, self.seller] if r is not None]


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


# ── Strategist V2 ────────────────────────────────────────────────────────────

class Strategist:
    """
    Active intelligence layer V2. Multi-wallet brain.

    Evaluates engines, partitions by wallet_role, picks the best action
    per wallet each cycle. Returns CycleRecommendation with up to 3 actions.

    Backward compat: evaluate() without sim_results falls back to inline simulate().
    Single-wallet mode: all engines assigned to Joey.

    Modes:
      interactive=True:  Prints recommendation, waits for operator Y/N
      interactive=False: Auto-approves if confidence >= auto_threshold
    """

    AUTO_THRESHOLD = "MEDIUM"  # Auto-approve at this confidence or above
    CONFIDENCE_ORDER = {"SKIP": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}

    def __init__(
        self,
        engines: list["EngineBase"],
        interactive: bool = False,
        gas_oracle: "GasOracle | None" = None,
        multi_wallet: bool = False,
    ):
        self.engines = engines
        self.interactive = interactive
        self.gas_oracle = gas_oracle
        self.multi_wallet = multi_wallet
        self.stats: dict[str, EngineStats] = {}
        self.session_start = time.time()
        self.cycles_run = 0
        self.total_session_profit = 0.0
        self._load_state()

    # ── Core evaluate method (V2 — multi-wallet) ─────────────────────────────

    def evaluate(
        self,
        balances: dict,
        sim_results: "dict[str, SimResult] | None" = None,
        gas_oracle: "GasOracle | None" = None,
    ) -> CycleRecommendation:
        """
        Evaluate all engines and return a CycleRecommendation with up to 3 actions.

        If sim_results is provided (from parallel_simulate), uses pre-computed data.
        Otherwise falls back to inline simulate() calls (backward compat).
        """
        self.cycles_run += 1
        pls_bal = balances.get("pls", 0) / 1e18
        oracle = gas_oracle or self.gas_oracle

        from .config import CYCLE_DELAY

        # Gather candidates with simulation data
        scored_by_role: dict[str, list] = {"joey": [], "minter": [], "seller": []}

        for engine in self.engines:
            if engine.is_disabled():
                continue
            if not engine.is_ready():
                continue

            # Get simulation data
            if sim_results and engine.name in sim_results:
                sim = sim_results[engine.name]
                if not sim.success:
                    continue
                profit_pls = sim.profit_wei / 1e18
                gas_pls = sim.gas_wei / 1e18
                roi = sim.roi
                pool_impact = sim.pool_impact_pct
                mode = sim.mode
            else:
                # Fallback: inline simulate
                try:
                    profit_wei, gas_wei = engine.simulate()
                    profit_pls = profit_wei / 1e18
                    gas_pls = gas_wei / 1e18
                    roi = profit_wei / gas_wei if gas_wei > 0 else 0.0
                    pool_impact = getattr(engine, '_last_pool_impact_pct', 0.0)
                    mode = ""
                except Exception:
                    continue

            stats = self.stats.get(engine.name, EngineStats())

            # Score this candidate
            score, confidence, risks = self._score_candidate(
                engine, profit_pls, gas_pls, roi, stats, pls_bal,
                pool_impact=pool_impact, mode=mode, oracle=oracle,
                cycle_delay=CYCLE_DELAY,
            )

            # Determine wallet role
            if self.multi_wallet:
                role = engine.wallet_role
            else:
                role = "joey"  # Single-wallet: everything goes to Joey

            scored_by_role.setdefault(role, []).append(
                (score, engine, profit_pls, gas_pls, roi, confidence, risks, pool_impact)
            )

        # Pick best candidate per wallet role
        joey_rec = self._pick_best(scored_by_role.get("joey", []), "joey", pls_bal)
        minter_rec = self._pick_best(scored_by_role.get("minter", []), "minter", pls_bal)
        seller_rec = self._pick_best(scored_by_role.get("seller", []), "seller", pls_bal)

        # Build overall rationale
        active = [r for r in [joey_rec, minter_rec, seller_rec] if r and r.engine]
        if active:
            names = [f"{r.wallet_role}:{r.engine.name}" for r in active]
            rationale = f"Cycle {self.cycles_run}: {', '.join(names)}"
        else:
            rationale = f"Cycle {self.cycles_run}: No engines ready"

        # Approval
        for rec in [joey_rec, minter_rec, seller_rec]:
            if rec and rec.engine:
                if self.interactive:
                    rec.approved = self._prompt_operator(rec)
                else:
                    rec.approved = self._auto_approve(rec)

        return CycleRecommendation(
            joey=joey_rec,
            minter=minter_rec if self.multi_wallet else None,
            seller=seller_rec if self.multi_wallet else None,
            rationale=rationale,
        )

    def _pick_best(
        self,
        scored: list,
        wallet_role: str,
        pls_bal: float,
    ) -> Recommendation | None:
        """Pick the best scoring candidate for a wallet role."""
        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0]
        score, engine, profit_pls, gas_pls, roi, confidence, risks, pool_impact = best

        runner_up = scored[1][1].name if len(scored) > 1 else "none"
        rationale = self._build_rationale(
            engine, profit_pls, gas_pls, roi, confidence,
            self.stats.get(engine.name, EngineStats()),
            runner_up, pls_bal,
        )

        return Recommendation(
            engine=engine,
            rationale=rationale,
            confidence=confidence,
            wallet_role=wallet_role,
            roi=roi,
            profit_est=profit_pls,
            gas_est=gas_pls,
            pool_impact_pct=pool_impact,
            risk_notes=risks,
        )

    # ── Record outcome ────────────────────────────────────────────────────────

    def record(self, engine_name: str, result: "EngineResult", wallet_role: str = "") -> None:
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

    # ── Scoring internals (V2 — all 6 phases) ────────────────────────────────

    def _score_candidate(
        self,
        engine: "EngineBase",
        profit_pls: float,
        gas_pls: float,
        roi: float,
        stats: EngineStats,
        pls_balance: float,
        *,
        pool_impact: float = 0.0,
        mode: str = "",
        oracle: "GasOracle | None" = None,
        cycle_delay: int = 30,
    ) -> tuple[float, str, list[str]]:
        """
        Score a candidate engine. Returns (score, confidence, risk_notes).

        V2 scoring phases:
          1. ROI weight (primary)
          2. Win rate bonus
          3. Consecutive failure penalty
          4. Strategic engine floor
          5. PLS balance check
          6. Gas affordability check
          7. Profit/loss check
          8. Pool impact penalty (Phase C — from SimResult)
          9. Rotation penalty (Phase D)
          10. GasOracle integration (Phase E)
          11. Cross-engine unlock bonus (Phase F)
          12. New engine flag
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
            risks.append("RECENT_FAILURE")

        # 4. Strategic engines get a floor score (Beat, LAU advance game state)
        if engine.name in STRATEGIC_ENGINES and score < 1.0:
            score = max(score, 1.0)
            if profit_pls <= gas_pls:
                risks.append("Strategic run (no direct profit)")

        # 5. PLS balance below gas buffer floor
        from .config import PLS_GAS_FLOOR
        if pls_balance < PLS_GAS_FLOOR / 1e18:
            risks.append("BELOW_GAS_BUFFER")

        # 6. Gas affordability check
        if gas_pls > 0 and gas_pls > pls_balance * 0.1:
            risks.append(f"GAS_HIGH ({gas_pls:.1f} PLS > 10% of balance)")
            score -= 1.0

        # 7. Profit/loss check
        # Engines with unlock potential (ARM, DEPLOY, STITCH) are infrastructure
        # investments — don't penalize them for having profit=0.
        unlock_key = (engine.name, mode) if mode else None
        has_unlock = unlock_key and unlock_key in UNLOCK_MAP
        if profit_pls <= gas_pls and engine.name not in STRATEGIC_ENGINES and not has_unlock:
            risks.append("Unprofitable (profit <= gas)")
            score -= 5.0

        # 7b. Revenue engine floor — proven generators shouldn't be blocked by RPC jitter
        if engine.name in REVENUE_ENGINES and profit_pls > gas_pls and score < 2.0:
            score = 2.0

        # 8. Pool impact penalty (Phase C — from SimResult data)
        # Atropa ecosystem pools are inherently thin. atomicArb() reverts if
        # unprofitable, so worst case is gas loss (~240 PLS). Thresholds tuned
        # for PulseChain reality: accept higher impact when profit justifies it.
        if pool_impact > 10.0:
            risks.append("TRAP_POOL")
            score -= 5.0
        elif pool_impact > 5.0:
            risks.append("THIN_POOL")
            score -= 2.0
        elif pool_impact > 2.0:
            risks.append("POOL_IMPACT_MODERATE")
            score -= 0.5

        # 9. Rotation penalty (Phase D) — prevent engine monopolization
        if stats.last_run_epoch > 0:
            secs_since_last = time.time() - stats.last_run_epoch
            if (secs_since_last < cycle_delay * 3
                    and engine.name not in STRATEGIC_ENGINES):
                score -= 1.0
                risks.append("RECENT_RUN")

        # 10. GasOracle integration (Phase E) — defer non-urgent when gas is falling
        if oracle and oracle.should_wait():
            confidence_high = score >= 5.0
            if not confidence_high and engine.name not in STRATEGIC_ENGINES:
                risks.append("GAS_FALLING")

        # 11. Cross-engine unlock bonus (Phase F)
        unlock_key = (engine.name, mode) if mode else None
        if unlock_key and unlock_key in UNLOCK_MAP:
            blocked_engines = UNLOCK_MAP[unlock_key]
            for blocked_name in blocked_engines:
                blocked_stats = self.stats.get(blocked_name, EngineStats())
                if blocked_stats.total_successes > 0:
                    bonus = (blocked_stats.avg_profit_pls / max(gas_pls, 0.001)) * 0.5
                else:
                    bonus = DEFAULT_UNLOCK_BONUS
                score += bonus
                risks.append(f"UNLOCK:{blocked_name}")

        # 12. New engine flag
        if stats.total_runs == 0:
            risks.append("NEW_ENGINE")

        # Confidence mapping
        critical_risks = {"TRAP_POOL", "RECENT_FAILURE", "BELOW_GAS_BUFFER"}
        has_critical = len([r for r in risks if r in critical_risks]) > 0
        if score >= 5.0 and not has_critical:
            confidence = "HIGH"
        elif score >= 2.0:
            confidence = "MEDIUM"
        elif score >= 0.0:
            confidence = "LOW"
        else:
            confidence = "SKIP"

        # Pool impact degrades confidence
        if pool_impact > 2.0 and confidence == "HIGH":
            confidence = "MEDIUM"
        if pool_impact > 10.0 and confidence == "MEDIUM":
            confidence = "LOW"

        # Phase E: GAS_FALLING downgrades non-HIGH, non-strategic to SKIP
        if "GAS_FALLING" in risks and confidence not in ("HIGH",):
            if engine.name not in STRATEGIC_ENGINES:
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
            f"Recommend: {engine.display_name} [{confidence}]",
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
            log.info("⏭️ Auto-skip: %s confidence=%s (threshold=%s)",
                     rec.engine.name if rec.engine else "none",
                     rec.confidence, self.AUTO_THRESHOLD)
        return approved

    def _prompt_operator(self, rec: Recommendation) -> bool:
        """Print recommendation and wait for operator Y/N."""
        print()
        print("=" * 60)
        print(f"  STRATEGIST RECOMMENDATION [{rec.wallet_role.upper()}]")
        print("=" * 60)
        print(rec.rationale)
        if rec.risk_notes:
            print(f"  Risks: {', '.join(rec.risk_notes)}")
        print("=" * 60)

        if rec.confidence == "SKIP":
            print("  -> Auto-skipping (no viable engine)")
            return False

        try:
            answer = input(f"  Execute {rec.wallet_role}? [Y/n/q] ").strip().lower()
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
        """Persist stats to disk. Atomic write via rename to prevent corruption."""
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "engine_stats": {name: s.to_dict() for name, s in self.stats.items()},
            "last_save_epoch": time.time(),
            "total_session_profit": round(self.total_session_profit, 6),
        }
        tmp_path = _STATE_FILE.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(str(tmp_path), str(_STATE_FILE))
        except Exception as exc:
            log.warning("Failed to save strategist state: %s", exc)
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    # ── Status / diagnostics ──────────────────────────────────────────────────

    def print_status(self) -> None:
        """Print strategist state summary in the canonical P&L table format."""
        print()
        print(self.summary())

    def summary(self) -> str:
        """
        Formatted P&L summary table for --status output.
        Phase A: Auto-discovers engines from self.engines (no hardcoded list).
        Returns a multi-line string.
        """
        lines = []
        w = 60
        lines.append(f"{'━' * w}")
        lines.append(f" JOYSTICK P&L SUMMARY (V2)")
        lines.append(f"{'━' * w}")
        wallet_mode = "Multi-Wallet" if self.multi_wallet else "Single-Wallet"
        lines.append(f" Mode: {'Interactive' if self.interactive else 'Auto'}  |  "
                      f"Threshold: {self.AUTO_THRESHOLD}  |  Cycles: {self.cycles_run}  |  "
                      f"{wallet_mode}")
        lines.append(f"{'─' * w}")

        # Header row
        lines.append(
            f" {'Engine':<18} {'Calls':>5}  {'Win%':>5}  "
            f"{'Profit PLS':>11}  {'Gas PLS':>9}  {'Net PLS':>10}"
        )
        lines.append(f"{'─' * w}")

        # Phase A: Auto-discover from self.engines
        total_calls = 0
        total_successes = 0
        total_profit = 0.0
        total_gas = 0.0

        seen_names = set()
        for engine in self.engines:
            name = engine.name
            seen_names.add(name)
            s = self.stats.get(name, EngineStats())
            display = engine.display_name
            win_str = f"{s.win_rate:.0%}" if s.total_runs > 0 else "—%"
            lines.append(
                f" {display:<18} {s.total_runs:>5}  {win_str:>5}  "
                f"{s.total_profit_pls:>+11.1f}  {s.total_gas_pls:>9.1f}  "
                f"{s.net_pls:>+10.1f}"
            )
            total_calls += s.total_runs
            total_successes += s.total_successes
            total_profit += s.total_profit_pls
            total_gas += s.total_gas_pls

        # Also show any tracked engines not currently in the roster (historical)
        for name, s in sorted(self.stats.items()):
            if name not in seen_names:
                win_str = f"{s.win_rate:.0%}" if s.total_runs > 0 else "—%"
                lines.append(
                    f" {name:<18} {s.total_runs:>5}  {win_str:>5}  "
                    f"{s.total_profit_pls:>+11.1f}  {s.total_gas_pls:>9.1f}  "
                    f"{s.net_pls:>+10.1f}"
                )
                total_calls += s.total_runs
                total_successes += s.total_successes
                total_profit += s.total_profit_pls
                total_gas += s.total_gas_pls

        lines.append(f"{'─' * w}")
        total_win = f"{total_successes / total_calls:.0%}" if total_calls > 0 else "—%"
        total_net = total_profit - total_gas
        lines.append(
            f" {'TOTAL':<18} {total_calls:>5}  {total_win:>5}  "
            f"{total_profit:>+11.1f}  {total_gas:>9.1f}  {total_net:>+10.1f}"
        )

        # Goal progress
        from .chain import get_read_pool
        from .config import JOEY_WALLET
        try:
            pls_bal = get_read_pool().call(lambda w3: w3.eth.get_balance(JOEY_WALLET)) / 1e18
        except Exception:
            pls_bal = 0.0
        pct = (pls_bal / VALIDATOR_GOAL_PLS) * 100 if VALIDATOR_GOAL_PLS > 0 else 0
        lines.append(
            f" Goal progress: {pls_bal:,.0f} / {VALIDATOR_GOAL_PLS:,} PLS ({pct:.2f}%)"
        )
        lines.append(f"{'━' * w}")

        return "\n".join(lines)
