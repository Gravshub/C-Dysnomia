"""
Engine 6 (DaVINCI) — Treasury Sniper
|>JOYSTICK<| / Dysnomia · Atropa · PulseChain

What it does:
  Scans all known treasury tokens for claimable backing. When a token holds
  parent tokens in its own self-balance, you can Claim them by spending child
  tokens. If the cost to acquire child tokens < value of the parent tokens
  you receive, that's pure profit.

Flow per opportunity:
  1. Multicall: read selfBalance, parentBalance, DEX reserves
  2. Estimate cost to acquire child tokens (DEX buy or mint)
  3. Estimate value of parent tokens (DEX sell)
  4. If value_out > cost_in + gas → execute via TGSv8.batchClaimTreasury

TGSv8 functions used:
  claimFromTreasury(treasury, backingAsset, amount) → received
  batchClaimTreasury(treasuries[], backingAssets[], amounts[]) → results[]
  getBestAmountsOut(amountIn, path) — oracle pre-flight
  bal(token) — internal balance view

File: scripts/Joystick/engines/treasury_sniper.py
Implements: EngineBase ABC (is_ready, simulate, execute)
"""

import json
import logging

from ..core.log_names import get_logger
import os
import time
from dataclasses import dataclass
from typing import Optional

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, TGSV8, WPLS, GAS_PRICE_CEIL, GAS_MULT,
    CROSS_TREASURY_MIN_IMPROVEMENT,
    PULSEX_V1_ROUTER, PULSEX_V2_ROUTER,
)
from ..core.chain import w3_read, w3_submit, tgsv8_contract, safe, multicall, erc20
from ..core.executor import send_tx
from ..core.simulator import SimulationFailed
from ..core import wallet
from ..oracle.price import get_amounts_out, get_amounts_out_v2

log = get_logger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────
DEX_BEST = 2

# Minimum profit threshold in PLS (100 PLS)
MIN_PROFIT_PLS = 100
# Max tokens to batch in one batchClaimTreasury TX
BATCH_SIZE = 10
# Recon cache TTL in seconds (60 minutes)
RECON_CACHE_TTL = 3600
# Approximate gas per claim operation
GAS_PER_CLAIM = 400_000


@dataclass
class TreasuryTarget:
    """One claimable treasury opportunity identified by recon."""
    label:          str
    address:        str            # treasury token address
    backing_asset:  str            # parent token address
    self_balance:   int            # child tokens held in treasury (wei)
    parent_balance: int            # parent tokens held in treasury (wei)
    pls_per_token:  float          # DEX price: 1 child token → PLS (float, not wei)
    parent_pls:     float          # DEX price: 1 parent token → PLS (float)
    decimals:       int = 18
    estimated_pls:  float = 0.0


class TreasurySniperEngine(EngineBase):
    """
    Engine 6 (DaVINCI) — Treasury Sniper.

    Reads recon_results.json (written by treasury_recon.py) and executes
    profitable claimFromTreasury operations through TGSv8.

    Priority: HIGH — single-execution treasury sweeps. Once claimed, backing
    is gone. Run early, run once per treasury per session.
    """
    name = "TreasurySniper"

    def __init__(self):
        super().__init__()
        self._targets: list[TreasuryTarget] = []
        self._claimed: set[str] = set()
        self._last_load = 0.0
        self._recon_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "recon_results.json"
        )

    # ── EngineBase interface ───────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Ready when TGSv8 is set and recon data exists with profitable targets."""
        if not TGSV8:
            log.debug("E6: TGSV8_ADDRESS not set")
            return False

        # Auto-refresh stale recon data (>24h old)
        self._maybe_refresh_recon()

        if not os.path.exists(self._recon_path):
            log.debug("E6: recon_results.json not found — run treasury_recon.py first")
            return False

        # Load targets to check if any are profitable
        self._refresh_targets()
        if not self._targets:
            log.debug("E6: no profitable treasury targets in recon data")
            return False

        return True

    def simulate(self) -> tuple[int, int]:
        """
        Returns (expected_profit_wei, estimated_gas_cost_wei).
        Uses live DEX quotes (same as execute) to avoid stale recon inflation.
        """
        self._refresh_targets()
        if not self._targets:
            return (0, 0)

        best = self._pick_best_batch()
        if not best:
            return (0, 0)

        # Use live DEX quotes per target (same method as _execute_batch)
        MAX_SANE_PROFIT_WEI = int(100_000 * 10**18)  # 100K PLS per-target cap
        MAX_BATCH_PROFIT_WEI = int(50_000 * 10**18)   # 50K PLS batch cap
        total_profit = 0
        for t in best:
            claim_amount = self._size_claim(t)
            if claim_amount > 0:
                route = self._find_best_sell_route(t.backing_asset, claim_amount)
                est = min(route["expected_pls"], MAX_SANE_PROFIT_WEI)
            else:
                est = min(int(t.estimated_pls * 10**18), MAX_SANE_PROFIT_WEI)
            total_profit += est

        # Batch-level cap prevents runaway sums from many targets
        total_profit = min(total_profit, MAX_BATCH_PROFIT_WEI)

        gas_price = w3_read.eth.gas_price
        gas_cost = GAS_PER_CLAIM * len(best) * gas_price

        if total_profit <= gas_cost:
            return (0, 0)

        return (total_profit - gas_cost, gas_cost)

    def execute(self, dry_run: bool = False) -> EngineResult:
        """
        Executes the best available batch of treasury claims.
        Simulates via eth_call first. Never sends blind.
        """
        self._refresh_targets()
        batch = self._pick_best_batch()
        if not batch:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="no profitable targets")

        gas_price = w3_read.eth.gas_price
        if gas_price > GAS_PRICE_CEIL:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes=f"gas too high: {gas_price/1e9:.0f} Beats")

        try:
            tgsv8 = tgsv8_contract(w3=w3_submit)
            result = self._execute_batch(tgsv8, batch, gas_price, dry_run)
            if result.success:
                for t in batch:
                    self._claimed.add(t.address.lower())
            return result
        except Exception as e:
            log.error("E6execute error: %s", e)
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes=str(e))

    # ── Internal mechanics ────────────────────────────────────────────────

    def _maybe_refresh_recon(self):
        """Re-run treasury recon if data is >24h stale."""
        if not os.path.exists(self._recon_path):
            self._run_recon()
            return
        mtime = os.path.getmtime(self._recon_path)
        if time.time() - mtime > 86400:  # 24 hours
            log.info("E6: recon data >24h stale — refreshing")
            self._run_recon()

    def _run_recon(self):
        """Shell out to treasury_recon.py."""
        import subprocess
        import sys
        recon_script = os.path.join(
            os.path.dirname(__file__), "..", "data", "treasury_recon.py"
        )
        if os.path.exists(recon_script):
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
            log.info("E6: running treasury_recon.py (timeout 300s)")
            try:
                subprocess.run(
                    [sys.executable, recon_script, "--data-dir", data_dir],
                    timeout=300,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                log.warning("E6: treasury_recon.py timed out — using cached data")
        else:
            log.debug("E6: treasury_recon.py not found at %s", recon_script)

    def _refresh_targets(self):
        """Load/refresh recon data. Respects TTL cache."""
        now = time.time()
        if now - self._last_load < RECON_CACHE_TTL and self._targets:
            return

        from ..oracle.data_store import DataStore
        recon = DataStore.get().recon_data(max_age=RECON_CACHE_TTL)
        if not recon:
            log.warning("E6: failed to load recon_results.json")
            return

        targets = []
        results = recon.get("results", {})

        for addr, entry in results.items():
            cd = entry.get("chain_data", {})

            if addr.lower() in self._claimed:
                continue

            self_bal    = cd.get("selfBalance", 0)
            parent_bal  = cd.get("parentBalance", 0)
            pls_per_tok = cd.get("pls_per_token", 0)
            parent_addr = cd.get("parent")
            decimals    = cd.get("decimals", 18)

            if self_bal == 0 or pls_per_tok == 0 or not parent_addr:
                continue
            if parent_addr in ("0x" + "0" * 40, None):
                continue

            qty_tokens = self_bal / (10 ** decimals)
            # pls_per_tok is the child token's DEX price (from recon).
            # This gives gross value of claimable tokens, NOT net profit
            # (cost to acquire ammo is unknown here). Used only for
            # filtering and sort order — live DEX quotes in simulate()
            # and _execute_batch() do the real pricing.
            token_pls = pls_per_tok
            est_pls_gross = qty_tokens * token_pls

            if est_pls_gross < MIN_PROFIT_PLS:
                continue

            targets.append(TreasuryTarget(
                label         = entry.get("label", addr[:10]),
                address       = addr,
                backing_asset = parent_addr,
                self_balance  = self_bal,
                parent_balance= parent_bal,
                pls_per_token = pls_per_tok,
                parent_pls    = token_pls,
                decimals      = decimals,
                estimated_pls = est_pls_gross,
            ))

        targets.sort(key=lambda t: t.estimated_pls, reverse=True)
        self._targets = targets
        self._last_load = now
        log.info("E6: loaded %d treasury targets from recon", len(targets))

    def _pick_best_batch(self) -> list[TreasuryTarget]:
        """Choose the best batch of treasury targets for this cycle."""
        if not self._targets:
            return []

        gas_price    = w3_read.eth.gas_price
        gas_cost_wei = int(GAS_PER_CLAIM * gas_price * GAS_MULT)

        profitable = []
        for t in self._targets:
            if t.address.lower() in self._claimed:
                continue

            claim_amount = self._size_claim(t)
            if claim_amount == 0:
                continue

            profit_est = claim_amount / (10 ** t.decimals) * t.parent_pls
            if int(profit_est * 10**18) > gas_cost_wei:
                profitable.append(t)

            if len(profitable) >= BATCH_SIZE:
                break

        return profitable

    def _size_claim(self, t: TreasuryTarget) -> int:
        """Return the amount of child tokens to spend in the Claim call."""
        try:
            tgsv8 = tgsv8_contract()
            tgsv8_child_bal = safe(tgsv8, "bal", Web3.to_checksum_address(t.address)) or 0
        except Exception:
            return 0

        available = min(tgsv8_child_bal, t.self_balance)
        return available

    def _find_best_sell_route(self, parent_addr: str, amount: int) -> dict:
        """
        Find best route to convert parent tokens to PLS.

        Checks:
          1. parent -> WPLS (direct, V1 and V2)
          2. parent -> other_treasury_token -> WPLS (cross-treasury hop)

        Returns: {"route": [addr, ...], "router": "V1"|"V2",
                  "expected_pls": int, "mode": "direct"|"cross_treasury"}
        """
        parent_cs = Web3.to_checksum_address(parent_addr)
        wpls_cs = Web3.to_checksum_address(WPLS)
        best = {"route": [parent_cs, wpls_cs], "router": "V1",
                "expected_pls": 0, "mode": "direct"}

        # Direct V1
        v1_out = get_amounts_out(amount, [parent_cs, wpls_cs])
        if v1_out:
            best["expected_pls"] = v1_out[-1]

        # Direct V2
        v2_out = get_amounts_out_v2(amount, [parent_cs, wpls_cs])
        if v2_out and v2_out[-1] > best["expected_pls"]:
            best = {"route": [parent_cs, wpls_cs], "router": "V2",
                    "expected_pls": v2_out[-1], "mode": "direct"}

        direct_pls = best["expected_pls"]
        if direct_pls == 0:
            return best

        # Cross-treasury: parent -> other_treasury -> WPLS
        # Only check targets we already loaded (cheap, no extra RPC)
        cross_candidates = []
        for t in self._targets:
            other = Web3.to_checksum_address(t.address)
            if other.lower() == parent_cs.lower():
                continue
            cross_candidates.append(other)

        # Limit to top 10 candidates by estimated PLS value to bound RPC calls
        cross_candidates = cross_candidates[:10]

        for intermediate in cross_candidates:
            for getter, label in [(get_amounts_out, "V1"), (get_amounts_out_v2, "V2")]:
                try:
                    hop1 = getter(amount, [parent_cs, intermediate])
                    if not hop1 or hop1[-1] == 0:
                        continue
                    hop2 = getter(hop1[-1], [intermediate, wpls_cs])
                    if not hop2 or hop2[-1] == 0:
                        continue
                    total_pls = hop2[-1]
                    improvement = (total_pls - direct_pls) / direct_pls if direct_pls > 0 else 0
                    if improvement >= CROSS_TREASURY_MIN_IMPROVEMENT and total_pls > best["expected_pls"]:
                        best = {
                            "route": [parent_cs, intermediate, wpls_cs],
                            "router": label,
                            "expected_pls": total_pls,
                            "mode": "cross_treasury",
                        }
                        log.info(
                            "E6: cross-treasury route via %s yields +%.1f%% vs direct",
                            intermediate[:10], improvement * 100,
                        )
                except Exception:
                    continue

        return best

    def _execute_batch(self, tgsv8, batch: list[TreasuryTarget],
                       gas_price: int, dry_run: bool) -> EngineResult:
        """Simulate then submit batchClaimTreasury TX."""
        treasuries     = [Web3.to_checksum_address(t.address)       for t in batch]
        backing_assets = [Web3.to_checksum_address(t.backing_asset) for t in batch]
        amounts        = [self._size_claim(t) for t in batch]

        valid = [(t, b, a) for t, b, a in zip(treasuries, backing_assets, amounts) if a > 0]
        if not valid:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="all amounts zero after sizing")

        treasuries, backing_assets, amounts = zip(*valid)
        treasuries     = list(treasuries)
        backing_assets = list(backing_assets)
        amounts        = list(amounts)

        fn_call = tgsv8.functions.batchClaimTreasury(treasuries, backing_assets, amounts)

        # Estimate real PLS output using best sell routes.
        # route["expected_pls"] is in wei (raw DEX output). Cap at 100K PLS per
        # target to prevent inflated cross-treasury route estimates from
        # dominating strategist scoring.
        MAX_SANE_PROFIT_WEI = int(100_000 * 10**18)  # 100K PLS sanity cap
        total_est_pls = 0
        sell_routes = {}
        for t in batch:
            claim_amount = self._size_claim(t)
            if claim_amount > 0:
                route = self._find_best_sell_route(t.backing_asset, claim_amount)
                sell_routes[t.address.lower()] = route
                est = route["expected_pls"]
                if est > MAX_SANE_PROFIT_WEI:
                    log.warning("E6: capping inflated route estimate %d wei → %d", est, MAX_SANE_PROFIT_WEI)
                    est = MAX_SANE_PROFIT_WEI
                total_est_pls += est
            else:
                total_est_pls += int(t.estimated_pls * 10**18)

        if total_est_pls == 0:
            total_est_pls = sum(int(t.estimated_pls * 10**18) for t in batch)

        result = send_tx(
            fn_call,
            f"TreasurySniper: batch claim {len(treasuries)} treasuries",
            dry_run=dry_run,
        )

        cross_count = sum(1 for r in sell_routes.values() if r["mode"] == "cross_treasury")
        route_note = f" ({cross_count} cross-treasury routes)" if cross_count else ""

        if result is None and dry_run:
            return EngineResult(
                success=True, profit_wei=total_est_pls, gas_wei=0,
                notes=f"[dry-run] would claim from {len(treasuries)} treasuries{route_note}",
            )

        if result and result.get("status") == 1:
            gas_used = result["gasUsed"] * result.get("effectiveGasPrice", gas_price)
            tx_hash = result["transactionHash"].hex()
            log.info("E6 SUCCESS — claimed from %d treasuries%s", len(treasuries), route_note)
            return EngineResult(
                success=True, profit_wei=total_est_pls, gas_wei=gas_used,
                tx_hashes=[tx_hash],
                notes=f"Claimed {len(treasuries)} treasuries{route_note}",
            )
        else:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="TX reverted on-chain")

    def status_line(self) -> str:
        """One-line engine status."""
        self._refresh_targets()
        state = "DISABLED" if self.is_disabled() else ("READY" if self.is_ready() else "NOT READY")
        return (f"{self.name}: {state} "
                f"(targets={len(self._targets)}, claimed={len(self._claimed)}, "
                f"failures={self.failure_count})")
