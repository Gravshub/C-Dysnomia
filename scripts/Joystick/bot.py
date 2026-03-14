"""
bot.py — Joystick: Dysnomia Self-Regulating Arbitrage Bot

Orchestrates all income engines with an active-intelligence Strategist:
  Engine 1 — Arb:          Purchase → DEX arb (AFFECTION/pDAI routes)
  Engine 2 — DSS:          chatAndClaimWithMultiplier → GIBS → PLS
  Engine 3 — Beat:         META.Beat() territory metrics
  Engine 4 — TokenFactory: AFFECTION Generate() gas-mint + WM batch mint + token mint/sell
  Engine 5 — LAU:          ABUPRU Faung advancement + EmitSniper
  Engine 6 — DaVINCI:      Treasury sniping via recon data
  Engine 7 — BACKBONE:     Spine runner (V2 Federal mint-claim loop)
  Engine 8 — PHR3AK:       Token web manipulation (DEPLOY/ARM/STITCH)

Per-cycle flow:
  0. Multicall balance snapshot (1 RPC call)
  1. Gas guard — abort if PLS < 100K floor, emergency-sell to refill
  2. Nonce reset — fresh nonce from chain
  3. Strategist.evaluate() — scores all engines, returns Recommendation
  4. Interactive: ask operator for approval | Auto: approve if confidence >= MEDIUM
  5. Execute approved engine (one per cycle to avoid nonce contention)
  6. Strategist.record() — persist P&L and engine stats
  7. Compound profits: 25% stays as PLS, 75% → AFFECTION for next arb
  8. Run eligible gameplay loops (Terraform, etc.)

Usage:
  python -m scripts.Joystick.bot                    # auto mode
  python -m scripts.Joystick.bot --interactive      # ask before each action
  python -m scripts.Joystick.bot --dry-run          # simulate only, no TXs
  python -m scripts.Joystick.bot --once             # run one cycle and exit
  python -m scripts.Joystick.bot --status           # print engine/strategist status and exit
  python -m scripts.Joystick.bot --beat-only        # run Beat engine only (debugging)

Env:
  DYSNOMIA_PRIVATE_KEY   Joey's wallet key
  PULSECHAIN_RPC         Override RPC (default: https://rpc.pulsechain.com)
  CYCLE_DELAY            Seconds between cycles (default: 30)
  PLS_GAS_FLOOR          Min PLS to keep (default: 100000 PLS)
  PROFIT_SPLIT           Fraction kept as PLS (default: 0.25)
"""
import argparse
import logging
import logging.handlers
import os
import time
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from .core.config import (
    JOEY_WALLET, AFFECTION, WPLS, PULSEX_V1_ROUTER,
    CYCLE_DELAY, PROFIT_SPLIT, PLS_GAS_FLOOR, AdaptiveDelay,
)
from .core.chain import snapshot_balances, router_contract, w3_submit, rpc_health, get_read_pool
from .core.wallet import reset_nonce, fmt_pls, pls_balance
from .core.executor import send_tx
from .core.gas_guard import GasGuard
from .core.gas_oracle import GasOracle
from .core.simulator import SimulationFailed, GasTooHigh
from .core.event_logger import events as _events
from .core.strategist import Strategist
from .engines.arb   import ArbEngine
from .engines.dss   import DSSEngine
from .engines.beat  import BeatEngine
from .engines.token_factory import TokenFactoryEngine
from .engines.lau import LAUEngine
from .engines.treasury_sniper import TreasurySniperEngine
from .engines.spine_runner import SpineRunnerEngine
from .engines.phreak import PhreakEngine
from .loops.terraform import TerraformLoop
from .oracle.route_auditor import route_summary

log = logging.getLogger("joystick")


class DysnomiaBot:
    """
    The Joystick orchestrator.

    Adding a new engine:   self.engines.append(NewEngine())
    Adding a new loop:     self.loops.append(NewLoop())
    No other changes required — Strategist picks the best engine each cycle.
    """

    def __init__(self, dry_run: bool = False, interactive: bool = False):
        self.dry_run    = dry_run
        self.cycle      = 0
        self.gas_guard  = GasGuard()
        self.gas_oracle = GasOracle()
        self.delay      = AdaptiveDelay()

        # Engine priority is determined by Strategist scoring each cycle.
        # List order only matters as a tiebreaker within equal scores.
        self.engines = [
            ArbEngine(),
            DSSEngine(),
            BeatEngine(with_cheon=True),
            TokenFactoryEngine(),
            LAUEngine(),
            TreasurySniperEngine(),
            SpineRunnerEngine(),
            PhreakEngine(),
        ]

        # Active intelligence layer — evaluates, recommends, tracks P&L
        self.strategist = Strategist(self.engines, interactive=interactive)

        # Gameplay loops run after engines (lower priority, positional)
        self.loops = [
            TerraformLoop(),
        ]

    # ── Public entry points ────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """Main loop. Ctrl-C to stop gracefully."""
        mode = "interactive" if self.strategist.interactive else "auto"
        log.info("Joystick starting. Wallet: %s  Mode: %s  Dry-run: %s",
                 JOEY_WALLET, mode, self.dry_run)
        _events.log("bot.start", data={
            "wallet": JOEY_WALLET,
            "mode": mode,
            "dry_run": self.dry_run,
            "engines": [e.name for e in self.engines],
            "loops": [l.name for l in self.loops],
        })
        while True:
            try:
                outcome = self.run_cycle()
            except KeyboardInterrupt:
                log.info("Interrupted — stopping.")
                _events.log("bot.stop", notes="KeyboardInterrupt")
                break
            except GasTooHigh as exc:
                self.delay.after_gas_high()
                log.warning("Gas too high: %s — sleeping %.0fs",
                            exc, self.delay.seconds)
                self.delay.wait()
                continue
            except Exception as exc:
                log.error("Cycle %d uncaught: %s", self.cycle, exc, exc_info=True)
                outcome = "failure"

            # Adaptive delay based on cycle outcome
            if outcome == "profit":
                self.delay.after_profit()
            elif outcome == "skip":
                self.delay.after_skip()
            else:  # "failure", "strategic"
                self.delay.after_failure()

            self.cycle += 1
            log.info("Cycle %d done — sleeping %.0fs", self.cycle - 1, self.delay.seconds)
            self.delay.wait()

    def run_cycle(self) -> str:
        """Single bot cycle. Returns outcome: 'profit', 'skip', 'failure', or 'strategic'."""
        log.info("━━━ Cycle %d ━━━", self.cycle)

        # 0. Balance snapshot (Multicall3: 1 RPC call)
        snap = snapshot_balances()
        log.info(
            "PLS=%.1f  AFF=%.4f  GIBS=%.1f  WM=%.4f  Fornax=%.4f",
            snap["pls"] / 1e18, snap["affection"] / 1e18,
            snap["gibs"] / 1e18, snap["wm"] / 1e18, snap["fornax"] / 1e18,
        )
        _events.log_balance_snapshot(snap)

        # 0b. Gas oracle update (rolling window)
        gas_price = self.gas_oracle.update()
        gas_status = self.gas_oracle.status()
        log.info(
            "Gas: %.0f Gwei (avg=%.0f, trend=%s, ceil=%.0f)",
            gas_status["current_gwei"], gas_status["average_gwei"],
            gas_status["trend"], gas_status["ceiling_gwei"],
        )

        # Gas above ceiling — raise GasTooHigh so run() uses the existing
        # adaptive delay path (after_gas_high → 2x backoff, not after_skip
        # which would cause exponential backoff every cycle)
        if self.gas_oracle.is_above_ceiling():
            raise GasTooHigh(
                f"Gas {gas_status['current_gwei']:.0f} Gwei > "
                f"ceiling {gas_status['ceiling_gwei']:.0f}"
            )

        # 1. Gas guard
        if not self.gas_guard.check():
            _events.log("bot.gas_guard.low", success=False, data={"pls_wei": snap["pls"]})
            if not self.dry_run:
                if not self.gas_guard.emergency_refill():
                    log.error("Emergency refill failed — skipping cycle")
                    _events.log_error("bot.gas_guard.refill_failed", "Emergency refill failed")
                    return "failure"
            else:
                log.warning("[dry-run] Gas below floor — would trigger emergency refill")
                return "failure"

        # 2. Reset nonce for fresh cycle
        reset_nonce()

        engines_status = [e.status_line() for e in self.engines]

        # 3. Strategist evaluates all engines and returns a recommendation
        rec = self.strategist.evaluate(snap)
        engine_ran = ""
        result_notes = ""
        cycle_success = True

        cycle_outcome = "skip"

        # Advisory: log if gas is falling (non-urgent engines may benefit from waiting)
        if self.gas_oracle.should_wait():
            log.info("GasOracle: gas is falling — non-urgent engines may benefit from waiting")

        if rec.engine is None or not rec.approved:
            reason = rec.rationale.split("\n")[0] if rec.rationale else "No recommendation"
            log.info("Strategist: %s", reason)
        else:
            engine = rec.engine
            log.info("▶ %s [%s]: est profit %.4f PLS (gas %.4f PLS, ROI %.2fx)",
                     engine.name, rec.confidence, rec.profit_est, rec.gas_est, rec.roi)

            # Measure realized PLS profit via balance delta
            pls_before = pls_balance()

            result = engine.execute(dry_run=self.dry_run)
            _events.log_engine_result(engine.name, result, cycle_num=self.cycle)

            # Record into both engine circuit breaker AND strategist P&L
            self.strategist.record(engine.name, result)

            if result.success:
                engine.record_success()

                pls_after = pls_balance()
                realized_profit = max(0, pls_after - pls_before)

                log.info("✓ %s: reported=%.4f PLS  realized=%.4f PLS  TXs=%d  notes=%s",
                         engine.name, result.net_pls, realized_profit / 1e18,
                         len(result.tx_hashes), result.notes)

                if realized_profit > 0 and not self.dry_run:
                    self.compound(realized_profit)
                    cycle_outcome = "profit"
                else:
                    cycle_outcome = "strategic"
            else:
                engine.record_failure()
                log.error("✗ %s failed: %s", engine.name, result.notes)
                cycle_success = False
                cycle_outcome = "failure"

            # Structured cycle log line (TASK 5)
            now = datetime.now()
            ts_str = now.strftime("%H:%M:%S")
            dt_str = now.strftime("%m/%d/%Y")
            tx_short = result.tx_hashes[0][:10] + "..." if result.tx_hashes else "none"
            if result.success:
                log.info(
                    "[CYCLE %d] [Time '%s' Date '%s'] [%s] [SUCCESS] "
                    "profit=+%.2f PLS | gas=%.1f PLS | net=+%.2f PLS | roi=%.2fx | tx=%s",
                    self.cycle, ts_str, dt_str, engine.name,
                    result.profit_pls, result.gas_pls, result.net_pls,
                    rec.roi, tx_short,
                )
            else:
                log.info(
                    "[CYCLE %d] [Time '%s' Date '%s'] [%s] [FAILED]  "
                    "profit=0 PLS | gas=0 PLS | reason=%s",
                    self.cycle, ts_str, dt_str, engine.name,
                    result.notes[:100],
                )

            engine_ran = engine.name
            result_notes = result.notes

        # 5. Gameplay loops (after engine — lower priority)
        for loop in self.loops:
            if loop.is_throttled():
                continue
            if loop.should_run():
                log.info("▶ Loop: %s", loop.name)
                result = loop.run(dry_run=self.dry_run)
                if result.success:
                    log.info("✓ %s: %s", loop.name, result.notes)
                    _events.log(
                        f"loop.{loop.name.lower()}.success",
                        data={"tx_hashes": result.tx_hashes},
                        notes=result.notes,
                    )
                else:
                    log.warning("✗ %s: %s", loop.name, result.notes)
                    _events.log(
                        f"loop.{loop.name.lower()}.failure",
                        success=False,
                        notes=result.notes,
                    )

        # 6. Periodic RPC health log (every 100 cycles)
        if self.cycle > 0 and self.cycle % 100 == 0:
            for r in get_read_pool().health_report():
                log.info("RPC[read] %s: %sms err=%s%%", r["name"], r["latency_ms"], r["error_rate"])

        # 7. Cycle summary event
        _events.log_cycle(
            cycle_num=self.cycle,
            balances=snap,
            engines_status=engines_status,
            engine_ran=engine_ran,
            result_notes=result_notes,
            success=cycle_success,
        )

        return cycle_outcome

    def compound(self, profit_pls_wei: int) -> None:
        """
        Route profits: 25% stays as PLS (gas reserve + validator fund).
                       75% → buy AFFECTION for next arb cycle.
        Respects PLS_GAS_FLOOR — will reduce or skip to avoid breaching.
        """
        compound_wei = int(profit_pls_wei * (1.0 - PROFIT_SPLIT))
        if compound_wei < 10**16:  # < 0.01 PLS — not worth the gas
            return

        # Re-check gas floor after engine execution may have consumed PLS
        current_pls = pls_balance()
        headroom = current_pls - compound_wei
        if headroom < PLS_GAS_FLOOR:
            safe_compound = current_pls - PLS_GAS_FLOOR
            if safe_compound < 10**16:
                log.info("Compound skipped — would breach gas floor "
                         "(PLS=%.4f, floor=%.4f)",
                         current_pls / 1e18, PLS_GAS_FLOOR / 1e18)
                return
            log.info("Compound reduced: %.4f → %.4f PLS (gas floor protection)",
                     compound_wei / 1e18, safe_compound / 1e18)
            compound_wei = int(safe_compound)

        router = router_contract(w3=w3_submit)
        deadline = int(time.time()) + 300
        log.info("Compounding %.4f PLS → AFFECTION", compound_wei / 1e18)
        try:
            send_tx(
                router.functions.swapExactETHForTokens(
                    1, [WPLS, AFFECTION], JOEY_WALLET, deadline
                ),
                "Compound PLS → AFFECTION",
                dry_run=False,
                value=compound_wei,
                skip_simulate=True,  # Payable function — skip pre-call
            )
        except Exception as exc:
            log.warning("Compound TX failed: %s — profit stays as PLS", exc)

    # ── Status / diagnostics ──────────────────────────────────────────────────

    def print_status(self) -> None:
        """Print engine, strategist, and wallet status without running anything."""
        snap = snapshot_balances()
        print(f"\n{'━'*60}")
        print(f"  Joystick Status — {JOEY_WALLET}")
        print(f"{'━'*60}")
        print(f"  PLS:        {fmt_pls(snap['pls'])}")
        print(f"  AFFECTION:  {snap['affection'] / 1e18:.4f}")
        print(f"  GIBS:       {snap['gibs'] / 1e18:.4f}")
        print(f"  WM:         {snap['wm'] / 1e18:.4f}")
        print(f"  Fornax@LAU: {snap['fornax'] / 1e18:.6f}")
        print(f"  Gas floor:  {fmt_pls(PLS_GAS_FLOOR)}")
        print(f"  Guard OK:   {self.gas_guard.check()}")
        print()
        for e in self.engines:
            print(f"  {e.status_line()}")
        for lp in self.loops:
            print(f"  {lp.status_line()}")
        print()
        # RPC health
        print(f"  -- RPC Health --")
        rpc_health()
        # Route audit
        print(route_summary())
        print()
        print(f"  Gas Oracle: {self.gas_oracle}")
        print()
        # P&L summary table from Strategist
        print(self.strategist.summary())
        print()


# ── CLI ────────────────────────────────────────────────────────────────────────
def _setup_logging() -> None:
    """Configure console + rotating file handler for bot_run.log."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # Rotating file handler — 10MB, keep 3 backups
    log_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "bot_run.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s",
    ))
    root.addHandler(file_handler)


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Joystick — Dysnomia self-regulating arbitrage bot"
    )
    parser.add_argument("--dry-run",   action="store_true",
                        help="Simulate all operations — no TXs sent")
    parser.add_argument("--interactive", action="store_true",
                        help="Ask for approval before each engine execution")
    parser.add_argument("--once",      action="store_true",
                        help="Run exactly one cycle then exit")
    parser.add_argument("--status",    action="store_true",
                        help="Print engine/strategist/wallet status and exit")
    parser.add_argument("--beat-only", action="store_true",
                        help="Run only the Beat engine (diagnostics)")
    parser.add_argument("--lau-only", action="store_true",
                        help="Run only the LAU engine (ABUPRU sequence)")
    parser.add_argument("--log-status", action="store_true",
                        help="Print event log statistics and recent events")
    parser.add_argument("--rpc-status", action="store_true",
                        help="Print RPC provider health and exit")
    args = parser.parse_args()

    if args.rpc_status:
        print(f"\n{'━'*60}")
        print(f"  Joystick RPC Provider Health")
        print(f"{'━'*60}")
        rpc_health()
        return

    bot = DysnomiaBot(dry_run=args.dry_run, interactive=args.interactive)

    if args.log_status:
        from .core.event_logger import EventLogger
        print(f"\n{'━'*50}")
        print(f"  Joystick Event Log Status")
        print(f"{'━'*50}")
        for name in ["joystick_events", "cycles", "engine_lau", "engine_arb",
                      "engine_beat", "engine_dss", "engine_tokenfactory"]:
            count = EventLogger.event_count(name)
            if count > 0:
                print(f"  {name}.jsonl: {count} events")
        print()
        print("  Last 5 events:")
        for evt in EventLogger.read_events("joystick_events", last_n=5):
            ts = evt.get("ts", "?")[:19]
            ev = evt.get("event", "?")
            eng = evt.get("engine", "")
            ok = "OK" if evt.get("success", True) else "FAIL"
            notes = evt.get("notes", "")[:60]
            print(f"    {ts}  {ev:<35} {eng:<6} {ok:<5} {notes}")
        print(f"{'━'*50}\n")
        return

    if args.status:
        bot.print_status()
        return

    if args.beat_only:
        engine = next(e for e in bot.engines if e.name == "Beat")
        print(f"Beat ready: {engine.is_ready()}")
        result = engine.execute(dry_run=args.dry_run)
        print(f"Beat result: {result}")
        _events.log_engine_result("Beat", result)
        return

    if args.lau_only:
        engine = next(e for e in bot.engines if e.name == "LAU")
        _events.log("bot.lau_only_start", engine="LAU",
                    data={"dry_run": args.dry_run})
        print(f"LAU ready: {engine.is_ready()}")
        if not engine.is_ready():
            # Try running anyway for diagnostics
            print("LAU not ready — attempting simulate for diagnostics...")
            try:
                profit, gas = engine.simulate()
                print(f"  Simulate OK: profit={profit/1e18:.4f} PLS, gas={gas/1e18:.4f} PLS")
            except Exception as e:
                print(f"  Simulate failed: {e}")
                _events.log_error("engine.lau.sim_failed", str(e), engine="LAU")
                return
        result = engine.execute(dry_run=args.dry_run)
        _events.log_engine_result("LAU", result)
        print(f"LAU result: success={result.success} gas={result.gas_pls:.4f} PLS "
              f"txs={len(result.tx_hashes)} notes={result.notes}")
        return

    if args.once:
        bot.run_cycle()
        return

    bot.run_forever()


if __name__ == "__main__":
    main()
