"""
Engine 6 — Spine Runner
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

For a spine with OZZY (Debenture=True):
  - We own BAR (parent of OZZY)
  - mint(1 BAR) → receive 1 OZZY
  - Claim(spendToken=some_debenture_token, 1) → receive 1 BAR back
  - Net: +1 OZZY. Sell OZZY for PLS.

Constraints:
  1. We must hold the parent token in TGSv8
  2. We must hold or acquire a Debenture=True spendToken for the Claim call
  3. Child token must have DEX liquidity to sell into
  4. Monitor Debenture status every cycle — if published(), the loop locks

TGSv8 functions used:
  mintAndClaim(child, spendToken, amount) → childNet
  batchMintAndClaim(children[], spendTokens[], amounts[]) → results[]
  swapExact(tokenIn, tokenOut, amountIn, minOut, dex) — sell accumulated child
  checkDebenture(token) → bool — live status check before each cycle
  getBestAmountsOut(amountIn, path) — oracle pre-flight for sell leg

File: scripts/Joystick/engines/spine_runner.py
Implements: EngineBase ABC (is_ready, simulate, execute, roi)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from web3 import Web3

from bot.core.config import Config
from bot.core.chain import Chain
from bot.core.wallet import Wallet
from bot.core.executor import Executor
from bot.core.gas_guard import GasGuard
from bot.engines.base import EngineBase

log = logging.getLogger("joystick.e6_spine")

# ─── ABI fragments ────────────────────────────────────────────────────────────

TGSV8_SPINE_ABI = [
    # mintAndClaim — single atomic iteration
    {
        "inputs": [
            {"name": "child",      "type": "address"},
            {"name": "spendToken", "type": "address"},
            {"name": "amount",     "type": "uint256"},
        ],
        "name": "mintAndClaim",
        "outputs": [{"name": "childNet", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # batchMintAndClaim — N iterations in one TX (maxBatch=20 by default)
    {
        "inputs": [
            {"name": "children_",   "type": "address[]"},
            {"name": "spendTokens", "type": "address[]"},
            {"name": "amounts",     "type": "uint256[]"},
        ],
        "name": "batchMintAndClaim",
        "outputs": [{"name": "results", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # checkDebenture — live status (call before every cycle!)
    {
        "inputs":  [{"name": "token", "type": "address"}],
        "name":    "checkDebenture",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    # swapExact — sell accumulated child tokens → WPLS
    {
        "inputs": [
            {"name": "tokenIn",  "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "minOut",   "type": "uint256"},
            {"name": "dex",      "type": "uint8"},
        ],
        "name": "swapExact",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # getBestAmountsOut — oracle pre-flight
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path",     "type": "address[]"},
        ],
        "name": "getBestAmountsOut",
        "outputs": [
            {"name": "v1Out",   "type": "uint256"},
            {"name": "v2Out",   "type": "uint256"},
            {"name": "best",    "type": "uint8"},
            {"name": "bestOut", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    # bal — TGSv8 internal balance
    {
        "inputs":  [{"name": "token", "type": "address"}],
        "name":    "bal",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    # deposit — seed TGSv8 with parent tokens
    {
        "inputs": [
            {"name": "token",  "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# ─── DEX enum (matches TGSv8 Solidity) ────────────────────────────────────────
DEX_V1   = 0
DEX_V2   = 1
DEX_BEST = 2

# ─── Constants ────────────────────────────────────────────────────────────────
TGSV8_ADDR  = Web3.to_checksum_address(os.getenv("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32"))
WPLS_ADDR   = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# From v2_federal_tokens.json — the one known Debenture=True candidate
OZZY_ADDR   = Web3.to_checksum_address("0x7AC2D2B02Af38a61db1CeD0AeF9CF68B79bD72e1")
BAR_ADDR    = Web3.to_checksum_address("0xaAE18Cd4BF1DaDb7A30B9c3D2d7d3A6D2bA91f4")

SLIP_BPS           = 150     # 1.5% slippage on sell leg
BATCH_ITERATIONS   = 20      # iterations per batchMintAndClaim TX (TGSv8 maxBatch default)
MIN_SELL_THRESHOLD = 500     # accumulate at least 500 child tokens before selling
RECON_CACHE_TTL    = 1800    # 30-minute cache on recon data


@dataclass
class Spine:
    """
    One active spine: a child token + spendToken pair that can loop.

    child:       the token we're minting (e.g., OZZY)
    parent:      the token we spend to mint and get back from Claim (e.g., BAR)
    spend_token: the Debenture=True token burned in the Claim call
    pls_per_child: DEX price for selling child tokens
    decimals:    child token decimals
    active:      False once Debenture flips (token published)
    """
    label:          str
    child:          str
    parent:         str
    spend_token:    str           # must have Debenture=True
    pls_per_child:  float         # PLS per 1 whole child token (float)
    decimals:       int = 18
    active:         bool = True
    last_debenture_check: float = 0.0


class SpineRunnerEngine(EngineBase):
    """
    Engine 6 — Spine Runner.

    Reads recon_results.json + v2_federal_tokens.json to find active spines.
    Runs batchMintAndClaim loops on active spines, then sells accumulated
    child tokens via swapExact → WPLS.

    Key invariant: verify checkDebenture() BEFORE every TX. If a spine's
    Debenture has flipped to False (it got published), remove from active list
    immediately — the Claim call will revert if we try.
    """

    ENGINE_ID   = 6
    ENGINE_NAME = "SpineRunner"

    def __init__(self, cfg: Config, chain: Chain, wallet: Wallet,
                 executor: Executor, gas_guard: GasGuard):
        self.cfg       = cfg
        self.chain     = chain
        self.wallet    = wallet
        self.executor  = executor
        self.gas_guard = gas_guard

        self._tgsv8 = chain.w3.eth.contract(address=TGSV8_ADDR, abi=TGSV8_SPINE_ABI)
        self._spines: list[Spine] = []
        self._last_load = 0.0
        self._consecutive_failures = 0
        self._total_pls_earned = 0

        self._recon_path   = os.path.join(os.path.dirname(__file__), "..", "data", "recon_results.json")
        self._v2fed_path   = os.path.join(os.path.dirname(__file__), "..", "data", "v2_federal_tokens.json")

    # ── EngineBase interface ───────────────────────────────────────────────

    def is_ready(self) -> bool:
        if self._consecutive_failures >= 3:
            log.warning("E6: circuit breaker tripped")
            return False

        # Load spines once
        self._refresh_spines()

        active = [s for s in self._spines if s.active]
        if not active:
            log.debug("E6: no active spines found")
            return False

        # Need parent tokens in TGSv8 to seed the loop
        for spine in active:
            parent_bal = self._tgsv8_bal(spine.parent)
            if parent_bal > 0:
                return True

        log.debug("E6: active spines exist but no parent token balance in TGSv8")
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

        # Live debenture check before committing
        if not self._live_debenture_check(best):
            best.active = False
            return (0, 0)

        # Expected child tokens from BATCH_ITERATIONS iterations
        amount_per_iter = self._size_iteration(best)
        if amount_per_iter == 0:
            return (0, 0)

        child_out     = BATCH_ITERATIONS * amount_per_iter
        pls_expected  = int(child_out * best.pls_per_child)   # already in wei via oracle

        # Gas: ~300k per batchMintAndClaim, ~150k for the sell swap
        gas_price     = self.chain.get_gas_price()
        gas_est       = (300_000 + 150_000) * gas_price
        gas_cost      = int(gas_est * 1.3)

        if pls_expected <= gas_cost:
            return (0, 0)

        return (pls_expected - gas_cost, gas_cost)

    def execute(self) -> dict:
        """
        1. Pick best spine
        2. Verify Debenture status (live call)
        3. batchMintAndClaim — N iterations
        4. swapExact child tokens → WPLS (if accumulated enough)
        """
        self._refresh_spines()
        spine = self._pick_best_spine()
        if not spine:
            return {"success": False, "reason": "no active spines"}

        if not self.gas_guard.check():
            return {"success": False, "reason": "gas guard: PLS floor breached"}

        gas_price = self.chain.get_gas_price()
        if gas_price > self.cfg.gas_ceiling_gwei * 10**9:
            return {"success": False, "reason": f"gas too high: {gas_price/1e9:.0f} Gwei"}

        # Live Debenture gate — non-negotiable
        if not self._live_debenture_check(spine):
            spine.active = False
            log.warning(f"E6: {spine.label} Debenture flipped False — deactivating spine")
            return {"success": False, "reason": f"{spine.label} debenture is now False"}

        try:
            result = self._run_spine_cycle(spine, gas_price)
            if result.get("success"):
                self._consecutive_failures = 0
                self._total_pls_earned += result.get("pls_earned", 0)
            else:
                self._consecutive_failures += 1
            return result
        except Exception as e:
            log.error(f"E6 execute error: {e}")
            self._consecutive_failures += 1
            return {"success": False, "reason": str(e)}

    def roi(self) -> float:
        profit, gas = self.simulate()
        if gas == 0:
            return 0.0
        return profit / gas

    # ── Internal mechanics ────────────────────────────────────────────────

    def _refresh_spines(self):
        """Load/discover spines from recon data. Respects TTL."""
        now = time.time()
        if now - self._last_load < RECON_CACHE_TTL and self._spines:
            return

        spines = []

        # ── Load V2 Federal known targets ─────────────────────────────────
        if os.path.exists(self._v2fed_path):
            try:
                with open(self._v2fed_path) as f:
                    v2data = json.load(f)
                for tok in v2data.get("tokens", []):
                    if tok.get("debenture") is not True:
                        continue
                    addr     = tok["address"]
                    label    = tok.get("symbol", addr[:8])
                    pls_ptok = tok.get("pls_per_token", 0.0)
                    if pls_ptok == 0:
                        log.debug(f"E6: skipping {label} — no DEX price (no liquidity)")
                        continue
                    # We need the parent address. Try recon_results.
                    parent = self._get_parent_from_recon(addr)
                    if not parent:
                        log.debug(f"E6: skipping {label} — parent address unknown")
                        continue
                    # The spendToken for Claim must ALSO be Debenture=True.
                    # For now, the same token serves as both child AND spendToken
                    # (the pattern: mint child, claim using child's sibling debenture token).
                    # If we have no separate spend token, we use the child itself as spendToken —
                    # this works when the contract allows self-referential Claim.
                    # Full resolution: recon tells us which tokens share a parent AND are unpublished.
                    spend_token = self._find_spend_token(addr, parent)
                    if not spend_token:
                        log.debug(f"E6: skipping {label} — no valid spend token found")
                        continue

                    spines.append(Spine(
                        label         = label,
                        child         = Web3.to_checksum_address(addr),
                        parent        = Web3.to_checksum_address(parent),
                        spend_token   = Web3.to_checksum_address(spend_token),
                        pls_per_child = pls_ptok * 1e18,   # convert to wei scale
                        active        = True,
                    ))
            except Exception as e:
                log.warning(f"E6: error loading v2_federal_tokens.json: {e}")

        # ── Fallback: seed known OZZY spine if recon found it ─────────────
        if not spines:
            log.info("E6: using hardcoded OZZY fallback spine (recon pending)")
            # OZZY confirmed Debenture=True from prior session.
            # BAR is OZZY's parent. OZZY has no DEX price yet (pls=0).
            # This spine will not pass the simulate() profitability check until
            # OZZY gets liquidity — Engine 7 (Web Weaver) is the unlock.
            spines.append(Spine(
                label         = "OZZY",
                child         = OZZY_ADDR,
                parent        = BAR_ADDR,
                spend_token   = OZZY_ADDR,    # TBD — needs proper debenture spendToken
                pls_per_child = 0,             # blocked until liquidity created
                active        = False,         # inactive until we have a DEX price
            ))

        self._spines   = spines
        self._last_load = now
        log.info(f"E6: loaded {len(spines)} spines ({sum(1 for s in spines if s.active)} active)")

    def _get_parent_from_recon(self, child_addr: str) -> Optional[str]:
        """Look up parent address from recon_results.json."""
        if not os.path.exists(self._recon_path):
            return None
        try:
            with open(self._recon_path) as f:
                recon = json.load(f)
            entry = recon.get("results", {}).get(child_addr.lower(), {})
            parent = entry.get("chain_data", {}).get("parent")
            if parent and parent != "0x" + "0" * 40:
                return parent
        except Exception:
            pass
        return None

    def _find_spend_token(self, child_addr: str, parent_addr: str) -> Optional[str]:
        """
        Find a valid Debenture=True token to use as the spendToken in the Claim call.

        Strategy:
        1. Check if any OTHER child of the same parent also has Debenture=True
        2. That sibling can serve as the burn token in the Claim call
        3. If none found, check if the child itself allows self-referential Claim

        This is the hardest part of the spine discovery problem.
        The recon data has Debenture status — we walk it here.
        """
        if not os.path.exists(self._recon_path):
            return None
        try:
            with open(self._recon_path) as f:
                recon = json.load(f)
            # Find siblings: same parent, Debenture=True, not the child itself
            for addr, entry in recon.get("results", {}).items():
                cd = entry.get("chain_data", {})
                if (cd.get("parent", "").lower() == parent_addr.lower()
                        and cd.get("debenture") is True
                        and addr.lower() != child_addr.lower()):
                    return addr
        except Exception:
            pass
        # If no sibling found, fall back to using child as spend token
        # (some V2 contracts allow this; will revert at sim time if not)
        return child_addr

    def _pick_best_spine(self) -> Optional[Spine]:
        """Return the highest-ROI active spine with parent balance in TGSv8."""
        candidates = []
        for spine in self._spines:
            if not spine.active:
                continue
            if spine.pls_per_child == 0:
                continue
            parent_bal = self._tgsv8_bal(spine.parent)
            if parent_bal == 0:
                continue
            candidates.append((spine, parent_bal))

        if not candidates:
            return None

        # Pick highest pls_per_child (proxy for ROI per iteration)
        candidates.sort(key=lambda x: x[0].pls_per_child, reverse=True)
        return candidates[0][0]

    def _size_iteration(self, spine: Spine) -> int:
        """
        How many parent tokens to commit per batchMintAndClaim iteration.
        Capped at 1/10 of TGSv8's parent balance (don't drain in one TX).
        """
        parent_bal = self._tgsv8_bal(spine.parent)
        if parent_bal == 0:
            return 0
        # Use 10% of balance per iteration, min 1 token, max 1000 tokens
        per_iter = max(10**spine.decimals, parent_bal // 10)
        return min(per_iter, 1000 * 10**spine.decimals)

    def _live_debenture_check(self, spine: Spine) -> bool:
        """
        Call TGSv8.checkDebenture() on-chain (eth_call, free).
        Cache result per spine for 60 seconds to avoid hammering RPC.
        """
        now = time.time()
        if now - spine.last_debenture_check < 60:
            return spine.active    # use cached status

        try:
            result = self._tgsv8.functions.checkDebenture(
                Web3.to_checksum_address(spine.child)
            ).call()
            spine.last_debenture_check = now
            if not result:
                log.warning(f"E6: {spine.label} debenture=False — spine is dead")
                spine.active = False
            return result
        except Exception as e:
            log.warning(f"E6: debenture check error for {spine.label}: {e}")
            return False

    def _run_spine_cycle(self, spine: Spine, gas_price: int) -> dict:
        """
        Full execution cycle for one spine:
        1. Build arrays for batchMintAndClaim (BATCH_ITERATIONS repetitions)
        2. Simulate via eth_call
        3. estimate_gas → abort if fails
        4. Send TX
        5. If enough child tokens accumulated, sell → WPLS
        """
        amount = self._size_iteration(spine)
        if amount == 0:
            return {"success": False, "reason": "iteration amount is zero"}

        children    = [spine.child]       * BATCH_ITERATIONS
        spend_toks  = [spine.spend_token] * BATCH_ITERATIONS
        amounts     = [amount]            * BATCH_ITERATIONS

        # ── eth_call simulation ───────────────────────────────────────────
        try:
            sim_result = self._tgsv8.functions.batchMintAndClaim(
                children, spend_toks, amounts
            ).call({"from": self.wallet.address})
            log.info(f"E6 sim OK — {spine.label}: {sum(sim_result)/10**spine.decimals:.4f} child tokens per batch")
        except Exception as e:
            log.warning(f"E6 batchMintAndClaim sim FAIL for {spine.label}: {e}")
            return {"success": False, "reason": f"sim failed: {e}"}

        # ── estimate_gas — abort on failure ───────────────────────────────
        try:
            gas_est = self._tgsv8.functions.batchMintAndClaim(
                children, spend_toks, amounts
            ).estimate_gas({"from": self.wallet.address})
        except Exception as e:
            log.warning(f"E6 gas estimate FAIL (aborting): {e}")
            return {"success": False, "reason": f"gas estimate failed: {e}"}

        gas_limit = int(gas_est * 1.3)

        # ── send TX ───────────────────────────────────────────────────────
        nonce = self.wallet.get_nonce()
        tx = self._tgsv8.functions.batchMintAndClaim(
            children, spend_toks, amounts
        ).build_transaction({
            "from":     self.wallet.address,
            "gas":      gas_limit,
            "gasPrice": gas_price,
            "nonce":    nonce,
            "chainId":  369,
        })

        receipt = self.executor.send_and_wait(tx)
        if not receipt or receipt.get("status") != 1:
            return {"success": False, "reason": "TX reverted", "receipt": receipt}

        child_accumulated = sum(sim_result)
        log.info(f"E6: minted {child_accumulated/10**spine.decimals:.4f} {spine.label}")

        # ── Sell leg: swap child → WPLS if above threshold ────────────────
        child_bal = self._tgsv8_bal(spine.child)
        pls_result = {}

        if child_bal >= MIN_SELL_THRESHOLD * 10**spine.decimals:
            pls_result = self._sell_child_tokens(spine, child_bal, gas_price)

        pls_earned = pls_result.get("pls_out", 0)
        return {
            "success":     True,
            "tx_hash":     receipt["transactionHash"].hex(),
            "gas_used":    receipt["gasUsed"],
            "child_minted":child_accumulated,
            "pls_earned":  pls_earned,
            "sell_result": pls_result,
        }

    def _sell_child_tokens(self, spine: Spine, amount: int, gas_price: int) -> dict:
        """
        Swap accumulated child tokens → WPLS via TGSv8.swapExact().
        Uses getBestAmountsOut pre-flight to set minOut with slippage.
        """
        try:
            path = [Web3.to_checksum_address(spine.child), WPLS_ADDR]
            v1, v2, best_dex, best_out = self._tgsv8.functions.getBestAmountsOut(
                amount, path
            ).call()
            if best_out == 0:
                return {"success": False, "reason": "no DEX output for child token"}

            min_out = int(best_out * (10000 - SLIP_BPS) / 10000)
        except Exception as e:
            log.warning(f"E6 sell pre-flight failed: {e}")
            return {"success": False, "reason": str(e)}

        # Simulate sell
        try:
            self._tgsv8.functions.swapExact(
                Web3.to_checksum_address(spine.child), WPLS_ADDR,
                amount, min_out, DEX_BEST
            ).call({"from": self.wallet.address})
        except Exception as e:
            log.warning(f"E6 sell sim failed: {e}")
            return {"success": False, "reason": f"sell sim failed: {e}"}

        try:
            gas_est = self._tgsv8.functions.swapExact(
                Web3.to_checksum_address(spine.child), WPLS_ADDR,
                amount, min_out, DEX_BEST
            ).estimate_gas({"from": self.wallet.address})
        except Exception as e:
            return {"success": False, "reason": f"sell gas estimate failed: {e}"}

        nonce = self.wallet.get_nonce()
        tx = self._tgsv8.functions.swapExact(
            Web3.to_checksum_address(spine.child), WPLS_ADDR,
            amount, min_out, DEX_BEST
        ).build_transaction({
            "from":     self.wallet.address,
            "gas":      int(gas_est * 1.3),
            "gasPrice": gas_price,
            "nonce":    nonce,
            "chainId":  369,
        })

        receipt = self.executor.send_and_wait(tx)
        if receipt and receipt.get("status") == 1:
            log.info(f"E6 sell TX confirmed — ~{min_out/1e18:.2f} WPLS received")
            return {"success": True, "pls_out": min_out, "tx_hash": receipt["transactionHash"].hex()}
        return {"success": False, "reason": "sell TX reverted"}

    def _tgsv8_bal(self, token_addr: str) -> int:
        try:
            return self._tgsv8.functions.bal(
                Web3.to_checksum_address(token_addr)
            ).call()
        except Exception:
            return 0

    def status(self) -> dict:
        self._refresh_spines()
        active = [s for s in self._spines if s.active]
        return {
            "engine":       self.ENGINE_NAME,
            "ready":        self.is_ready(),
            "spines_total": len(self._spines),
            "spines_active":len(active),
            "active_labels":[s.label for s in active],
            "total_pls_earned": f"{self._total_pls_earned/1e18:,.2f}",
            "failures":     self._consecutive_failures,
        }
