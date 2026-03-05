"""
bot.py — Joystick: Dysnomia Self-Regulating Arbitrage Bot

Orchestrates all income engines with an active-intelligence Strategist:
  Engine 1 — Arb:          Purchase → DEX arb (AFFECTION/pDAI routes)
  Engine 2 — DSS:          chatAndClaimWithMultiplier → GIBS → PLS
  Engine 3 — Beat:         META.Beat() territory metrics
  Engine 4 — TokenFactory: TGSV8 token creation & swap
  Engine 5 — LAU:          ABUPRU Faung advancement + EmitSniper

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
import os
import time
import sys

from dotenv import load_dotenv
load_dotenv()

from .core.config import (
    JOEY_WALLET, AFFECTION, WPLS, PULSEX_V1_ROUTER,
    CYCLE_DELAY, PROFIT_SPLIT, PLS_GAS_FLOOR,
)
from .core.chain import snapshot_balances, router_contract, w3_submit
from .core.wallet import reset_nonce, fmt_pls, pls_balance
from .core.executor import send_tx
from .core.gas_guard import GasGuard
from .core.simulator import SimulationFailed, GasTooHigh
from .core.event_logger import events as _events
from .core.strategist import Strategist
from .engines.arb   import ArbEngine
from .engines.dss   import DSSEngine
from .engines.beat  import BeatEngine
from .engines.token_factory import TokenFactoryEngine
from .engines.lau import LAUEngine
from .loops.terraform import TerraformLoop

log = logging.getLogger("joystick")


class DysnomiaBot:
    """
    The Joystick orchestrator.

    Adding a new engine:   self.engines.append(NewEngine())
    Adding a new loop:     self.loops.append(NewLoop())
    No other changes required — Strategist picks the best engine each cycle.
    """

    def __init__(self, dry_run: bool = False, interactive: bool = False):
        self.dry_run   = dry_run
        self.cycle     = 0
        self.gas_guard = GasGuard()

        # Engine priority is determined by Strategist scoring each cycle.
        # List order only matters as a tiebreaker within equal scores.
        self.engines = [
            ArbEngine(),
            DSSEngine(),
            BeatEngine(with_cheon=True),
            TokenFactoryEngine(),
            LAUEngine(),
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
                self.run_cycle()
            except KeyboardInterrupt:
                log.info("Interrupted — stopping.")
                _events.log("bot.stop", notes="KeyboardInterrupt")
                break
            except GasTooHigh as exc:
                log.warning("Gas too high: %s — sleeping %ds", exc, CYCLE_DELAY * 2)
                time.sleep(CYCLE_DELAY * 2)
                continue
            except Exception as exc:
                log.error("Cycle %d uncaught: %s", self.cycle, exc, exc_info=True)

            self.cycle += 1
            log.info("Cycle %d done — sleeping %ds", self.cycle - 1, CYCLE_DELAY)
            time.sleep(CYCLE_DELAY)

    def run_cycle(self) -> None:
        """Single bot cycle."""
        log.info("━━━ Cycle %d ━━━", self.cycle)

        # 0. Balance snapshot (Multicall3: 1 RPC call)
        snap = snapshot_balances()
        log.info(
            "PLS=%.1f  AFF=%.4f  GIBS=%.1f  WM=%.4f  Fornax=%.4f",
            snap["pls"] / 1e18, snap["affection"] / 1e18,
            snap["gibs"] / 1e18, snap["wm"] / 1e18, snap["fornax"] / 1e18,
        )
        _events.log_balance_snapshot(snap)

        # 1. Gas guard
        if not self.gas_guard.check():
            _events.log("bot.gas_guard.low", success=False, data={"pls_wei": snap["pls"]})
            if not self.dry_run:
                if not self.gas_guard.emergency_refill():
                    log.error("Emergency refill failed — skipping cycle")
                    _events.log_error("bot.gas_guard.refill_failed", "Emergency refill failed")
                    return
            else:
                log.warning("[dry-run] Gas below floor — would trigger emergency refill")
                return

        # 2. Reset nonce for fresh cycle
        reset_nonce()

        engines_status = [e.status_line() for e in self.engines]

        # 3. Strategist evaluates all engines and returns a recommendation
        rec = self.strategist.evaluate(snap)
        engine_ran = ""
        result_notes = ""
        cycle_success = True

        if rec.engine is None or not rec.approved:
            reason = rec.rationale.split("\n")[0] if rec.rationale else "No recommendation"
            log.info("Strategist: %s", reason)
        else:
            engine = rec.engine
            log.info("▶ %s [%s]: est profit %.4f PLS (gas %.4f PLS, ROI %.2fx)",
                     engine.name, rec.confidence, rec.profit_est, rec.gas_est, rec.roi)

            result = engine.execute(dry_run=self.dry_run)
            _events.log_engine_result(engine.name, result, cycle_num=self.cycle)

            # Record into both engine circuit breaker AND strategist P&L
            self.strategist.record(engine.name, result)

            if result.success:
                engine.record_success()
                log.info("✓ %s: net %.4f PLS  TXs=%d  notes=%s",
                         engine.name, result.net_pls, len(result.tx_hashes), result.notes)
                if result.profit_wei > 0 and not self.dry_run:
                    self.compound(result.profit_wei)
            else:
                engine.record_failure()
                log.error("✗ %s failed: %s", engine.name, result.notes)
                cycle_success = False

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

        # 6. Cycle summary event
        _events.log_cycle(
            cycle_num=self.cycle,
            balances=snap,
            engines_status=engines_status,
            engine_ran=engine_ran,
            result_notes=result_notes,
            success=cycle_success,
        )

    def compound(self, profit_pls_wei: int) -> None:
        """
        Route profits: 25% stays as PLS (gas reserve + validator fund).
                       75% → buy AFFECTION for next arb cycle.
        """
        compound_wei = int(profit_pls_wei * (1.0 - PROFIT_SPLIT))
        if compound_wei < 10**16:  # < 0.01 PLS — not worth the gas
            return

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
        print(f"\n{'━'*50}")
        print(f"  Joystick Status — {JOEY_WALLET}")
        print(f"{'━'*50}")
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
        for l in self.loops:
            print(f"  {l.status_line()}")
        print()
        self.strategist.print_status()
        print(f"{'━'*50}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

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
    args = parser.parse_args()

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
