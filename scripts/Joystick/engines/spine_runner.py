"""
Engine 7 (BACKBONE) — Spine Runner
|>JOYSTICK<| / Dysnomia · Atropa · PulseChain

What it does:
  Exploits the V2 Federal mint-claim infinite loop.

The mechanic:
  1. Hold parent tokens (e.g., BAR)
  2. Call mint(amount) on child → spend parent 1:1, receive child tokens
  3. Call Claim(spendToken, amount) on child → spend an unpublished V2 token
     (Debenture=True), receive parent back 1:1
  4. Parent recovered. Net: free child tokens at gas cost only.
  5. Repeat indefinitely. Child tokens → DEX sell → PLS.

TGSv8 wraps this as mintAndClaim(child, spendToken, amount).
batchMintAndClaim() runs N iterations in one TX.

Constraints:
  1. We must hold the parent token in TGSv8
  2. We must hold or acquire a Debenture=True spendToken for the Claim call
  3. Child token must have DEX liquidity to sell into
  4. Monitor Debenture status every cycle — if published(), the loop locks

File: scripts/Joystick/engines/spine_runner.py
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
from ..core.config import JOEY_WALLET, TGSV8, WPLS, GAS_PRICE_CEIL, GAS_MULT
from ..core.chain import w3_read, w3_submit, tgsv8_contract, safe
from ..core.executor import send_tx

log = get_logger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────
DEX_BEST = 2

# Known addresses from prior recon
OZZY_ADDR = Web3.to_checksum_address("0x52b4F56d87765E7A9567E35bea97de13C3386554")
BAR_ADDR  = Web3.to_checksum_address("0xaAE18Cd46C45d343BbA1eab46716B4D69d799734")

SLIP_BPS           = 150     # 1.5% slippage on sell leg
BATCH_ITERATIONS   = 20      # iterations per batchMintAndClaim TX (TGSv8 maxBatch default)
MIN_SELL_THRESHOLD = 500     # accumulate at least 500 child tokens before selling
RECON_CACHE_TTL    = 1800    # 30-minute cache on recon data
SPINE_GAS_EST      = 450_000 # gas estimate for batch mint+claim + sell


@dataclass
class Spine:
    """
    One active spine: a child token + spendToken pair that can loop.

    child:       the token we're minting (e.g., OZZY)
    parent:      the token we spend to mint and get back from Claim (e.g., BAR)
    spend_token: the Debenture=True token burned in the Claim call
    pls_per_child: DEX price for selling child tokens
    """
    label:          str
    child:          str
    parent:         str
    spend_token:    str
    pls_per_child:  float
    decimals:       int = 18
    active:         bool = True
    last_debenture_check: float = 0.0


class SpineRunnerEngine(EngineBase):
    """
    Engine 7 (BACKBONE) — Spine Runner.

    Reads recon_results.json + v2_federal_tokens.json to find active spines.
    Runs batchMintAndClaim loops on active spines, then sells accumulated
    child tokens via swapExact → WPLS.

    Key invariant: verify checkDebenture() BEFORE every TX.
    """
    name = "SpineRunner"

    def __init__(self):
        super().__init__()
        self._spines: list[Spine] = []
        self._last_load = 0.0
        self._total_pls_earned = 0

        self._recon_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "recon_results.json"
        )
        self._v2fed_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "v2_federal_tokens.json"
        )

    # ── EngineBase interface ───────────────────────────────────────────────

    def is_ready(self) -> bool:
        if not TGSV8:
            log.debug("E7: TGSV8_ADDRESS not set")
            return False

        self._refresh_spines()

        active = [s for s in self._spines if s.active]
        if not active:
            log.debug("E7: no active spines found")
            return False

        try:
            tgsv8 = tgsv8_contract()
            for spine in active:
                parent_bal = safe(tgsv8, "bal", Web3.to_checksum_address(spine.parent)) or 0
                if parent_bal > 0:
                    return True
        except Exception as e:
            log.debug("E7: TGSv8 check failed: %s", e)
            return False

        log.debug("E7: active spines exist but no parent token balance in TGSv8")
        return False

    def simulate(self) -> tuple[int, int]:
        """
        Estimate profit from one batch cycle on the best active spine.
        Returns (expected_profit_wei, estimated_gas_cost_wei).
        """
        self._refresh_spines()
        best = self._pick_best_spine()
        if not best:
            return (0, 0)

        if not self._live_debenture_check(best):
            best.active = False
            return (0, 0)

        amount_per_iter = self._size_iteration(best)
        if amount_per_iter == 0:
            return (0, 0)

        child_out    = BATCH_ITERATIONS * amount_per_iter
        # child_out is in wei, pls_per_child is PLS per whole token (float)
        # Convert: (child_out_wei / 10^18) * pls_per_child * 10^18 = child_out * pls_per_child
        pls_expected = int(child_out * best.pls_per_child)

        gas_price = w3_read.eth.gas_price
        gas_cost  = int(SPINE_GAS_EST * gas_price * GAS_MULT)

        if pls_expected <= gas_cost:
            return (0, 0)

        return (pls_expected - gas_cost, gas_cost)

    def execute(self, dry_run: bool = False) -> EngineResult:
        """
        1. Pick best spine
        2. Verify Debenture status (live call)
        3. batchMintAndClaim — N iterations
        4. swapExact child tokens → WPLS (if accumulated enough)
        """
        self._refresh_spines()
        spine = self._pick_best_spine()
        if not spine:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="no active spines")

        gas_price = w3_read.eth.gas_price
        if gas_price > GAS_PRICE_CEIL:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes=f"gas too high: {gas_price/1e9:.0f} Beats")

        if not self._live_debenture_check(spine):
            spine.active = False
            log.warning("E7: %s Debenture flipped False — deactivating spine", spine.label)
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes=f"{spine.label} debenture is now False")

        try:
            return self._run_spine_cycle(spine, gas_price, dry_run)
        except Exception as e:
            log.error("E7execute error: %s", e)
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes=str(e))

    # ── Internal mechanics ────────────────────────────────────────────────

    def _refresh_spines(self):
        """Load/discover spines from recon data. Respects TTL."""
        now = time.time()
        if now - self._last_load < RECON_CACHE_TTL and self._spines:
            return

        spines = []

        from ..oracle.data_store import DataStore
        store = DataStore.get()
        v2fed_tokens = store.v2_federal_tokens()

        if v2fed_tokens:
            try:
                v2data = {"tokens": v2fed_tokens}
                for tok in v2data.get("tokens", []):
                    if tok.get("debenture") is not True:
                        continue
                    addr     = tok["address"]
                    label    = tok.get("symbol", addr[:8])
                    pls_ptok = tok.get("pls_per_token", 0.0)
                    if pls_ptok == 0:
                        log.debug("E7: skipping %s — no DEX price", label)
                        continue
                    parent = self._get_parent_from_recon(addr)
                    if not parent:
                        log.debug("E7: skipping %s — parent address unknown", label)
                        continue
                    spend_token = self._find_spend_token(addr, parent)
                    if not spend_token:
                        log.debug("E7: skipping %s — no valid spend token found", label)
                        continue

                    spines.append(Spine(
                        label         = label,
                        child         = Web3.to_checksum_address(addr),
                        parent        = Web3.to_checksum_address(parent),
                        spend_token   = Web3.to_checksum_address(spend_token),
                        pls_per_child = pls_ptok,
                        active        = True,
                    ))
            except Exception as e:
                log.warning("E7: error loading v2_federal_tokens.json: %s", e)

        if not spines:
            log.info("E7: using hardcoded OZZY fallback spine (recon pending)")
            spines.append(Spine(
                label         = "OZZY",
                child         = OZZY_ADDR,
                parent        = BAR_ADDR,
                spend_token   = OZZY_ADDR,
                pls_per_child = 0,
                active        = False,
            ))

        self._spines    = spines
        self._last_load = now
        log.info("E7: loaded %d spines (%d active)",
                 len(spines), sum(1 for s in spines if s.active))

    def _get_parent_from_recon(self, child_addr: str) -> Optional[str]:
        """Look up parent address from recon_results.json."""
        from ..oracle.data_store import DataStore
        recon = DataStore.get().recon_data()
        if not recon:
            return None
        try:
            entry = recon.get("results", {}).get(child_addr.lower(), {})
            parent = entry.get("chain_data", {}).get("parent")
            if parent and parent != "0x" + "0" * 40:
                return parent
        except Exception:
            pass
        return None

    def _find_spend_token(self, child_addr: str, parent_addr: str) -> Optional[str]:
        """Find a valid Debenture=True token to use as the spendToken."""
        from ..oracle.data_store import DataStore
        recon = DataStore.get().recon_data()
        if not recon:
            return None
        try:
            for addr, entry in recon.get("results", {}).items():
                cd = entry.get("chain_data", {})
                if (cd.get("parent", "").lower() == parent_addr.lower()
                        and cd.get("debenture") is True
                        and addr.lower() != child_addr.lower()):
                    return addr
        except Exception:
            pass
        return child_addr

    def _pick_best_spine(self) -> Optional[Spine]:
        """Return the highest-ROI active spine with parent balance in TGSv8."""
        candidates = []
        try:
            tgsv8 = tgsv8_contract()
        except Exception:
            return None

        for spine in self._spines:
            if not spine.active:
                continue
            if spine.pls_per_child == 0:
                continue
            parent_bal = safe(tgsv8, "bal", Web3.to_checksum_address(spine.parent)) or 0
            if parent_bal == 0:
                continue
            candidates.append((spine, parent_bal))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0].pls_per_child, reverse=True)
        return candidates[0][0]

    def _size_iteration(self, spine: Spine) -> int:
        """How many parent tokens to commit per iteration."""
        try:
            tgsv8 = tgsv8_contract()
            parent_bal = safe(tgsv8, "bal", Web3.to_checksum_address(spine.parent)) or 0
        except Exception:
            return 0
        if parent_bal == 0:
            return 0
        per_iter = max(10**spine.decimals, parent_bal // 10)
        return min(per_iter, 1000 * 10**spine.decimals)

    def _live_debenture_check(self, spine: Spine) -> bool:
        """Call TGSv8.checkDebenture() on-chain (eth_call, free)."""
        now = time.time()
        if now - spine.last_debenture_check < 60:
            return spine.active

        try:
            tgsv8 = tgsv8_contract()
            result = tgsv8.functions.checkDebenture(
                Web3.to_checksum_address(spine.child)
            ).call()
            spine.last_debenture_check = now
            if not result:
                log.warning("E7: %s debenture=False — spine is dead", spine.label)
                spine.active = False
            return result
        except Exception as e:
            log.warning("E7: debenture check error for %s: %s", spine.label, e)
            return False

    def _run_spine_cycle(self, spine: Spine, gas_price: int,
                         dry_run: bool) -> EngineResult:
        """Full execution cycle for one spine."""
        amount = self._size_iteration(spine)
        if amount == 0:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="iteration amount is zero")

        tgsv8 = tgsv8_contract(w3=w3_submit)

        children   = [spine.child]       * BATCH_ITERATIONS
        spend_toks = [spine.spend_token] * BATCH_ITERATIONS
        amounts    = [amount]            * BATCH_ITERATIONS

        fn_call = tgsv8.functions.batchMintAndClaim(children, spend_toks, amounts)

        result = send_tx(
            fn_call,
            f"SpineRunner: {spine.label} x{BATCH_ITERATIONS}",
            dry_run=dry_run,
        )

        # amount is in wei, pls_per_child is PLS per whole token (float)
        pls_expected = int(BATCH_ITERATIONS * amount * spine.pls_per_child)

        if result is None and dry_run:
            return EngineResult(
                success=True, profit_wei=int(pls_expected), gas_wei=0,
                notes=f"[dry-run] would run {spine.label} spine x{BATCH_ITERATIONS}",
            )

        if not result or result.get("status") != 1:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="batchMintAndClaim TX reverted")

        gas_used = result["gasUsed"] * result.get("effectiveGasPrice", gas_price)
        tx_hashes = [result["transactionHash"].hex()]

        # Sell leg: swap child → WPLS if above threshold
        child_bal = safe(tgsv8, "bal", Web3.to_checksum_address(spine.child)) or 0
        pls_earned = 0

        if child_bal >= MIN_SELL_THRESHOLD * 10**spine.decimals and not dry_run:
            sell_result = self._sell_child_tokens(spine, child_bal, gas_price)
            if sell_result.get("success"):
                pls_earned = sell_result.get("pls_out", 0)
                if sell_result.get("tx_hash"):
                    tx_hashes.append(sell_result["tx_hash"])

        self._total_pls_earned += pls_earned
        return EngineResult(
            success=True,
            profit_wei=pls_earned if pls_earned else int(pls_expected),
            gas_wei=gas_used,
            tx_hashes=tx_hashes,
            notes=f"{spine.label}: minted {BATCH_ITERATIONS} iterations",
        )

    def _sell_child_tokens(self, spine: Spine, amount: int,
                           gas_price: int) -> dict:
        """Swap accumulated child tokens → WPLS via TGSv8.swapExact()."""
        try:
            tgsv8 = tgsv8_contract()
            path = [Web3.to_checksum_address(spine.child),
                    Web3.to_checksum_address(WPLS)]
            v1, v2, best_dex, best_out = tgsv8.functions.getBestAmountsOut(
                amount, path
            ).call()
            if best_out == 0:
                return {"success": False, "reason": "no DEX output for child token"}
            min_out = int(best_out * (10000 - SLIP_BPS) / 10000)
        except Exception as e:
            log.warning("E7 sell pre-flight failed: %s", e)
            return {"success": False, "reason": str(e)}

        tgsv8_w = tgsv8_contract(w3=w3_submit)
        fn_call = tgsv8_w.functions.swapExact(
            Web3.to_checksum_address(spine.child),
            Web3.to_checksum_address(WPLS),
            amount, min_out, DEX_BEST
        )

        receipt = send_tx(fn_call, f"SpineRunner: sell {spine.label} → WPLS")
        if receipt and receipt.get("status") == 1:
            log.info("E7 sell TX confirmed — ~%.2f WPLS received", min_out / 1e18)
            return {"success": True, "pls_out": min_out,
                    "tx_hash": receipt["transactionHash"].hex()}
        return {"success": False, "reason": "sell TX reverted"}

    def status_line(self) -> str:
        """One-line engine status."""
        self._refresh_spines()
        active = [s for s in self._spines if s.active]
        state = "DISABLED" if self.is_disabled() else ("READY" if self.is_ready() else "NOT READY")
        labels = ", ".join(s.label for s in active) if active else "none"
        return (f"{self.name}: {state} "
                f"(spines={len(self._spines)}, active={len(active)} [{labels}], "
                f"earned={self._total_pls_earned/1e18:,.2f} PLS, "
                f"failures={self.failure_count})")
