"""
bot.py — Joystick: Dysnomia Self-Regulating Arbitrage Bot

Orchestrates all income engines with a priority scheduler:
  Engine 1 — Arb:  Purchase → DEX arb (AFFECTION/pDAI routes)
  Engine 2 — DSS:  chatAndClaimWithMultiplier → GIBS → PLS
  Engine 3 — WM:   TGSv5 batch WM minting
  Engine 4 — Beat: META.Beat() territory metrics
  Engine 5 — TokenFactory: TGSV7 token creation & swap
  Engine 6 — LAU:  ABUPRU Faung advancement + EmitSniper

Per-cycle flow:
  0. Multicall balance snapshot (1 RPC call)
  1. Gas guard — abort if PLS < 100K floor, emergency-sell to refill
  2. Nonce reset — fresh nonce from chain
  3. Rank ready engines by simulated ROI
  4. Execute top profitable engine (one per cycle to avoid nonce contention)
  5. Compound profits: 25% stays as PLS, 75% → AFFECTION for next arb
  6. Run eligible gameplay loops (Terraform, etc.)

Usage:
  python -m scripts.Joystick.bot               # live mode
  python -m scripts.Joystick.bot --dry-run     # simulate only, no TXs
  python -m scripts.Joystick.bot --once        # run one cycle and exit
  python -m scripts.Joystick.bot --status      # print engine status and exit
  python -m scripts.Joystick.bot --beat-only   # run Beat engine only (debugging)

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
from .engines.arb   import ArbEngine
from .engines.dss   import DSSEngine
from .engines.wm    import WMEngine
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
    No other changes required.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run   = dry_run
        self.cycle     = 0
        self.gas_guard = GasGuard()

        # Engine priority is determined dynamically by ROI each cycle.
        # List order only matters as a tiebreaker.
        self.engines = [
            ArbEngine(),
            DSSEngine(),
            WMEngine(),
            BeatEngine(with_cheon=True),
            TokenFactoryEngine(),
            LAUEngine(),
        ]

        # Gameplay loops run after engines (lower priority, positional)
        self.loops = [
            TerraformLoop(),
        ]

    # ── Public entry points ────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """Main loop. Ctrl-C to stop gracefully."""
        log.info("Joystick starting. Wallet: %s  Dry-run: %s", JOEY_WALLET, self.dry_run)
        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                log.info("Interrupted — stopping.")
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

        # 1. Gas guard
        if not self.gas_guard.check():
            if not self.dry_run:
                if not self.gas_guard.emergency_refill():
                    log.error("Emergency refill failed — skipping cycle")
                    return
            else:
                log.warning("[dry-run] Gas below floor — would trigger emergency refill")
                return

        # 2. Reset nonce for fresh cycle
        reset_nonce()

        # 3. Rank engines by ROI (all read-only, no TXs)
        ready = [
            e for e in self.engines
            if not e.is_disabled() and e.is_ready()
        ]
        ranked = sorted(ready, key=lambda e: e.roi(), reverse=True)

        if not ranked:
            log.info("No engines ready this cycle")
        else:
            log.info("Engine ranking: %s",
                     " > ".join(f"{e.name}({e.roi():.2f}x)" for e in ranked))

        # 4. Execute top profitable engine (one per cycle)
        engine_ran = False
        for engine in ranked:
            try:
                profit, gas = engine.simulate()
            except SimulationFailed as exc:
                log.debug("%s simulate: %s", engine.name, exc)
                continue

            if profit <= gas and engine.name not in ("Beat", "LAU"):
                # Beat and LAU are allowed to run even at 0 profit (strategic)
                log.info("%s: unprofitable (%.4f vs %.4f PLS) — skip",
                         engine.name, profit / 1e18, gas / 1e18)
                continue

            log.info("▶ %s: expected profit %.4f PLS (gas %.4f PLS)",
                     engine.name, profit / 1e18, gas / 1e18)

            result = engine.execute(dry_run=self.dry_run)

            if result.success:
                engine.record_success()
                log.info("✓ %s: net %.4f PLS  TXs=%d  notes=%s",
                         engine.name, result.net_pls, len(result.tx_hashes), result.notes)
                if result.profit_wei > 0 and not self.dry_run:
                    self.compound(result.profit_wei)
            else:
                engine.record_failure()
                log.error("✗ %s failed: %s", engine.name, result.notes)

            engine_ran = True
            break  # One engine per cycle — avoid nonce issues

        if not engine_ran:
            log.info("No engine executed this cycle")

        # 5. Gameplay loops (after engine — lower priority)
        for loop in self.loops:
            if loop.is_throttled():
                continue
            if loop.should_run():
                log.info("▶ Loop: %s", loop.name)
                result = loop.run(dry_run=self.dry_run)
                if result.success:
                    log.info("✓ %s: %s", loop.name, result.notes)
                else:
                    log.warning("✗ %s: %s", loop.name, result.notes)

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
        """Print engine and wallet status without running anything."""
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
    parser.add_argument("--once",      action="store_true",
                        help="Run exactly one cycle then exit")
    parser.add_argument("--status",    action="store_true",
                        help="Print engine/wallet status and exit")
    parser.add_argument("--beat-only", action="store_true",
                        help="Run only the Beat engine (diagnostics)")
    args = parser.parse_args()

    bot = DysnomiaBot(dry_run=args.dry_run)

    if args.status:
        bot.print_status()
        return

    if args.beat_only:
        engine = next(e for e in bot.engines if e.name == "Beat")
        print(f"Beat ready: {engine.is_ready()}")
        result = engine.execute(dry_run=args.dry_run)
        print(f"Beat result: {result}")
        return

    if args.once:
        bot.run_cycle()
        return

    bot.run_forever()


if __name__ == "__main__":
    main()
