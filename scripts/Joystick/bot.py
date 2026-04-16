"""
bot.py — Joystick V2: Dysnomia Self-Regulating Arbitrage Bot

3-wallet parallel pipeline with async orchestration:
  Engine 1 — Arb (RAZOR):     Purchase → DEX arb (AFFECTION/pDAI routes)     [Seller]
  Engine 2 — DSS (CEREAL):    chatAndClaimWithMultiplier → GIBS → PLS        [Joey]
  Engine 3 — Beat (MERIDIAN): META.Beat() territory metrics                  [Joey]
  Engine 4 — Factory:         AFFECTION Generate() + WM batch mint           [Minter]
  Engine 5 — LAU (ABUPRU):    ABUPRU Faung advancement + EmitSniper          [Joey]
  Engine 6 — DaVINCI:         Treasury sniping via recon data                [Joey]
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
# Load .env.pulse: try repo-relative path first, then hardcoded VPS path, then cwd
_env_candidates = [
    os.path.join(os.path.dirname(__file__), "..", "..", ".env.pulse"),
    "/opt/joystick/.env.pulse",
]
for _env_path in _env_candidates:
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        break
load_dotenv()  # also check cwd for overrides

from .core.config import (
    JOEY_WALLET, AFFECTION, WPLS, GIBS_LAU, PULSEX_V1_ROUTER, TGSV8PLUS, JOYSTICK_HUB,
    CYCLE_DELAY, CYCLE_TIMEOUT, PROFIT_SPLIT, PLS_GAS_FLOOR, MAX_SLIPPAGE, AdaptiveDelay,
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
from .oracle.supply_oracle import SupplyOracle

from .core.log_names import get_logger, fmt_pls as fmt_pls_comma, fmt_int, fmt_pls_short
from .core.probe_controller import ProbeController
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
        self.gas_oracle    = GasOracle()
        self.supply_oracle = SupplyOracle()
        self.delay         = AdaptiveDelay()

        # Multi-wallet manager (gracefully degrades to single-wallet)
        self.wallet_mgr = WalletManager()
        self.multi_wallet = self.wallet_mgr.is_multi_wallet and not force_single_wallet
        if force_single_wallet and self.wallet_mgr.is_multi_wallet:
            log.info("--single-wallet: forcing single-wallet mode")

        # ProbeController singleton — shared state for adaptive E2 sell sizing.
        # Persists across restarts via scripts/Joystick/data/probe_state.json.
        self.probe_controller = ProbeController()
        log.info(
            "ProbeController loaded: mode=%s, sweet_spot_pct=%s",
            self.probe_controller.state.mode.value,
            self.probe_controller.state.sweet_spot_pct,
        )

        # Engine priority is determined by Strategist scoring each cycle.
        # ENGINE_EXCLUDE: comma-separated engine names to skip (e.g. "Beat,LAU")
        exclude = set(
            n.strip() for n in os.getenv("ENGINE_EXCLUDE", "").split(",") if n.strip()
        )
        all_engines = [
            ArbEngine(),
            DSSEngine(probe_controller=self.probe_controller),
            BeatEngine(with_cheon=True),
            TokenFactoryEngine(),
            LAUEngine(),
            TreasurySniperEngine(),
            SpineRunnerEngine(),
            PhreakEngine(),
        ]
        self.engines = [e for e in all_engines if e.name not in exclude]
        if exclude:
            log.info("ENGINE_EXCLUDE: disabled %s", ", ".join(sorted(exclude)))

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

    def _warmup_approvals(self) -> None:
        """Pre-approve common token→router pairs on TGSv8 to prevent transferFrom reverts."""
        from .core.config import TGSV8, PULSEX_V1_ROUTER, PULSEX_V2_ROUTER
        if not TGSV8 or self.dry_run:
            return
        try:
            from .core.chain import tgsv8_contract, safe, erc20
            tgsv8 = tgsv8_contract(w3=w3_submit)
            routers = [PULSEX_V1_ROUTER, PULSEX_V2_ROUTER]
            # Check WPLS allowance to each router — if zero, approve
            for router in routers:
                wpls_allowance = safe(
                    erc20(WPLS),
                    "allowance",
                    TGSV8,
                    router,
                ) or 0
                if wpls_allowance == 0:
                    log.info("Warming up: TGSv8 approveMax(WPLS, %s)", router[:10])
                    send_tx(
                        tgsv8.functions.approveMax(WPLS, router),
                        f"Warmup: WPLS → {router[:10]}",
                    )
        except Exception as exc:
            log.warning("Approval warmup failed (non-fatal): %s", exc)

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

        # Startup: pre-approve common token→router pairs on TGSv8
        self._warmup_approvals()

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
                outcome = await asyncio.wait_for(
                    self._async_run_cycle(),
                    timeout=CYCLE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                log.error("Cycle %d TIMED OUT after %ds — skipping", self.cycle, CYCLE_TIMEOUT)
                _events.log("bot.cycle_timeout", success=False,
                            data={"cycle": self.cycle, "timeout_s": CYCLE_TIMEOUT})
                outcome = "failure"
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

        # Contract balance tracking
        _track_addr = JOYSTICK_HUB or TGSV8PLUS
        if _track_addr:
            from .core.chain import erc20, safe, multicall
            aff_c = erc20(AFFECTION)
            gibs_c = erc20(GIBS_LAU)
            wpls_c = erc20(WPLS)
            contract_bals = multicall([
                (aff_c, "balanceOf", [_track_addr]),
                (gibs_c, "balanceOf", [_track_addr]),
                (wpls_c, "balanceOf", [_track_addr]),
            ])
            snap["aff_hub"] = contract_bals[0] or 0
            snap["gibs_hub"] = contract_bals[1] or 0
            snap["wpls_hub"] = contract_bals[2] or 0
            _label = "Hub" if JOYSTICK_HUB else "TGSv8+"
            log.info("  %s: AFF=%.1f  GIBS=%.1f  WPLS=%.1f",
                     _label,
                     snap["aff_hub"] / 1e18,
                     snap["gibs_hub"] / 1e18,
                     snap["wpls_hub"] / 1e18)
            # Keep legacy keys for dashboard compat
            snap["aff_plus"] = snap["aff_hub"]
            snap["gibs_plus"] = snap["gibs_hub"]
            snap["wpls_plus"] = snap["wpls_hub"]

        _events.log_balance_snapshot(snap)

        # 0b. Gas oracle update (rolling window)
        gas_price = self.gas_oracle.update()
        gas_status = self.gas_oracle.status()
        log.info(
            "⛽ Gas: %s Beats (avg=%s, trend=%s, ceil=%s)",
            fmt_int(gas_status["current_beats"]), fmt_int(gas_status["average_beats"]),
            gas_status["trend"], fmt_int(gas_status["ceiling_beats"]),
        )

        # 0c. Supply oracle update (inflation detection)
        self.supply_oracle.update()
        supply_status = self.supply_oracle.status()
        if supply_status["inflated"] > 0:
            log.info("📈 Supply inflation detected: %d tokens", supply_status["inflated"])

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

        # 1b. Multi-wallet floor check — Minter/Seller have no auto-refill path
        if self.multi_wallet and not self.gas_guard.check_multi(self.wallet_mgr):
            _events.log("bot.gas_guard.multi_low", success=False)
            log.warning("Minter/Seller below floor — engines on those wallets will skip this cycle")

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

            # Measure realized value via PLS + WPLS balance delta.
            # E2 sends native PLS as msg.value but sell output returns WPLS (ERC20),
            # so checking only native PLS would falsely report LP-building as a loss.
            from .core.chain import erc20, safe
            pls_before = pls_balance()
            wpls_before = safe(erc20(WPLS), "balanceOf", JOEY_WALLET) or 0

            result = engine.execute(dry_run=self.dry_run)
            _events.log_engine_result(engine.name, result, cycle_num=self.cycle)

            # Record into strategist P&L
            self.strategist.record(engine.name, result, wallet_role=rec.wallet_role)

            if result.success:
                engine.record_success()

                pls_after = pls_balance()
                wpls_after = safe(erc20(WPLS), "balanceOf", JOEY_WALLET) or 0
                realized_delta = (pls_after + wpls_after) - (pls_before + wpls_before)

                # E2 deposits PLS into LP (creates LP tokens not tracked here),
                # so realized_delta will appear negative even on profitable cycles.
                # Use engine-reported profit for LP-building engines.
                lp_engine = engine.name in ("DSS",)  # engines that deposit into LP
                effective_delta = result.net_pls * 1e18 if lp_engine else realized_delta

                log.info("✓ %s [%s]: reported=%.4f PLS  realized=%.4f PLS  TXs=%d  notes=%s",
                         engine.display_name, rec.wallet_role,
                         result.net_pls, realized_delta / 1e18,
                         len(result.tx_hashes), result.notes)
                if lp_engine and realized_delta < 0:
                    log.info("  (LP deposit: %.1f PLS in LP tokens, not counted in realized)",
                             abs(realized_delta / 1e18) + result.net_pls)

                if effective_delta > 0 and not self.dry_run and not self.multi_wallet:
                    # Only auto-compound in single-wallet mode
                    self.compound(int(effective_delta))
                    cycle_outcome = "profit"
                elif effective_delta > 0:
                    cycle_outcome = "profit"
                elif effective_delta < -100 * 10**18:
                    # Lost more than 100 PLS — treat as failure for adaptive delay
                    cycle_outcome = "failure"
                    log.warning("  Loss detected: %.1f PLS (gas > revenue)", effective_delta / 1e18)
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
            # Quote expected output for slippage protection
            from .oracle.price import get_amounts_out
            amounts = get_amounts_out(compound_wei, [WPLS, AFFECTION])
            expected_out = amounts[-1] if amounts else 0
            min_out = int(expected_out * (1.0 - MAX_SLIPPAGE)) if expected_out else 1
            send_tx(
                router.functions.swapExactETHForTokens(
                    min_out, [WPLS, AFFECTION], JOEY_WALLET, deadline
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


def _ladder_up(max_batches: int = 40, dry_run: bool = False) -> None:
    """
    Balanced GIBS uptrend via atomic mintLPAndSellPair.

    Each cycle: 1 TX via Hub — prime → purchase → LP → sell.
    Gas: ~300 PLS (vs ~3,000 PLS in old multi-TX pipeline).
    Arb bots do the heavy lifting — our sell creates price impact,
    they arb it back, we LP at the corrected price next cycle.

    P&L tracked per cycle: sell_revenue - mint_cost = net PLS.
    """
    import time
    from web3 import Web3
    from .core.config import (
        GIBS_LAU, AFFECTION, WPLS, JOYSTICK_HUB, JOEY_WALLET,
        PULSEX_V1_ROUTER, GIBS_WPLS_V2_PAIR,
    )
    from .core.chain import (
        safe, erc20, joystick_hub, router_contract,
        w3_submit, w3_read,
    )
    from .core.executor import send_tx, approve_if_needed
    from .core.probe_controller import ProbeController, ArbResponseKind
    from .oracle.price import get_amounts_out_v2
    from .engines.dss import DSSEngine

    cs = Web3.to_checksum_address
    GIBS_AFF_V2 = "0x1E2fAeF811b8eA8dC5E0dEEe2c3b0E355A7d7EA0"
    PLS_FLOOR = 200_000
    MAX_UINT = 2**256 - 1

    LP_BPS = 7000          # 70% to LP, 30% to sell
    AFF_PLS_EST = 38.0     # fallback AFF/PLS price estimate

    pair_abi = [
        {"constant": True, "inputs": [], "name": "getReserves",
         "outputs": [{"name": "", "type": "uint112"}, {"name": "", "type": "uint112"},
                     {"name": "", "type": "uint32"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "token0",
         "outputs": [{"name": "", "type": "address"}], "type": "function"},
    ]

    gibs_cs = cs(GIBS_LAU)
    aff_cs = cs(AFFECTION)
    wpls_cs = cs(WPLS)

    probe = ProbeController()
    e2 = DSSEngine(probe_controller=probe)
    hub = joystick_hub(w3=w3_submit)

    def _gibs_prices():
        """Return (wpls_price, aff_price) in PLS."""
        pc1 = w3_read.eth.contract(address=cs(GIBS_WPLS_V2_PAIR), abi=pair_abi)
        r1 = pc1.functions.getReserves().call()
        t0 = pc1.functions.token0().call()
        p_wpls = r1[1] / r1[0] if t0.lower() == GIBS_LAU.lower() else r1[0] / r1[1]

        pc2 = w3_read.eth.contract(address=cs(GIBS_AFF_V2), abi=pair_abi)
        r2 = pc2.functions.getReserves().call()
        t0b = pc2.functions.token0().call()
        aff_ratio = r2[0] / r2[1] if t0b.lower() == AFFECTION.lower() else r2[1] / r2[0]
        aff_pls = get_amounts_out_v2(10**18, [aff_cs, wpls_cs])
        aff_price_pls = aff_pls[-1] / 1e18 if aff_pls else AFF_PLS_EST
        return p_wpls, aff_ratio * aff_price_pls

    # Check if mintLPAndSellPair is available
    has_atomic = e2._has_mint_lp_sell_pair(hub)
    if not has_atomic:
        print("  mintLPAndSellPair NOT registered on Hub — deploy HarvestV3 first.")
        print("  Run: python3 scripts/deploy_harvest_v3.py")
        return

    # Ensure Hub has enough AFF for cycles
    aff_hub = (safe(erc20(AFFECTION), "balanceOf", cs(JOYSTICK_HUB)) or 0) / 1e18
    print(f"  Hub AFF balance: {aff_hub:.0f}")
    if aff_hub < 20:
        print(f"  Hub needs AFF. Deposit AFF to Hub before running --pump.")
        return

    start_wpls, start_aff = _gibs_prices()
    cumulative_pls = 0.0
    arb_count = 0
    cycle_count = 0
    consecutive_fails = 0

    for batch in range(1, max_batches + 1):
        p_wpls, p_aff = _gibs_prices()
        joey_pls = w3_read.eth.get_balance(cs(JOEY_WALLET)) / 1e18

        # Size the cycle: small batches that grow the pool steadily.
        # Cap by Hub AFF (1 AFF per GIBS) and a per-cycle ceiling.
        hub_aff = (safe(erc20(AFFECTION), "balanceOf", cs(JOYSTICK_HUB)) or 0) / 1e18
        CYCLE_CAP = 17  # match E2 harvest size — small, frequent cycles
        if hub_aff < CYCLE_CAP:
            print(f"  Hub AFF depleted ({hub_aff:.0f} < {CYCLE_CAP}). Stopping.")
            break
        mint_count = min(CYCLE_CAP, int(hub_aff))

        sell_pct = (10000 - LP_BPS) / 10000

        # Estimate mint cost (1 AFF per GIBS)
        aff_pls_quote = get_amounts_out_v2(10**18, [aff_cs, wpls_cs])
        aff_price = aff_pls_quote[-1] / 1e18 if aff_pls_quote else AFF_PLS_EST
        mint_cost_pls = mint_count * aff_price

        # Estimate sell revenue — route through LP partner (GIBS→AFF→WPLS)
        sell_gibs = int(mint_count * sell_pct)
        sell_gibs_wei = sell_gibs * 10**18
        sell_path = [gibs_cs, aff_cs, wpls_cs]
        sell_dex = 1  # V2
        try:
            amounts = get_amounts_out_v2(sell_gibs_wei, sell_path)
            expected_sell = amounts[-1] if amounts else 0
        except Exception:
            expected_sell = 0
        est_sell_pls = expected_sell / 1e18 if expected_sell else 0

        print(f"\n{'━'*60}")
        print(f"  Cycle {batch}/{max_batches}  [ATOMIC — mintLPAndSellPair]")
        print(f"  GIBS: WPLS={p_wpls:.2f}  AFF={p_aff:.2f}  "
              f"D: WPLS {p_wpls-start_wpls:+.2f}  AFF {p_aff-start_aff:+.2f}")
        print(f"  PLS: {joey_pls:,.0f}  Arbs: {arb_count}  Cycles: {cycle_count}  "
              f"Cumulative: {cumulative_pls:+,.0f} PLS")
        print(f"  Mint: {mint_count} GIBS (cost ~{mint_cost_pls:.0f} PLS)  "
              f"Sell: {sell_gibs} GIBS (~{est_sell_pls:.0f} PLS)  "
              f"LP: {mint_count - sell_gibs} GIBS")
        print(f"{'━'*60}")

        if joey_pls < PLS_FLOOR:
            print(f"  PLS floor hit"); break
        if dry_run:
            print(f"  [dry-run]"); continue

        # ── Check arb from previous sell ──
        arb_resp = probe.check_arb_response()
        if arb_resp.kind is ArbResponseKind.ARB_DETECTED:
            arb_count += 1
            print(f"  ARB! {arb_resp.gibs_size_wei/1e18:.1f} GIBS by {arb_resp.sender[:10]}")
            probe.clear_lp_add_target()
        elif arb_resp.kind is ArbResponseKind.PENDING:
            print(f"  Arb pending — waiting 12s")
            time.sleep(12)
            arb_resp = probe.check_arb_response()
            if arb_resp.kind is ArbResponseKind.ARB_DETECTED:
                arb_count += 1
                print(f"  ARB (delayed)! {arb_resp.gibs_size_wei/1e18:.1f} GIBS")
                probe.clear_lp_add_target()

        # ── Execute atomic cycle ──
        min_sell_out = int(expected_sell * 85 / 100) if expected_sell else 0

        # Reset nonce from chain before each cycle to avoid stale-nonce crashes
        from .core.wallet import reset_nonce
        reset_nonce()

        try:
            result = e2._execute_harvest_pair(
                lau=GIBS_LAU,
                payment_token=AFFECTION,
                lp_partner=AFFECTION,
                prime_count=mint_count,
                purchase_amt=mint_count,
                lp_bps=LP_BPS,
                sell_path=sell_path,
                sell_dex=sell_dex,
                min_sell_out=min_sell_out,
                dry_run=dry_run,
                sell_pair_address=GIBS_AFF_V2,
            )
        except Exception as exc:
            print(f"  TX ERROR: {exc}")
            reset_nonce()
            consecutive_fails += 1
            if consecutive_fails >= 3:
                print(f"  3 consecutive failures. Stopping.")
                break
            time.sleep(15)
            continue

        if result.success:
            consecutive_fails = 0
            cycle_count += 1
            gas_pls = result.gas_wei / 1e18 if result.gas_wei else 0
            net_pls = est_sell_pls - mint_cost_pls - gas_pls
            cumulative_pls += net_pls
            print(f"  P&L: sell~{est_sell_pls:.0f} - mint~{mint_cost_pls:.0f} "
                  f"- gas~{gas_pls:.0f} = {net_pls:+.0f} PLS  "
                  f"(cumulative: {cumulative_pls:+,.0f})")
        else:
            print(f"  FAILED: {result.notes}")
            if "insufficient" in result.notes.lower():
                print(f"  Hub may need more AFF. Stopping.")
                break

        if batch < max_batches:
            time.sleep(20)

    # Summary
    final_wpls, final_aff = _gibs_prices()
    joey_final = w3_read.eth.get_balance(cs(JOEY_WALLET)) / 1e18
    print(f"\n{'━'*60}")
    print(f"  PUMP COMPLETE  ({cycle_count}/{max_batches} cycles)")
    print(f"  GIBS/WPLS: {start_wpls:.2f} -> {final_wpls:.2f} ({final_wpls-start_wpls:+.2f})")
    print(f"  GIBS/AFF:  {start_aff:.2f} -> {final_aff:.2f} ({final_aff-start_aff:+.2f})")
    print(f"  Arb detections: {arb_count}  Cycles: {cycle_count}")
    print(f"  Cumulative P&L: {cumulative_pls:+,.0f} PLS")
    print(f"  Joey PLS: {joey_final:,.0f}")
    print(f"{'━'*60}")


def _buy_and_lp(pls_per_batch: int = 10_000, max_batches: int = 20,
                 dry_run: bool = False) -> None:
    """
    Buy GIBS from cheapest pair (upward pressure) + LP at new price (floor lock).
    Each cycle: PLS → buy GIBS → LP with matching AFF → price ratchets up.
    """
    import time
    from web3 import Web3
    from .core.config import (
        GIBS_LAU, AFFECTION, WPLS, JOEY_WALLET,
        PULSEX_V1_ROUTER, PULSEX_V2_ROUTER, GIBS_WPLS_V2_PAIR,
    )
    from .core.chain import (
        safe, erc20, tgsv8_contract, router_contract,
        w3_submit, w3_read, pair_contract,
    )
    from .core.executor import send_tx, approve_if_needed
    from .core.probe_controller import ProbeController, ArbResponseKind

    cs = Web3.to_checksum_address
    GIBS_AFF_V2 = "0x1E2fAeF811b8eA8dC5E0dEEe2c3b0E355A7d7EA0"
    PLS_FLOOR = 200_000
    MAX_UINT = 2**256 - 1

    probe = ProbeController()
    tgs = tgsv8_contract(w3=w3_submit)
    tgs_addr = tgs.address
    gibs_cs = cs(GIBS_LAU)
    aff_cs = cs(AFFECTION)
    wpls_cs = cs(WPLS)

    pair_abi = [
        {"constant": True, "inputs": [], "name": "getReserves",
         "outputs": [{"name": "", "type": "uint112"}, {"name": "", "type": "uint112"},
                     {"name": "", "type": "uint32"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "token0",
         "outputs": [{"name": "", "type": "address"}], "type": "function"},
    ]

    def _gibs_price_on(pair_addr, other_token):
        """Return GIBS price in PLS for a given pair."""
        from .oracle.price import get_amounts_out_v2
        pc = w3_read.eth.contract(address=cs(pair_addr), abi=pair_abi)
        r = pc.functions.getReserves().call()
        t0 = pc.functions.token0().call()
        if t0.lower() == GIBS_LAU.lower():
            gibs_r, other_r = r[0], r[1]
        else:
            gibs_r, other_r = r[1], r[0]
        ratio = other_r / gibs_r  # other per GIBS
        if other_token == WPLS:
            return ratio, gibs_r
        # Convert to PLS
        pls_out = get_amounts_out_v2(10**18, [cs(other_token), wpls_cs])
        if pls_out and pls_out[-1] > 0:
            return ratio * (pls_out[-1] / 1e18), gibs_r
        return 0, gibs_r

    # One-time approvals
    approve_if_needed(
        w3_submit.eth.contract(address=wpls_cs, abi=erc20(WPLS).abi),
        cs(PULSEX_V1_ROUTER), MAX_UINT, "WPLS→V1Router")
    approve_if_needed(
        w3_submit.eth.contract(address=gibs_cs, abi=erc20(GIBS_LAU).abi),
        tgs_addr, MAX_UINT, "GIBS→TGSv8")
    approve_if_needed(
        w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi),
        tgs_addr, MAX_UINT, "AFF→TGSv8")

    start_price_wpls, _ = _gibs_price_on(GIBS_WPLS_V2_PAIR, WPLS)
    start_price_aff, _ = _gibs_price_on(GIBS_AFF_V2, AFFECTION)

    for batch in range(1, max_batches + 1):
        price_wpls, gibs_r_wpls = _gibs_price_on(GIBS_WPLS_V2_PAIR, WPLS)
        price_aff, gibs_r_aff = _gibs_price_on(GIBS_AFF_V2, AFFECTION)
        joey_pls = w3_read.eth.get_balance(cs(JOEY_WALLET)) / 1e18

        # Find cheapest pair
        cheapest = "AFF" if price_aff < price_wpls else "WPLS"
        cheap_price = min(price_aff, price_wpls)

        print(f"\n{'━'*60}")
        print(f"  Batch {batch}/{max_batches}  |  GIBS prices: WPLS={price_wpls:.2f}  AFF={price_aff:.2f}")
        print(f"  Cheapest: {cheapest} pair  |  Joey PLS: {joey_pls:,.0f}")
        delta_wpls = price_wpls - start_price_wpls
        delta_aff = price_aff - start_price_aff
        print(f"  Δ since start: WPLS {delta_wpls:+.2f}  AFF {delta_aff:+.2f}")
        print(f"{'━'*60}")

        if joey_pls < PLS_FLOOR:
            print(f"  PLS floor hit"); break

        if dry_run:
            print(f"  [dry-run] would buy ~{pls_per_batch/cheap_price:.0f} GIBS"); continue

        # ── Check arb response from previous buy ──
        arb_resp = probe.check_arb_response()
        if arb_resp.kind is ArbResponseKind.ARB_DETECTED:
            print(f"  ★ ARB: {arb_resp.gibs_size_wei/1e18:.1f} GIBS by {arb_resp.sender[:10]}")
            probe.clear_lp_add_target()  # acknowledged
        elif arb_resp.kind is ArbResponseKind.PENDING:
            print(f"  ⏳ Arb pending — waiting...")
            time.sleep(12)
            arb_resp = probe.check_arb_response()
            if arb_resp.kind is ArbResponseKind.ARB_DETECTED:
                print(f"  ★ ARB: {arb_resp.gibs_size_wei/1e18:.1f} GIBS detected after wait")
                probe.clear_lp_add_target()

        # ── Step 1: Buy GIBS from cheapest pair ──
        # Split: 60% to buy GIBS (upward pressure), 40% to buy AFF (for LP pairing)
        buy_pls = int(pls_per_batch * 60 / 100)
        lp_pls = pls_per_batch - buy_pls

        # Wrap all PLS
        WPLS_ABI = [{"constant": False, "inputs": [], "name": "deposit",
                     "outputs": [], "payable": True, "type": "function"}]
        wpls_c = w3_submit.eth.contract(address=wpls_cs, abi=WPLS_ABI)

        print(f"  1. Wrap {pls_per_batch:,} PLS")
        r = send_tx(wpls_c.functions.deposit(),
                    f"wrap {pls_per_batch} PLS",
                    value=pls_per_batch * 10**18,
                    skip_simulate=True, fixed_gas=50_000)
        if not r:
            print("     FAILED"); break

        # Buy GIBS: WPLS → AFF → GIBS (cheapest route, multi-hop via V2 router)
        v2_router_addr = cs(PULSEX_V2_ROUTER)
        approve_if_needed(
            w3_submit.eth.contract(address=wpls_cs, abi=erc20(WPLS).abi),
            v2_router_addr, MAX_UINT, "WPLS→V2Router")

        ROUTER_SWAP_ABI = [{"inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}],
            "name": "swapExactTokensForTokens",
            "outputs": [{"name": "", "type": "uint256[]"}],
            "type": "function"}]
        v2_router = w3_submit.eth.contract(address=v2_router_addr, abi=ROUTER_SWAP_ABI)

        buy_amount = buy_pls * 10**18
        est_gibs = int(buy_pls / cheap_price * 0.9)  # 10% slippage buffer
        print(f"  2. BUY ~{buy_pls/cheap_price:.0f} GIBS (WPLS→AFF→GIBS, {buy_pls:,} PLS)")
        r = send_tx(
            v2_router.functions.swapExactTokensForTokens(
                buy_amount, est_gibs * 10**18,
                [wpls_cs, aff_cs, gibs_cs],
                JOEY_WALLET, int(time.time()) + 300),
            f"buy GIBS ({buy_pls} PLS)",
            skip_simulate=True, fixed_gas=350_000, gas_tier="fast")
        if not r:
            print("     BUY FAILED"); break
        print(f"     TX: 0x{r['transactionHash'].hex()}")

        # Record the buy with probe (on AFF pair — we bought GIBS FROM it)
        try:
            probe.record_sell(  # "sell" from the pair's perspective = our buy
                sell_gibs_wei=est_gibs * 10**18,
                block_number=r["blockNumber"],
                tx_hash=r["transactionHash"].hex(),
                pair_address=GIBS_AFF_V2,
                gibs_is_token0=False,  # token0=AFF, token1=GIBS
            )
        except Exception as exc:
            print(f"     probe: {exc}")

        # ── Step 2: Buy AFF for LP pairing ──
        lp_amount = lp_pls * 10**18
        print(f"  3. Buy AFF for LP ({lp_pls:,} PLS)")
        v1_router = router_contract(w3=w3_submit)
        r = send_tx(
            v1_router.functions.swapExactTokensForTokens(
                lp_amount, 0, [wpls_cs, aff_cs],
                JOEY_WALLET, int(time.time()) + 300),
            f"buy AFF ({lp_pls} PLS)",
            skip_simulate=True, fixed_gas=300_000)
        if not r:
            print("     FAILED"); break

        # ── Step 3: LP bought GIBS + AFF at new higher price ──
        gibs_bal = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
        aff_bal = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0

        # Read current ratio from pair
        pc = w3_read.eth.contract(address=cs(GIBS_AFF_V2), abi=pair_abi)
        res = pc.functions.getReserves().call()
        t0 = pc.functions.token0().call()
        if t0.lower() == AFFECTION.lower():
            ratio = res[0] / res[1]  # AFF/GIBS
        else:
            ratio = res[1] / res[0]

        lp_gibs = gibs_bal
        lp_aff = int(lp_gibs * ratio)
        if lp_aff > aff_bal:
            lp_aff = aff_bal
            lp_gibs = int(lp_aff / ratio)

        if lp_gibs > 10**18 and lp_aff > 10**18:
            print(f"  4. LP {lp_gibs/1e18:.0f} GIBS + {lp_aff/1e18:.0f} AFF (floor lock)")
            send_tx(tgs.functions.deposit(gibs_cs, lp_gibs),
                    "deposit GIBS", skip_simulate=True, fixed_gas=200_000, gas_tier="fast")
            send_tx(tgs.functions.deposit(aff_cs, lp_aff),
                    "deposit AFF", skip_simulate=True, fixed_gas=200_000, gas_tier="fast")

            r = send_tx(tgs.functions.addLiquidity(
                            gibs_cs, aff_cs, lp_gibs, lp_aff,
                            1500, cs(JOEY_WALLET), 1),
                        f"addLiquidity({lp_gibs//10**18} GIBS + {lp_aff//10**18} AFF)",
                        skip_simulate=True, fixed_gas=500_000)
            if r:
                print(f"     LP TX: 0x{r['transactionHash'].hex()}")
            else:
                print("     LP FAILED (non-fatal)")

        # Post-batch prices
        new_wpls, _ = _gibs_price_on(GIBS_WPLS_V2_PAIR, WPLS)
        new_aff, _ = _gibs_price_on(GIBS_AFF_V2, AFFECTION)
        print(f"  ✓ Prices: WPLS={new_wpls:.2f} ({new_wpls-price_wpls:+.2f})  "
              f"AFF={new_aff:.2f} ({new_aff-price_aff:+.2f})")

        if batch < max_batches:
            print(f"  Waiting 15s for arb bots...")
            time.sleep(15)

    # Final summary
    final_wpls, _ = _gibs_price_on(GIBS_WPLS_V2_PAIR, WPLS)
    final_aff, _ = _gibs_price_on(GIBS_AFF_V2, AFFECTION)
    joey_pls_final = w3_read.eth.get_balance(cs(JOEY_WALLET)) / 1e18

    print(f"\n{'━'*60}")
    print(f"  BUY & LP COMPLETE")
    print(f"  GIBS/WPLS: {start_price_wpls:.2f} → {final_wpls:.2f} PLS ({final_wpls-start_price_wpls:+.2f})")
    print(f"  GIBS/AFF:  {start_price_aff:.2f} → {final_aff:.2f} PLS ({final_aff-start_price_aff:+.2f})")
    print(f"  Joey PLS:  {joey_pls_final:,.0f}")
    print(f"{'━'*60}")


def _grow_gibs_aff(target_pool: str = "GIBS_AFF", batch_gibs: int = 500,
                    max_batches: int = 15, dry_run: bool = False) -> None:
    """
    Grow GIBS/AFF LP pool by repeatedly buying AFF, minting GIBS, and adding LP.
    Runs until GIBS/AFF GIBS reserve exceeds GIBS/WPLS, or max_batches reached.
    """
    import time
    from web3 import Web3
    from .core.config import (
        GIBS_LAU, AFFECTION, WPLS, JOYSTICK_HUB, JOEY_WALLET,
        PULSEX_V1_ROUTER, PULSEX_V2_ROUTER, GIBS_WPLS_V2_PAIR,
    )
    from .core.chain import (
        safe, erc20, joystick_hub, tgsv8_contract,
        w3_submit, w3_read, pair_contract, router_contract,
    )
    from .core.executor import send_tx, approve_if_needed

    from .core.probe_controller import ProbeController, ArbResponseKind

    cs = Web3.to_checksum_address
    GIBS_AFF_V2 = "0x1E2fAeF811b8eA8dC5E0dEEe2c3b0E355A7d7EA0"
    PLS_FLOOR = 200_000  # stop if Joey PLS drops below this
    # GIBS/AFF: token0=AFF, token1=GIBS → gibs_is_token0=False
    GIBS_IS_TOKEN0_AFF_PAIR = False

    probe = ProbeController()

    pair_abi = [
        {"constant": True, "inputs": [], "name": "getReserves",
         "outputs": [{"name": "", "type": "uint112"}, {"name": "", "type": "uint112"},
                     {"name": "", "type": "uint32"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "token0",
         "outputs": [{"name": "", "type": "address"}], "type": "function"},
    ]

    def _read_gibs_reserve(pair_addr):
        pc = w3_read.eth.contract(address=cs(pair_addr), abi=pair_abi)
        r = pc.functions.getReserves().call()
        t0 = pc.functions.token0().call()
        if t0.lower() == GIBS_LAU.lower():
            return r[0] / 1e18, r[1] / 1e18  # gibs, other
        return r[1] / 1e18, r[0] / 1e18

    def _read_aff_ratio():
        """AFF per GIBS in GIBS/AFF pool"""
        pc = w3_read.eth.contract(address=cs(GIBS_AFF_V2), abi=pair_abi)
        r = pc.functions.getReserves().call()
        t0 = pc.functions.token0().call()
        if t0.lower() == AFFECTION.lower():
            return r[0] / r[1]  # AFF / GIBS in wei
        return r[1] / r[0]

    hub = joystick_hub(w3=w3_submit)
    tgs = tgsv8_contract(w3=w3_submit)
    gibs_cs = cs(GIBS_LAU)
    aff_cs = cs(AFFECTION)
    wpls_cs = cs(WPLS)
    tgs_addr = tgs.address
    MAX_UINT = 2**256 - 1

    # One-time approvals
    approve_if_needed(
        w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi),
        gibs_cs, MAX_UINT, "AFF→GIBS_LAU")
    approve_if_needed(
        w3_submit.eth.contract(address=gibs_cs, abi=erc20(GIBS_LAU).abi),
        tgs_addr, MAX_UINT, "GIBS→TGSv8")
    approve_if_needed(
        w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi),
        tgs_addr, MAX_UINT, "AFF→TGSv8")

    PURCHASE_ABI = [{"inputs": [{"name": "_t", "type": "address"},
                     {"name": "_a", "type": "uint256"}],
                     "name": "Purchase", "outputs": [], "type": "function"}]
    gibs_contract = w3_submit.eth.contract(address=gibs_cs, abi=PURCHASE_ABI)

    for batch in range(1, max_batches + 1):
        # ── Status check ──
        gibs_aff_r, _ = _read_gibs_reserve(GIBS_AFF_V2)
        gibs_wpls_r, _ = _read_gibs_reserve(GIBS_WPLS_V2_PAIR)
        joey_pls = w3_read.eth.get_balance(cs(JOEY_WALLET)) / 1e18
        ratio = _read_aff_ratio()

        print(f"\n{'━'*60}")
        print(f"  Batch {batch}/{max_batches}")
        print(f"  GIBS/AFF:  {gibs_aff_r:,.0f} GIBS   GIBS/WPLS: {gibs_wpls_r:,.0f} GIBS")
        print(f"  Gap: {gibs_wpls_r - gibs_aff_r:,.0f}   Joey PLS: {joey_pls:,.0f}")
        print(f"{'━'*60}")

        if gibs_aff_r >= gibs_wpls_r:
            print(f"  TARGET REACHED! GIBS/AFF ({gibs_aff_r:,.0f}) ≥ GIBS/WPLS ({gibs_wpls_r:,.0f})")
            break

        if joey_pls < PLS_FLOOR:
            print(f"  PLS floor hit ({joey_pls:,.0f} < {PLS_FLOOR:,})")
            break

        # ── Check arb response from previous sell → LP ratchet ──
        arb_resp = probe.check_arb_response()
        if arb_resp.kind is ArbResponseKind.ARB_DETECTED:
            print(f"  ★ ARB DETECTED! {arb_resp.gibs_size_wei/1e18:.1f} GIBS bought by {arb_resp.sender[:10]}...")
            lp_target = probe.lp_add_target()
            if lp_target:
                print(f"    → LP ratchet: adding {lp_target/1e18:.0f} GIBS at new price")
                from .engines.dss import DSSEngine
                e2 = DSSEngine(probe_controller=probe)
                lp_result = e2._execute_lp_add_via_tgsv8(
                    lp_target, GIBS_AFF_V2, dry_run=dry_run)
                if lp_result.success:
                    probe.clear_lp_add_target()
                    print(f"    → LP ratchet OK: {lp_result.notes}")
                else:
                    probe.record_lp_add_failure()
                    print(f"    → LP ratchet failed: {lp_result.notes}")
        elif arb_resp.kind is ArbResponseKind.PENDING:
            print(f"  ⏳ Arb pending (waiting for response window)")
        elif arb_resp.kind is ArbResponseKind.NO_RESPONSE and batch > 1:
            print(f"  — No arb response from previous sell")

        if dry_run:
            print(f"  [dry-run] would add {batch_gibs} GIBS")
            continue

        # ── Step 1: Buy AFF from DEX ──
        aff_for_mint = batch_gibs
        aff_for_lp = int(batch_gibs * ratio)  # ratio is unitless (AFF/GIBS)
        total_aff = aff_for_mint + aff_for_lp
        total_aff_wei = total_aff * 10**18

        # Wrap PLS → WPLS
        WPLS_ABI = [{"constant": False, "inputs": [], "name": "deposit",
                     "outputs": [], "payable": True, "type": "function"}]
        wpls_c = w3_submit.eth.contract(address=wpls_cs, abi=WPLS_ABI)

        # Get quote for AFF buy
        from .oracle.price import get_amounts_out
        est_pls = int(total_aff * 42)  # ~42 PLS/AFF estimate with buffer
        quote = get_amounts_out(est_pls * 10**18, [wpls_cs, aff_cs])
        if not quote or quote[-1] < total_aff_wei:
            est_pls = int(est_pls * 1.2)  # bump estimate

        pls_cost = est_pls * 10**18
        print(f"  1. Buy ~{total_aff} AFF from DEX (~{est_pls:,} PLS)")

        try:
            r = send_tx(wpls_c.functions.deposit(),
                        f"wrap {est_pls} PLS", value=pls_cost, skip_simulate=True, fixed_gas=50_000)
        except Exception as exc:
            print(f"     wrap FAILED: {exc}"); break
        if not r:
            print("     wrap FAILED"); break

        # Approve WPLS → V1 Router
        approve_if_needed(
            w3_submit.eth.contract(address=wpls_cs, abi=erc20(WPLS).abi),
            cs(PULSEX_V1_ROUTER), MAX_UINT, "WPLS→Router")

        v1_router = router_contract(w3=w3_submit)
        min_aff = int(total_aff_wei * 90 / 100)
        r = send_tx(
            v1_router.functions.swapExactTokensForTokens(
                pls_cost, min_aff, [wpls_cs, aff_cs],
                JOEY_WALLET, int(time.time()) + 300),
            f"swap WPLS → {total_aff} AFF",
            skip_simulate=True, fixed_gas=300_000)
        if not r:
            print("     swap FAILED"); break
        print(f"     TX: 0x{r['transactionHash'].hex()}")

        # ── Step 2: Prime GIBS ──
        print(f"  2. primeGibs({batch_gibs})")
        r = send_tx(hub.functions.primeGibs(batch_gibs),
                    f"primeGibs({batch_gibs})", gas_tier="fast")
        if not r:
            print("     FAILED"); break
        print(f"     TX: 0x{r['transactionHash'].hex()}")

        # ── Step 3: Purchase GIBS ──
        print(f"  3. Purchase({batch_gibs} GIBS)")
        r = send_tx(gibs_contract.functions.Purchase(aff_cs, batch_gibs * 10**18),
                    f"Purchase({batch_gibs} GIBS)",
                    skip_simulate=True, fixed_gas=200_000)
        if not r:
            print("     FAILED"); break
        print(f"     TX: 0x{r['transactionHash'].hex()}")

        # ── Step 4: Split — 70% LP + 30% SELL into pair ──
        gibs_bal = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
        aff_bal = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0

        sell_gibs = int(gibs_bal * 30 / 100)   # 30% for displacement
        lp_gibs = gibs_bal - sell_gibs          # 70% for LP floor

        # Match LP side to pool ratio
        lp_aff = int(lp_gibs * ratio)
        if lp_aff > aff_bal:
            lp_aff = aff_bal
            lp_gibs = int(lp_aff / ratio)
            sell_gibs = gibs_bal - lp_gibs  # rest goes to sell

        # ── 4a. Sell GIBS into GIBS/AFF pair (creates displacement) ──
        # Low-level: transfer GIBS → pair, call pair.swap()
        # This pushes GIBS price down on AFF pair → arb bots buy cheap
        pair_cs = cs(GIBS_AFF_V2)

        # Read pair to determine swap output
        _pair_abi = [{"constant": True, "inputs": [], "name": "getReserves",
                      "outputs": [{"name": "", "type": "uint112"}, {"name": "", "type": "uint112"},
                                  {"name": "", "type": "uint32"}], "type": "function"},
                     {"constant": True, "inputs": [], "name": "token0",
                      "outputs": [{"name": "", "type": "address"}], "type": "function"}]
        _pc = w3_submit.eth.contract(address=pair_cs, abi=_pair_abi)
        _res = _pc.functions.getReserves().call()
        _t0 = _pc.functions.token0().call()

        if _t0.lower() == AFFECTION.lower():
            r_aff_now, r_gibs_now = _res[0], _res[1]
            gibs_is_token1 = True
        else:
            r_gibs_now, r_aff_now = _res[0], _res[1]
            gibs_is_token1 = False

        # Constant product: amountOut = (amountIn * 997 * reserveOut) / (reserveIn * 1000 + amountIn * 997)
        aff_out = (sell_gibs * 997 * r_aff_now) // (r_gibs_now * 1000 + sell_gibs * 997)

        print(f"  4a. SELL {sell_gibs/1e18:.0f} GIBS → {aff_out/1e18:.1f} AFF (displacement)")

        # Transfer GIBS to pair
        TRANSFER_ABI = [{"inputs": [{"name": "to", "type": "address"},
                         {"name": "amount", "type": "uint256"}],
                         "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
                         "type": "function"}]
        gibs_token = w3_submit.eth.contract(address=gibs_cs, abi=TRANSFER_ABI)
        r = send_tx(gibs_token.functions.transfer(pair_cs, sell_gibs),
                    f"transfer({sell_gibs//10**18} GIBS → pair)",
                    skip_simulate=True, fixed_gas=150_000, gas_tier="fast")
        if not r:
            print("     transfer FAILED"); break

        # Call pair.swap — send AFF out to Joey
        SWAP_ABI = [{"inputs": [{"name": "amount0Out", "type": "uint256"},
                     {"name": "amount1Out", "type": "uint256"},
                     {"name": "to", "type": "address"},
                     {"name": "data", "type": "bytes"}],
                     "name": "swap", "outputs": [], "type": "function"}]
        pair_swap = w3_submit.eth.contract(address=pair_cs, abi=SWAP_ABI)

        if gibs_is_token1:
            # GIBS is token1, AFF is token0 → we want AFF out (amount0Out)
            r = send_tx(pair_swap.functions.swap(aff_out, 0, JOEY_WALLET, b""),
                        f"swap({aff_out//10**18} AFF out)",
                        skip_simulate=True, fixed_gas=200_000, gas_tier="fast")
        else:
            # GIBS is token0, AFF is token1 → we want AFF out (amount1Out)
            r = send_tx(pair_swap.functions.swap(0, aff_out, JOEY_WALLET, b""),
                        f"swap({aff_out//10**18} AFF out)",
                        skip_simulate=True, fixed_gas=200_000, gas_tier="fast")
        if r:
            print(f"     SOLD! TX: 0x{r['transactionHash'].hex()}")
            # Record sell with probe for arb detection
            try:
                probe.record_sell(
                    sell_gibs_wei=sell_gibs,
                    block_number=r["blockNumber"],
                    tx_hash=r["transactionHash"].hex(),
                    pair_address=GIBS_AFF_V2,
                    gibs_is_token0=GIBS_IS_TOKEN0_AFF_PAIR,
                )
            except Exception as exc:
                print(f"     probe.record_sell: {exc}")
        else:
            print("     swap FAILED"); break

        # ── 4b. LP remaining 70% GIBS + AFF via TGSv8 ──
        # Re-read balances (sell changed AFF balance)
        gibs_bal2 = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
        aff_bal2 = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0

        # Re-read ratio (sell changed it)
        ratio = _read_aff_ratio()
        lp_gibs = gibs_bal2
        lp_aff = int(lp_gibs * ratio)
        if lp_aff > aff_bal2:
            lp_aff = aff_bal2
            lp_gibs = int(lp_aff / ratio)

        if lp_gibs > 0 and lp_aff > 0:
            print(f"  4b. LP {lp_gibs/1e18:.0f} GIBS + {lp_aff/1e18:.0f} AFF (floor)")
            send_tx(tgs.functions.deposit(gibs_cs, lp_gibs),
                    f"deposit GIBS", skip_simulate=True, fixed_gas=200_000, gas_tier="fast")
            send_tx(tgs.functions.deposit(aff_cs, lp_aff),
                    f"deposit AFF", skip_simulate=True, fixed_gas=200_000, gas_tier="fast")

            # TGSv8 may have leftover tokens from prior batches — use total balance
            tgs_gibs = safe(erc20(GIBS_LAU), "balanceOf", tgs_addr) or 0
            tgs_aff = safe(erc20(AFFECTION), "balanceOf", tgs_addr) or 0
            lp_g = min(tgs_gibs, lp_gibs)
            lp_a = min(tgs_aff, int(lp_g * ratio))

            r = send_tx(tgs.functions.addLiquidity(
                            gibs_cs, aff_cs, lp_g, lp_a,
                            1500, cs(JOEY_WALLET), 1),  # 15% slippage for post-sell ratio shift
                        f"addLiquidity({lp_g//10**18} GIBS + {lp_a//10**18} AFF)",
                        skip_simulate=True, fixed_gas=500_000)
            if r:
                print(f"     LP TX: 0x{r['transactionHash'].hex()}")
            else:
                print("     addLiquidity FAILED (non-fatal)")

        # ── Post-batch status ──
        gibs_aff_new, aff_new = _read_gibs_reserve(GIBS_AFF_V2)
        new_ratio = aff_new / gibs_aff_new if gibs_aff_new > 0 else 0
        print(f"  ✓ GIBS/AFF pool: {gibs_aff_new:,.0f} GIBS / {aff_new:,.0f} AFF (ratio {new_ratio:.4f})")

        # Brief pause between batches
        if batch < max_batches:
            print(f"  Waiting 10s...")
            time.sleep(10)

    # Final summary
    gibs_aff_final, aff_final = _read_gibs_reserve(GIBS_AFF_V2)
    gibs_wpls_final, _ = _read_gibs_reserve(GIBS_WPLS_V2_PAIR)
    joey_pls_final = w3_read.eth.get_balance(cs(JOEY_WALLET)) / 1e18

    print(f"\n{'━'*60}")
    print(f"  GROWTH COMPLETE")
    print(f"  GIBS/AFF:   {gibs_aff_final:,.0f} GIBS / {aff_final:,.0f} AFF")
    print(f"  GIBS/WPLS:  {gibs_wpls_final:,.0f} GIBS")
    winner = "GIBS/AFF 🏆" if gibs_aff_final >= gibs_wpls_final else f"GIBS/WPLS (gap: {gibs_wpls_final - gibs_aff_final:,.0f})"
    print(f"  Largest:    {winner}")
    print(f"  Joey PLS:   {joey_pls_final:,.0f}")
    print(f"{'━'*60}")


def _run_seed_lp(pair_name: str, dry_run: bool = False) -> None:
    """Seed a GIBS LP pair with liquidity from Hub reserves."""
    import time
    from web3 import Web3
    from .core.config import (
        GIBS_LAU, AFFECTION, JOYSTICK_HUB, JOEY_WALLET,
        PULSEX_V2_ROUTER, PULSEX_V2_FACTORY,
    )
    from .core.chain import safe, erc20, joystick_hub, w3_submit, w3_read, pair_contract
    from .core.executor import send_tx, approve_if_needed

    cs = Web3.to_checksum_address

    # ── Pair registry ──
    PAIRS = {
        "GIBS_AFF": {"other": AFFECTION, "other_name": "AFF"},
    }
    if pair_name not in PAIRS:
        print(f"Unknown pair: {pair_name}. Available: {', '.join(PAIRS)}")
        return

    other_token = PAIRS[pair_name]["other"]
    other_name = PAIRS[pair_name]["other_name"]

    # ── Discover or verify pair exists ──
    factory_abi = [{"constant": True, "inputs": [{"name": "", "type": "address"},
                    {"name": "", "type": "address"}], "name": "getPair",
                    "outputs": [{"name": "", "type": "address"}], "type": "function"}]
    factory = w3_read.eth.contract(address=cs(PULSEX_V2_FACTORY), abi=factory_abi)
    pair_addr = factory.functions.getPair(cs(GIBS_LAU), cs(other_token)).call()
    if pair_addr == "0x" + "0" * 40:
        print(f"GIBS/{other_name} V2 pair does not exist. Create it first.")
        return

    # ── Read current pool ratio ──
    pair_abi = [
        {"constant": True, "inputs": [], "name": "getReserves",
         "outputs": [{"name": "", "type": "uint112"}, {"name": "", "type": "uint112"},
                     {"name": "", "type": "uint32"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "token0",
         "outputs": [{"name": "", "type": "address"}], "type": "function"},
    ]
    pc = w3_read.eth.contract(address=cs(pair_addr), abi=pair_abi)
    reserves = pc.functions.getReserves().call()
    t0 = pc.functions.token0().call()
    if t0.lower() == GIBS_LAU.lower():
        gibs_r, other_r = reserves[0], reserves[1]
    else:
        gibs_r, other_r = reserves[1], reserves[0]

    if gibs_r == 0:
        print("Pool is empty — needs initial seeding with manual amounts.")
        return

    ratio = other_r / gibs_r  # other-per-GIBS in pool

    # ── Calculate seeding amounts ──
    hub_other = (safe(erc20(other_token), "balanceOf", JOYSTICK_HUB) or 0)
    hub_other_human = hub_other / 1e18

    # Use up to 50% of Hub's other-token for LP, rest stays for operations
    seed_other = int(hub_other_human * 0.5)
    seed_gibs = int(seed_other / ratio)
    prime_cost = seed_gibs  # 1 AFF per GIBS minted

    if seed_other < 10:
        print(f"Hub {other_name} balance too low ({hub_other_human:.2f}). Acquire more first.")
        return

    total_other_needed = seed_other + prime_cost
    if total_other_needed > hub_other_human:
        # Scale down to what Hub can afford
        seed_other = int(hub_other_human / (1 + ratio))
        seed_gibs = int(seed_other / ratio)
        prime_cost = seed_gibs
        total_other_needed = seed_other + prime_cost

    print(f"{'━'*60}")
    print(f"  Seed LP: GIBS/{other_name} V2")
    print(f"{'━'*60}")
    print(f"  Pair:      {pair_addr}")
    print(f"  Current:   {gibs_r/1e18:.2f} GIBS / {other_r/1e18:.2f} {other_name}")
    print(f"  Ratio:     1 GIBS = {ratio:.4f} {other_name}")
    print(f"  Seed:      {seed_gibs} GIBS + {seed_other} {other_name}")
    print(f"  Prime:     {prime_cost} {other_name} (to mint {seed_gibs} GIBS)")
    print(f"  Hub after: ~{hub_other_human - total_other_needed:.0f} {other_name}")
    print(f"{'━'*60}")

    if dry_run:
        print("  [dry-run] — no TXs sent")
        return

    hub = joystick_hub(w3=w3_submit)
    gibs_cs = cs(GIBS_LAU)
    other_cs = cs(other_token)
    router_addr = cs(PULSEX_V2_ROUTER)

    # Step 1: Withdraw other token from Hub → Joey
    print(f"\n  Step 1: withdraw({seed_other + seed_gibs} {other_name} from Hub)")
    total_withdraw = (seed_other + seed_gibs) * 10**18  # seed_gibs AFF for Purchase + seed_other for LP
    r = send_tx(hub.functions.withdraw(other_cs, total_withdraw),
                f"withdraw({seed_other + seed_gibs} {other_name})",
                skip_simulate=True, fixed_gas=100_000)
    if not r:
        print("  FAILED"); return
    print(f"    TX: 0x{r['transactionHash'].hex()}")

    # Step 2: Prime GIBS_LAU self-balance (free — no AFF cost here)
    print(f"  Step 2: primeGibs({seed_gibs}) — primes GIBS_LAU self-balance")
    r = send_tx(hub.functions.primeGibs(seed_gibs),
                f"primeGibs({seed_gibs}) [seed-lp]", gas_tier="fast")
    if not r:
        print("  FAILED"); return
    print(f"    TX: 0x{r['transactionHash'].hex()}  Block: {r['blockNumber']}")

    # Step 3: Joey calls GIBS_LAU.Purchase(AFF, seed_gibs) to extract GIBS
    # Purchase costs 1 AFF per GIBS (market rate set at LAU birth)
    print(f"  Step 3: Purchase({seed_gibs} GIBS for {seed_gibs} AFF)")
    PURCHASE_ABI = [{"inputs": [{"name": "_t", "type": "address"},
                     {"name": "_a", "type": "uint256"}],
                     "name": "Purchase", "outputs": [], "type": "function"}]
    gibs_contract = w3_submit.eth.contract(address=gibs_cs, abi=PURCHASE_ABI)
    # Approve AFF → GIBS_LAU for Purchase payment
    approve_if_needed(
        w3_submit.eth.contract(address=other_cs, abi=erc20(other_token).abi),
        gibs_cs, 2**256 - 1, f"{other_name}→GIBS_LAU")
    r = send_tx(gibs_contract.functions.Purchase(other_cs, seed_gibs * 10**18),
                f"Purchase({seed_gibs} GIBS)")
    if not r:
        print("  FAILED"); return
    print(f"    TX: 0x{r['transactionHash'].hex()}")

    # Step 4: Low-level LP — transfer tokens to pair + mint
    # (Bypasses router safeTransferFrom which reverts on GIBS LAU)
    pair_cs = cs(pair_addr)

    # Use actual Joey balances (may differ from seed targets due to rounding)
    joey_gibs_bal = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
    joey_other_bal = safe(erc20(other_token), "balanceOf", JOEY_WALLET) or 0

    # Match pool ratio using the smaller side
    gibs_for_lp = min(joey_gibs_bal, int(joey_other_bal / ratio))
    other_for_lp = int(gibs_for_lp * ratio)

    print(f"  Step 4: transfer {gibs_for_lp/1e18:.2f} GIBS → pair")
    TRANSFER_ABI = [{"inputs": [{"name": "to", "type": "address"},
                     {"name": "amount", "type": "uint256"}],
                     "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
                     "type": "function"}]
    gibs_token = w3_submit.eth.contract(address=gibs_cs, abi=TRANSFER_ABI)
    r = send_tx(gibs_token.functions.transfer(pair_cs, gibs_for_lp),
                f"transfer({gibs_for_lp//10**18} GIBS → pair)",
                skip_simulate=True, fixed_gas=150_000)
    if not r:
        print("  FAILED"); return
    print(f"    TX: 0x{r['transactionHash'].hex()}")

    print(f"  Step 5: transfer {other_for_lp/1e18:.2f} {other_name} → pair")
    other_token_c = w3_submit.eth.contract(address=other_cs, abi=TRANSFER_ABI)
    r = send_tx(other_token_c.functions.transfer(pair_cs, other_for_lp),
                f"transfer({other_for_lp//10**18} {other_name} → pair)",
                skip_simulate=True, fixed_gas=150_000)
    if not r:
        print("  FAILED"); return
    print(f"    TX: 0x{r['transactionHash'].hex()}")

    print(f"  Step 6: pair.mint(Joey) — mint LP tokens")
    MINT_ABI = [{"inputs": [{"name": "to", "type": "address"}],
                 "name": "mint", "outputs": [{"name": "liquidity", "type": "uint256"}],
                 "type": "function"}]
    pair_c = w3_submit.eth.contract(address=pair_cs, abi=MINT_ABI)
    r = send_tx(pair_c.functions.mint(JOEY_WALLET),
                f"pair.mint(Joey)", skip_simulate=True, fixed_gas=300_000)
    if not r:
        print("  FAILED"); return
    print(f"    TX: 0x{r['transactionHash'].hex()}  Block: {r['blockNumber']}")

    # Final state
    reserves2 = pc.functions.getReserves().call()
    if t0.lower() == GIBS_LAU.lower():
        g2, o2 = reserves2[0], reserves2[1]
    else:
        g2, o2 = reserves2[1], reserves2[0]
    hub_remaining = (safe(erc20(other_token), "balanceOf", JOYSTICK_HUB) or 0) / 1e18

    print(f"\n{'━'*60}")
    print(f"  DONE — GIBS/{other_name} V2 seeded")
    print(f"  Before: {gibs_r/1e18:.2f} GIBS / {other_r/1e18:.2f} {other_name}")
    print(f"  After:  {g2/1e18:.2f} GIBS / {o2/1e18:.2f} {other_name}")
    print(f"  Hub {other_name}: {hub_remaining:.2f}")
    print(f"{'━'*60}")


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
    parser.add_argument("--e2-only", action="store_true",
                        help="Run single E2 Hub harvest cycle and exit")
    parser.add_argument("--e6-only", action="store_true",
                        help="Run single E6 treasury snipe and exit")
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
    parser.add_argument("--engine", type=str, default="",
                        help="Run a specific engine by name (e.g. --engine Arb, --engine PHR3AK)")
    parser.add_argument("--lp-fees", action="store_true",
                        help="Report LP fee accrual vs saved baseline (takes initial baseline on first run)")
    parser.add_argument("--reset-baseline", action="store_true",
                        help="With --lp-fees: overwrite baseline with current state")
    parser.add_argument("--seed-lp", type=str, default="",
                        help="Seed LP pair (e.g. --seed-lp GIBS_AFF). "
                             "Primes GIBS via Hub, withdraws, adds liquidity to V2 pair.")
    parser.add_argument("--mint-lp", type=str, default="",
                        help="Mint LP from tokens already deposited in a pair "
                             "(e.g. --mint-lp 0x1E2f...)")
    parser.add_argument("--grow-pair", action="store_true",
                        help="Grow GIBS/AFF LP pool until it exceeds GIBS/WPLS. "
                             "Buys AFF from DEX, mints GIBS, adds LP in batches of 500.")
    parser.add_argument("--pump", action="store_true",
                        help="Buy GIBS from cheapest pair + LP at new price. "
                             "Creates upward pressure. Arb bots equalize across pairs.")
    args = parser.parse_args()

    if args.rpc_status:
        print(f"\n{'━'*60}")
        print(f"  Joystick RPC Provider Health")
        print(f"{'━'*60}")
        rpc_health()
        return

    if args.lp_fees:
        from .oracle import lp_fees
        # Pairs that may not yet be in a stale registry snapshot.
        # GIBS/PRVX: 0x89D38BfBFf92Cfc3C9ab8368E2348AaaD6c68C50 (Joey-deployed)
        extra = [{
            "pair_address": "0x89D38BfBFf92Cfc3C9ab8368E2348AaaD6c68C50",
            "token_a": "0x66a08aa12da955eb63d7ac121a88b2b210a07b03",  # GIBS
            "token_b": "0xF6f8Db0a94AC9A5F55a1f80FB7ff73AfDC3e7A0e",  # PRVX (placeholder; auto-reread from pair if mismatch)
            "symbol_a": "GIBS",
            "symbol_b": "PRVX",
            "factory": "V2",
        }]
        # Normalize token_b from on-chain — don't trust the placeholder above
        try:
            from .core.chain import pair_contract, safe as _safe
            pc = pair_contract(extra[0]["pair_address"])
            t0 = _safe(pc, "token0"); t1 = _safe(pc, "token1")
            if t0 and t1:
                GIBS_LC = extra[0]["token_a"].lower()
                if t0.lower() == GIBS_LC:
                    extra[0]["token_a"], extra[0]["token_b"] = t0, t1
                else:
                    extra[0]["token_a"], extra[0]["token_b"] = t1, t0
        except Exception as exc:
            print(f"warn: failed to verify GIBS/PRVX token order: {exc}")

        print("Scanning Joey's GIBS LP positions via multicall...")
        positions = lp_fees.scan_joey_lp_positions(extra_pairs=extra)
        if not positions:
            print("No LP positions found (Joey holds 0 LP in all known GIBS pairs).")
            return

        baseline = lp_fees.load_baseline() if not args.reset_baseline else None

        if baseline is None:
            # First run (or reset) — snapshot current state as baseline
            lp_fees.save_baseline(positions)
            print(lp_fees.format_positions_table(positions))
            if args.reset_baseline:
                print("Baseline RESET to current state.")
            else:
                print("Initial baseline snapshot saved. Run --lp-fees again later to see delta.")
            return

        report = lp_fees.compute_fee_accrual(baseline, positions)
        print(lp_fees.format_positions_table(positions))
        print()
        print(lp_fees.format_report(report, positions))
        return

    if args.pump:
        _ladder_up(dry_run=args.dry_run)
        return

    if args.grow_pair:
        _grow_gibs_aff(dry_run=args.dry_run)
        return

    if args.mint_lp:
        # Skim excess tokens from pair back to Joey, then add via TGSv8
        from web3 import Web3
        from .core.executor import send_tx, approve_if_needed
        from .core.config import JOEY_WALLET, GIBS_LAU, AFFECTION
        from .core.chain import w3_submit, safe, erc20, tgsv8_contract
        cs = Web3.to_checksum_address
        pair_addr = cs(args.mint_lp)

        # Step 1: Skim excess tokens from pair → Joey
        skim_abi = [{"inputs": [{"name": "to", "type": "address"}],
                     "name": "skim", "outputs": [], "type": "function"}]
        pair_c = w3_submit.eth.contract(address=pair_addr, abi=skim_abi)
        print(f"Step 1: skim({pair_addr}) → Joey")
        r = send_tx(pair_c.functions.skim(JOEY_WALLET),
                    "pair.skim(Joey)", skip_simulate=True, fixed_gas=200_000)
        if r:
            print(f"  TX: 0x{r['transactionHash'].hex()}")
        else:
            print("  skim FAILED"); return

        joey_gibs = (safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0) / 1e18
        joey_aff = (safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0) / 1e18
        print(f"  Joey: {joey_gibs:.2f} GIBS, {joey_aff:.2f} AFF")

        # Step 2: Compute ratio-matched amounts then deposit into TGSv8
        tgs = tgsv8_contract(w3=w3_submit)
        tgs_addr = tgs.address
        gibs_cs = cs(GIBS_LAU)
        aff_cs = cs(AFFECTION)
        MAX_UINT = 2**256 - 1

        # Read pool ratio and match amounts
        pair_abi_r = [{"constant":True,"inputs":[],"name":"getReserves",
                       "outputs":[{"name":"","type":"uint112"},{"name":"","type":"uint112"},
                                  {"name":"","type":"uint32"}],"type":"function"},
                      {"constant":True,"inputs":[],"name":"token0",
                       "outputs":[{"name":"","type":"address"}],"type":"function"}]
        from .core.chain import w3_read
        pc_r = w3_read.eth.contract(address=pair_addr, abi=pair_abi_r)
        res = pc_r.functions.getReserves().call()
        tok0 = pc_r.functions.token0().call()
        if tok0.lower() == AFFECTION.lower():
            r_aff, r_gibs = res[0], res[1]
        else:
            r_gibs, r_aff = res[0], res[1]
        ratio = r_aff / r_gibs

        joey_gibs_wei = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
        joey_aff_wei = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0

        # Use GIBS as base, compute matching AFF
        gibs_amt = joey_gibs_wei
        aff_needed = int(gibs_amt * ratio)
        if aff_needed > joey_aff_wei:
            # Scale down to what AFF allows
            aff_amt = joey_aff_wei
            gibs_amt = int(aff_amt / ratio)
        else:
            aff_amt = aff_needed

        joey_gibs = gibs_amt / 1e18
        joey_aff = aff_amt / 1e18
        print(f"  Ratio-matched: {joey_gibs:.2f} GIBS + {joey_aff:.2f} AFF")

        print(f"Step 2: deposit {joey_gibs:.0f} GIBS + {joey_aff:.0f} AFF → TGSv8")
        # Approve + deposit GIBS
        approve_if_needed(
            w3_submit.eth.contract(address=gibs_cs, abi=erc20(GIBS_LAU).abi),
            tgs_addr, MAX_UINT, "GIBS→TGSv8")
        r = send_tx(tgs.functions.deposit(gibs_cs, gibs_amt),
                    f"deposit({int(joey_gibs)} GIBS)", skip_simulate=True, fixed_gas=200_000)
        if r:
            print(f"  GIBS deposited: 0x{r['transactionHash'].hex()}")

        # Approve + deposit AFF
        approve_if_needed(
            w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi),
            tgs_addr, MAX_UINT, "AFF→TGSv8")
        r = send_tx(tgs.functions.deposit(aff_cs, aff_amt),
                    f"deposit({int(joey_aff)} AFF)", skip_simulate=True, fixed_gas=200_000)
        if r:
            print(f"  AFF deposited: 0x{r['transactionHash'].hex()}")

        # Step 3: TGSv8.addLiquidity → LP to Joey
        # Re-read TGSv8 balances (may have tokens from prior failed runs)
        tgs_gibs = safe(erc20(GIBS_LAU), "balanceOf", tgs_addr) or 0
        tgs_aff = safe(erc20(AFFECTION), "balanceOf", tgs_addr) or 0
        if tgs_gibs > gibs_amt:
            gibs_amt = tgs_gibs
            aff_amt = int(gibs_amt * ratio)
            if aff_amt > tgs_aff:
                aff_amt = tgs_aff
                gibs_amt = int(aff_amt / ratio)
            joey_gibs = gibs_amt / 1e18
            joey_aff = aff_amt / 1e18
            print(f"  Using TGSv8 balances: {joey_gibs:.2f} GIBS + {joey_aff:.2f} AFF")

        if gibs_amt == 0 or aff_amt == 0:
            print(f"  No tokens to LP (TGSv8 GIBS={tgs_gibs/1e18:.2f}, AFF={tgs_aff/1e18:.2f})")
            return

        print(f"Step 3: TGSv8.addLiquidity({joey_gibs:.0f} GIBS, {joey_aff:.0f} AFF) → Joey")
        r = send_tx(tgs.functions.addLiquidity(
                        gibs_cs, aff_cs, gibs_amt, aff_amt,
                        1000,  # 10% slippage in bps
                        JOEY_WALLET,
                        1),   # DEX.V2
                    f"addLiquidity({int(joey_gibs)} GIBS + {int(joey_aff)} AFF)")
        if r:
            print(f"  SUCCESS! TX: 0x{r['transactionHash'].hex()}  Block: {r['blockNumber']}")
        else:
            print("  addLiquidity FAILED")
        return

    if args.seed_lp:
        _run_seed_lp(args.seed_lp, dry_run=args.dry_run)
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

    if args.e2_only:
        engine = next((e for e in bot.engines if e.name == "DSS"), None)
        if not engine:
            print("E2 DSS engine not found (excluded?)", file=sys.stderr)
            sys.exit(1)
        print(f"Running E2 CEREAL ({'dry-run' if args.dry_run else 'LIVE'})...")
        print(f"  Ready: {engine.is_ready()}")
        try:
            sim_profit, sim_gas = engine.simulate()
            print(f"  Simulate: profit={sim_profit/1e18:.4f} PLS, gas={sim_gas/1e18:.4f} PLS")
        except Exception as e:
            print(f"  Simulate: {e}")
        result = engine.execute(dry_run=args.dry_run)
        _events.log_engine_result("DSS", result)
        print(f"  Result: success={result.success} net={result.net_pls:.4f} PLS "
              f"txs={len(result.tx_hashes)} notes={result.notes}")
        return

    if args.e6_only:
        engine = next((e for e in bot.engines if e.name == "TreasurySniper"), None)
        if not engine:
            print("E6 TreasurySniper engine not found (excluded?)", file=sys.stderr)
            sys.exit(1)
        print(f"Running E6 DaVINCI ({'dry-run' if args.dry_run else 'LIVE'})...")
        print(f"  Ready: {engine.is_ready()}")
        try:
            sim_profit, sim_gas = engine.simulate()
            print(f"  Simulate: profit={sim_profit/1e18:.4f} PLS, gas={sim_gas/1e18:.4f} PLS")
        except Exception as e:
            print(f"  Simulate: {e}")
        result = engine.execute(dry_run=args.dry_run)
        _events.log_engine_result("TreasurySniper", result)
        print(f"  Result: success={result.success} net={result.net_pls:.4f} PLS "
              f"txs={len(result.tx_hashes)} notes={result.notes}")
        return

    if args.engine:
        target = args.engine.strip()
        engine = None
        for e in bot.engines:
            if e.name.lower() == target.lower() or e.display_name.lower().startswith(target.lower()):
                engine = e
                break
        if not engine:
            print(f"Unknown engine: {target}", file=sys.stderr)
            print(f"Available: {', '.join(e.name for e in bot.engines)}", file=sys.stderr)
            sys.exit(1)
        print(f"Running {engine.display_name} ({'dry-run' if args.dry_run else 'LIVE'})...")
        print(f"  Ready: {engine.is_ready()}")
        try:
            sim_profit, sim_gas = engine.simulate()
            print(f"  Simulate: profit={sim_profit/1e18:.4f} PLS, gas={sim_gas/1e18:.4f} PLS")
        except Exception as e:
            print(f"  Simulate: {e}")
        result = engine.execute(dry_run=args.dry_run)
        _events.log_engine_result(engine.name, result)
        print(f"  Result: success={result.success} net={result.net_pls:.4f} PLS "
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
