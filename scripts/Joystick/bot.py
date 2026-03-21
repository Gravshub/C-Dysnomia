"""
bot.py — Joystick V2: Dysnomia Self-Regulating Arbitrage Bot

3-wallet parallel pipeline with async orchestration:
  Engine 1 — Arb (RAZOR):     Purchase → DEX arb (AFFECTION/pDAI routes)     [Seller]
  Engine 2 — DSS (CEREAL):    chatAndClaimWithMultiplier → GIBS → PLS        [Joey]
  Engine 3 — Beat (MERIDIAN): META.Beat() territory metrics                  [Joey]
  Engine 4 — Factory:         AFFECTION Generate() + WM batch mint           [Minter]
  Engine 5 — LAU (ABUPRU):    ABUPRU Faung advancement + EmitSniper          [Joey]
  Engine 6 — DaVINCI:         Treasury sniping via recon data                [Minter]
  Engine 7 — BACKBONE:        Spine runner (V2 Federal mint-claim loop)      [Minter]
  Engine 8 — PHR3AK:          Token web manipulation (DEPLOY/ARM/STITCH)     [Minter]

Per-cycle flow (V2):
  0. Multicall balance snapshot (all 3 wallets, 1 RPC call)
  1. Gas guard — abort if PLS < 100K floor
  2. Nonce reset for all wallets
  3. Parallel simulate — all 8 engines via ThreadPoolExecutor (~300ms)
  4. Strategist V2 evaluate — returns CycleRecommendation (up to 3 actions)
  5. Parallel wallet execution — asyncio.gather() across wallets
  6. Record results, sell queue update, sweep check
  7. Gameplay loops (Terraform, etc.)

Usage:
  python -m scripts.Joystick.bot                    # auto mode
  python -m scripts.Joystick.bot --interactive      # ask before each action
  python -m scripts.Joystick.bot --dry-run          # simulate only, no TXs
  python -m scripts.Joystick.bot --once             # run one cycle and exit
  python -m scripts.Joystick.bot --status           # print engine/strategist status
  python -m scripts.Joystick.bot --wallet-status    # show 3-wallet balances + auth
  python -m scripts.Joystick.bot --single-wallet    # force single-wallet mode
  python -m scripts.Joystick.bot --beat-only        # run Beat engine only
  python -m scripts.Joystick.bot --lau-only         # run LAU engine only

Env:
  DYSNOMIA_PRIVATE_KEY   Joey's wallet key
  MINTER_PRIVATE_KEY     Minter wallet key (optional — enables multi-wallet)
  SELLER_PRIVATE_KEY     Seller wallet key (optional — enables multi-wallet)
  CYCLE_DELAY            Seconds between cycles (default: 30)
  PLS_GAS_FLOOR          Min PLS to keep (default: 100000 PLS)
"""
import argparse
import asyncio
import logging
import logging.handlers
import os
import time
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv("/opt/joystick/.env")
load_dotenv()  # also check cwd for overrides

from .core.config import (
    JOEY_WALLET, AFFECTION, WPLS, GIBS_LAU, PULSEX_V1_ROUTER, TGSV8PLUS,
    CYCLE_DELAY, PROFIT_SPLIT, PLS_GAS_FLOOR, AdaptiveDelay,
)
from .core.chain import snapshot_balances, router_contract, w3_submit, rpc_health, get_read_pool
from .core.wallet import reset_nonce, fmt_pls, pls_balance
from .core.executor import send_tx
from .core.gas_guard import GasGuard
from .core.gas_oracle import GasOracle
from .core.simulator import SimulationFailed, GasTooHigh
from .core.event_logger import events as _events
from .core.strategist import Strategist, CycleRecommendation
from .core.concurrency import SimExecutor
from .core.wallet_manager import WalletManager, WalletRole
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

from .core.log_names import get_logger, fmt_pls as fmt_pls_comma, fmt_int, fmt_pls_short
log = get_logger("joystick")


class DysnomiaBot:
    """
    The Joystick V2 orchestrator.

    3-wallet parallel pipeline with async simulation and execution.
    Falls back to single-wallet mode if worker keys are not configured.
    """

    def __init__(
        self,
        dry_run: bool = False,
        interactive: bool = False,
        force_single_wallet: bool = False,
    ):
        self.dry_run    = dry_run
        self.cycle      = 0
        self.gas_guard  = GasGuard()
        self.gas_oracle = GasOracle()
        self.delay      = AdaptiveDelay()

        # Multi-wallet manager (gracefully degrades to single-wallet)
        self.wallet_mgr = WalletManager()
        self.multi_wallet = self.wallet_mgr.is_multi_wallet and not force_single_wallet
        if force_single_wallet and self.wallet_mgr.is_multi_wallet:
            log.info("--single-wallet: forcing single-wallet mode")

        # Engine priority is determined by Strategist scoring each cycle.
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

        # Active intelligence layer V2
        self.strategist = Strategist(
            self.engines,
            interactive=interactive,
            gas_oracle=self.gas_oracle,
            multi_wallet=self.multi_wallet,
        )

        # Parallel simulation executor
        self.sim_executor = SimExecutor()

        # Sell queue (tracks TGSv8 token balances for Seller)
        self.sell_queue = None
        try:
            from .core.config import TGSV8
            if TGSV8:
                from .core.sell_queue import SellQueue
                self.sell_queue = SellQueue(TGSV8)
        except Exception:
            pass

        # Gameplay loops — disabled pending web-interface plug-in system
        # self.loops = [
        #     TerraformLoop(),
        # ]
        self.loops = []

    # ── Public entry points ────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """Main loop. Ctrl-C to stop gracefully."""
        mode = "interactive" if self.strategist.interactive else "auto"
        wallet_mode = "multi-wallet" if self.multi_wallet else "single-wallet"
        log.info("🚀 Joystick V2 starting. Wallet: %s  Mode: %s  Wallets: %s  Dry-run: %s",
                 JOEY_WALLET, mode, wallet_mode, self.dry_run)
        _events.log("bot.start", data={
            "wallet": JOEY_WALLET,
            "mode": mode,
            "wallet_mode": wallet_mode,
            "dry_run": self.dry_run,
            "engines": [e.name for e in self.engines],
            "loops": [l.name for l in self.loops],
        })

        # Use asyncio event loop for the main cycle
        try:
            asyncio.run(self._async_run_forever())
        except KeyboardInterrupt:
            log.info("Interrupted — stopping.")
            _events.log("bot.stop", notes="KeyboardInterrupt")
        finally:
            self.sim_executor.shutdown()

    async def _async_run_forever(self) -> None:
        """Async main loop."""
        while True:
            try:
                outcome = await self._async_run_cycle()
            except KeyboardInterrupt:
                raise
            except GasTooHigh as exc:
                self.delay.after_gas_high()
                log.warning("Gas too high: %s — sleeping %.0fs",
                            exc, self.delay.seconds)
                await asyncio.sleep(self.delay.seconds)
                continue
            except Exception as exc:
                log.error("Cycle %d uncaught: %s", self.cycle, exc, exc_info=True)
                outcome = "failure"

            # Adaptive delay based on cycle outcome
            if outcome == "profit":
                self.delay.after_profit()
            elif outcome == "skip":
                self.delay.after_skip()
            else:
                self.delay.after_failure()

            self.cycle += 1
            log.info("😴 Cycle %d done — sleeping %.0fs", self.cycle - 1, self.delay.seconds)
            await asyncio.sleep(self.delay.seconds)

    def run_cycle(self) -> str:
        """Synchronous wrapper for backward compat with --once."""
        return asyncio.run(self._async_run_cycle())

    async def _async_run_cycle(self) -> str:
        """Single bot cycle (async). Returns outcome: 'profit', 'skip', 'failure', or 'strategic'."""
        log.info("━━━ Cycle %d ━━━", self.cycle)

        # 0. Balance snapshot (Multicall3: 1 RPC call)
        extra_wallets = []
        if self.multi_wallet:
            if self.wallet_mgr.minter:
                extra_wallets.append(self.wallet_mgr.minter.address)
            if self.wallet_mgr.seller:
                extra_wallets.append(self.wallet_mgr.seller.address)

        snap = snapshot_balances(extra_wallets=extra_wallets or None)
        log.info(
            "💰 PLS=%s  AFF=%.4f  GIBS=%.4f  WM=%.4f  Fornax=%.4f",
            fmt_pls_comma(snap["pls"]), snap["affection"] / 1e18,
            snap["gibs"] / 1e18, snap["wm"] / 1e18, snap["fornax"] / 1e18,
        )
        if self.multi_wallet:
            for key in ["pls_minter", "pls_seller"]:
                if key in snap:
                    log.info("  %s=%.1f", key, snap[key] / 1e18)

        # TGSv8+ balance tracking (if configured)
        if TGSV8PLUS:
            from .core.chain import erc20, safe, multicall
            aff_c = erc20(AFFECTION)
            gibs_c = erc20(GIBS_LAU)
            wpls_c = erc20(WPLS)
            plus_bals = multicall([
                (aff_c, "balanceOf", [TGSV8PLUS]),
                (gibs_c, "balanceOf", [TGSV8PLUS]),
                (wpls_c, "balanceOf", [TGSV8PLUS]),
            ])
            snap["aff_plus"] = plus_bals[0] or 0
            snap["gibs_plus"] = plus_bals[1] or 0
            snap["wpls_plus"] = plus_bals[2] or 0
            log.info("  TGSv8+: AFF=%.1f  GIBS=%.1f  WPLS=%.1f",
                     snap["aff_plus"] / 1e18,
                     snap["gibs_plus"] / 1e18,
                     snap["wpls_plus"] / 1e18)

        _events.log_balance_snapshot(snap)

        # 0b. Gas oracle update (rolling window)
        gas_price = self.gas_oracle.update()
        gas_status = self.gas_oracle.status()
        log.info(
            "⛽ Gas: %s Beats (avg=%s, trend=%s, ceil=%s)",
            fmt_int(gas_status["current_beats"]), fmt_int(gas_status["average_beats"]),
            gas_status["trend"], fmt_int(gas_status["ceiling_beats"]),
        )

        if self.gas_oracle.is_above_ceiling():
            raise GasTooHigh(
                f"Gas {fmt_int(gas_status['current_beats'])} Beats > "
                f"ceiling {fmt_int(gas_status['ceiling_beats'])}"
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

        # 2. Reset nonces for all wallets
        reset_nonce()
        if self.multi_wallet:
            self.wallet_mgr.reset_all_nonces()

        engines_status = [e.status_line() for e in self.engines]

        # 3. Parallel simulate — all engines via ThreadPoolExecutor
        sim_results = await self.sim_executor.parallel_simulate(self.engines)

        # 4. Strategist V2 evaluates and returns CycleRecommendation
        cycle_rec = self.strategist.evaluate(snap, sim_results, self.gas_oracle)

        # Advisory: log if gas is falling
        if self.gas_oracle.should_wait():
            log.info("📉 Gas falling — non-urgent engines may benefit from waiting")

        cycle_outcome = "skip"
        engine_ran = ""
        result_notes = ""
        cycle_success = True

        # 5. Execute recommendations
        # In multi-wallet mode, we could run in parallel.
        # For now, execute sequentially per wallet for safety.
        for rec in cycle_rec.all_recommendations():
            if rec.engine is None or not rec.approved:
                reason = rec.rationale.split("\n")[0] if rec.rationale else "No recommendation"
                log.info("🧠 Strategist [%s]: %s", rec.wallet_role, reason)
                continue

            engine = rec.engine
            log.info("▶ %s [%s] → %s: est profit %.4f PLS (gas %.4f PLS, ROI %.2fx)",
                     engine.display_name, rec.confidence, rec.wallet_role,
                     rec.profit_est, rec.gas_est, rec.roi)

            # Measure realized PLS profit via balance delta
            pls_before = pls_balance()

            result = engine.execute(dry_run=self.dry_run)
            _events.log_engine_result(engine.name, result, cycle_num=self.cycle)

            # Record into strategist P&L
            self.strategist.record(engine.name, result, wallet_role=rec.wallet_role)

            if result.success:
                engine.record_success()

                pls_after = pls_balance()
                realized_profit = max(0, pls_after - pls_before)

                log.info("✓ %s [%s]: reported=%.4f PLS  realized=%.4f PLS  TXs=%d  notes=%s",
                         engine.display_name, rec.wallet_role,
                         result.net_pls, realized_profit / 1e18,
                         len(result.tx_hashes), result.notes)

                if realized_profit > 0 and not self.dry_run and not self.multi_wallet:
                    # Only auto-compound in single-wallet mode
                    self.compound(realized_profit)
                    cycle_outcome = "profit"
                elif realized_profit > 0:
                    cycle_outcome = "profit"
                else:
                    cycle_outcome = "strategic"
            else:
                engine.record_failure()
                log.error("✗ %s [%s] failed: %s", engine.display_name,
                          rec.wallet_role, result.notes)
                cycle_success = False
                cycle_outcome = "failure"

            # Structured cycle log line
            tx_short = result.tx_hashes[0][:10] + "..." if result.tx_hashes else "none"
            if result.success:
                log.info(
                    "✅ [CYCLE %d] [%s] [%s] profit=+%s PLS | gas=%s PLS | net=+%s PLS | roi=%.2fx | tx=%s",
                    self.cycle, engine.display_name, rec.wallet_role,
                    fmt_pls_short(result.profit_pls), fmt_pls_short(result.gas_pls),
                    fmt_pls_short(result.net_pls), rec.roi, tx_short,
                )
            else:
                log.info(
                    "❌ [CYCLE %d] [%s] [%s] FAILED | reason=%s",
                    self.cycle, engine.display_name, rec.wallet_role,
                    result.notes[:100],
                )

            engine_ran = engine.name
            result_notes = result.notes

        # 6. Sweep check (multi-wallet mode)
        if self.multi_wallet and not self.dry_run:
            if self.wallet_mgr.check_sweep():
                log.info("🧹 Sweep threshold exceeded — sweeping Seller PLS to Joey")
                self.wallet_mgr.execute_sweep(dry_run=self.dry_run)

        # 7. Gameplay loops (after engines — lower priority)
        for loop in self.loops:
            if loop.is_throttled():
                continue
            if loop.should_run():
                log.info("▶ Loop: %s", loop.name)
                result = loop.run(dry_run=self.dry_run)
                if result.success:
                    log.info("🔄 %s: %s", loop.name, result.notes)
                    _events.log(
                        f"loop.{loop.name.lower()}.success",
                        data={"tx_hashes": result.tx_hashes},
                        notes=result.notes,
                    )
                else:
                    log.warning("⚠️ %s: %s", loop.name, result.notes)
                    _events.log(
                        f"loop.{loop.name.lower()}.failure",
                        success=False,
                        notes=result.notes,
                    )

        # 8. Background pair graph rebuild (between cycles, not during sim)
        arb_engine = next((e for e in self.engines if e.name == "Arb"), None)
        if arb_engine and getattr(arb_engine, '_needs_graph_rebuild', False):
            log.info("📊 Background pair graph rebuild...")
            try:
                from .oracle.pair_discovery import discover_pairs
                graph = discover_pairs()
                arb_engine._pair_graph = graph
                arb_engine._graph_last_refresh = time.time()
                arb_engine._needs_graph_rebuild = False
                log.info("📊 Pair graph rebuilt: %s edges, %s tokens",
                         fmt_int(graph.edge_count), fmt_int(graph.token_count))
            except Exception as exc:
                log.warning("📊 Background graph rebuild failed: %s", exc)
                arb_engine._needs_graph_rebuild = False

        # 9. Periodic RPC health log (every 100 cycles)
        if self.cycle > 0 and self.cycle % 100 == 0:
            for r in get_read_pool().health_report():
                log.info("RPC[read] %s: %sms err=%s%%", r["name"], r["latency_ms"], r["error_rate"])

        # 10. Cycle summary event
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
        Only used in single-wallet mode.
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
        print(f"  Joystick V2 Status — {JOEY_WALLET}")
        wallet_mode = "Multi-Wallet" if self.multi_wallet else "Single-Wallet"
        print(f"  Mode: {wallet_mode}")
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
        # P&L summary table from Strategist V2
        print(self.strategist.summary())
        print()

    def print_wallet_status(self) -> None:
        """Print 3-wallet balances, auth status, and nonces."""
        print(f"\n{'━'*60}")
        print(f"  Joystick V2 — Wallet Status")
        print(f"{'━'*60}")
        for line in self.wallet_mgr.wallet_status_lines():
            print(line)
        print(f"{'━'*60}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────
def _setup_logging() -> None:
    """Configure console + rotating file handler for bot_run.log."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler — no timestamp (journald/systemd provides it)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(name)-16s %(levelname)-8s %(message)s",
    ))
    root.addHandler(console)

    # Rotating file handler — 10MB, keep 3 backups (keeps timestamp for offline review)
    log_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "bot_run.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)-16s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Joystick V2 — Dysnomia 3-wallet parallel arbitrage bot"
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
    parser.add_argument("--single-wallet", action="store_true",
                        help="Force single-wallet mode even if worker keys are set")
    parser.add_argument("--wallet-status", action="store_true",
                        help="Show 3-wallet balances, auth status, nonces")
    parser.add_argument("--force-test", action="store_true",
                        help="Force one E4 TokenFactory diagnostic cycle (bypasses ROI threshold)")
    args = parser.parse_args()

    if args.rpc_status:
        print(f"\n{'━'*60}")
        print(f"  Joystick RPC Provider Health")
        print(f"{'━'*60}")
        rpc_health()
        return

    bot = DysnomiaBot(
        dry_run=args.dry_run,
        interactive=args.interactive,
        force_single_wallet=args.single_wallet,
    )

    if args.wallet_status:
        bot.print_wallet_status()
        return

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

    if args.force_test:
        # Enable force-test on the TokenFactory engine and run one cycle
        os.environ["FORCE_AFF_TEST"] = "1"
        for e in bot.engines:
            if e.name == "TokenFactory":
                e.FORCE_TEST = True
                break
        log.info("Force-test mode enabled for E4 TokenFactory")
        bot.run_cycle()
        return

    if args.once:
        bot.run_cycle()
        return

    bot.run_forever()


if __name__ == "__main__":
    main()
