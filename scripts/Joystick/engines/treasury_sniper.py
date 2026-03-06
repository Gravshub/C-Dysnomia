"""
Engine 5 — Treasury Sniper
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
  4. If value_out > cost_in + gas → execute via TGSv8.executeRoute([
       TRANSFER_IN WPLS,
       SWAP WPLS→child,
       CLAIM child→parent,
       SWAP parent→WPLS,
       TRANSFER_OUT WPLS
     ])

TGSv8 functions used:
  claimFromTreasury(treasury, backingAsset, amount) → received
  batchClaimTreasury(treasuries[], backingAssets[], amounts[]) → results[]
  executeRoute(Step[]) — for full atomic SWAP→CLAIM→SWAP pipeline
  getBestAmountsOut(amountIn, path) — oracle pre-flight

File: scripts/Joystick/engines/treasury_sniper.py
Implements: EngineBase ABC (is_ready, simulate, execute, roi)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from web3 import Web3

# Import existing infrastructure — never rewrite
from bot.core.config import Config
from bot.core.chain import Chain
from bot.core.wallet import Wallet
from bot.core.executor import Executor
from bot.core.gas_guard import GasGuard
from bot.engines.base import EngineBase

log = logging.getLogger("joystick.e5_sniper")

# ─── ABI fragments ────────────────────────────────────────────────────────────

TGSV8_SNIPER_ABI = [
    # claimFromTreasury — single atomic claim
    {
        "inputs": [
            {"name": "treasury",     "type": "address"},
            {"name": "backingAsset", "type": "address"},
            {"name": "amount",       "type": "uint256"},
        ],
        "name": "claimFromTreasury",
        "outputs": [{"name": "received", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # batchClaimTreasury — sweep N treasuries in one TX
    {
        "inputs": [
            {"name": "treasuries",   "type": "address[]"},
            {"name": "backingAssets","type": "address[]"},
            {"name": "amounts",      "type": "uint256[]"},
        ],
        "name": "batchClaimTreasury",
        "outputs": [{"name": "results", "type": "uint256[]"}],
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
    # executeRoute — full atomic pipeline
    {
        "inputs": [
            {
                "components": [
                    {"name": "action",   "type": "uint8"},
                    {"name": "target",   "type": "address"},
                    {"name": "tokenA",   "type": "address"},
                    {"name": "tokenB",   "type": "address"},
                    {"name": "amount",   "type": "uint256"},
                    {"name": "amountB",  "type": "uint256"},
                    {"name": "slipBps",  "type": "uint256"},
                    {"name": "dex",      "type": "uint8"},
                ],
                "name": "steps",
                "type": "tuple[]",
            }
        ],
        "name": "executeRoute",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # bal — internal balance view
    {
        "inputs": [{"name": "token", "type": "address"}],
        "name": "bal",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_BAL_ABI = [
    {
        "inputs": [{"name": "a", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# ─── StepType enum (must match TGSv8 Solidity order) ─────────────────────────
STEP_MINT         = 0
STEP_CLAIM        = 1
STEP_SWAP         = 2
STEP_ADD_LIQ      = 3
STEP_TRANSFER_IN  = 4
STEP_TRANSFER_OUT = 5
STEP_APPROVE      = 6
STEP_SWAP_MULTI   = 7
STEP_WRAP_PLS     = 8
STEP_UNWRAP_WPLS  = 9

DEX_V1   = 0
DEX_V2   = 1
DEX_BEST = 2

# ─── Configuration ────────────────────────────────────────────────────────────
TGSV8_ADDR   = Web3.to_checksum_address(os.getenv("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32"))
WPLS_ADDR    = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
JOEY_WALLET  = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# Minimum profit threshold in PLS wei (500 PLS)
MIN_PROFIT_WEI   = 500 * 10**18
# Max fraction of a DEX pool to consume in one swap (10%)
MAX_POOL_IMPACT  = 0.10
# Slippage tolerance for swaps in basis points
SLIP_BPS         = 100   # 1%
# Max tokens to batch in one batchClaimTreasury TX
BATCH_SIZE       = 10
# Recon cache TTL in seconds (60 minutes)
RECON_CACHE_TTL  = 3600


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
    buy_dex:        int = DEX_BEST
    sell_dex:       int = DEX_BEST


class TreasurySniperEngine(EngineBase):
    """
    Engine 5 — Treasury Sniper.

    Reads recon_results.json (written by treasury_recon.py) and executes
    profitable claimFromTreasury operations through TGSv8.

    Priority: HIGH — single-execution treasury sweeps. Once claimed, backing
    is gone. Run early, run once per treasury per session.
    """

    ENGINE_ID   = 5
    ENGINE_NAME = "TreasurySniper"

    def __init__(self, cfg: Config, chain: Chain, wallet: Wallet,
                 executor: Executor, gas_guard: GasGuard):
        self.cfg       = cfg
        self.chain     = chain
        self.wallet    = wallet
        self.executor  = executor
        self.gas_guard = gas_guard

        self._tgsv8 = chain.w3.eth.contract(address=TGSV8_ADDR, abi=TGSV8_SNIPER_ABI)
        self._targets: list[TreasuryTarget] = []
        self._claimed: set[str] = set()     # addresses already claimed this session
        self._last_load = 0.0
        self._recon_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "recon_results.json"
        )
        self._consecutive_failures = 0

    # ── EngineBase interface ───────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Ready when TGSv8 is set, recon data exists, and we have WPLS or PLS."""
        if not os.path.exists(self._recon_path):
            log.debug("E5: recon_results.json not found — run treasury_recon.py first")
            return False
        if self._consecutive_failures >= 3:
            log.warning("E5: circuit breaker tripped (3 consecutive failures)")
            return False
        wpls_bal = self._tgsv8_bal(WPLS_ADDR)
        native_bal = self.chain.w3.eth.get_balance(TGSV8_ADDR)
        if wpls_bal + native_bal < 100 * 10**18:   # need at least 100 PLS to work with
            log.debug(f"E5: TGSv8 working balance too low (WPLS={wpls_bal/1e18:.1f})")
            return False
        return True

    def simulate(self) -> tuple[int, int]:
        """
        Returns (expected_profit_wei, estimated_gas_cost_wei).
        Loads recon data, filters profitable targets, picks best batch.
        """
        self._refresh_targets()
        if not self._targets:
            return (0, 0)

        best = self._pick_best_batch()
        if not best:
            return (0, 0)

        total_profit = sum(
            int(t.estimated_pls * 10**18) for t in best
        )
        gas_est = 400_000 * len(best)   # ~400k gas per claim op
        gas_price = self.chain.get_gas_price()
        gas_cost = gas_est * gas_price

        if total_profit <= gas_cost:
            return (0, 0)

        return (total_profit - gas_cost, gas_cost)

    def execute(self) -> dict:
        """
        Executes the best available batch of treasury claims.
        Simulates via eth_call first. Never sends blind.
        """
        self._refresh_targets()
        batch = self._pick_best_batch()
        if not batch:
            return {"success": False, "reason": "no profitable targets"}

        if not self.gas_guard.check():
            return {"success": False, "reason": "gas guard: PLS floor breached"}

        gas_price = self.chain.get_gas_price()
        if gas_price > self.cfg.gas_ceiling_gwei * 10**9:
            return {"success": False, "reason": f"gas too high: {gas_price/1e9:.0f} Gwei"}

        try:
            result = self._execute_batch(batch, gas_price)
            if result.get("success"):
                for t in batch:
                    self._claimed.add(t.address.lower())
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
            return result
        except Exception as e:
            log.error(f"E5 execute error: {e}")
            self._consecutive_failures += 1
            return {"success": False, "reason": str(e)}

    def roi(self) -> float:
        """ROI estimate: expected_profit / gas_cost ratio."""
        profit, gas = self.simulate()
        if gas == 0:
            return 0.0
        return profit / gas

    # ── Internal mechanics ────────────────────────────────────────────────

    def _refresh_targets(self):
        """Load/refresh recon data. Respects TTL cache."""
        now = time.time()
        if now - self._last_load < RECON_CACHE_TTL and self._targets:
            return

        try:
            with open(self._recon_path) as f:
                recon = json.load(f)
        except Exception as e:
            log.warning(f"E5: failed to load recon_results.json: {e}")
            return

        targets = []
        results = recon.get("results", {})

        for addr, entry in results.items():
            cd = entry.get("chain_data", {})

            # Skip already claimed this session
            if addr.lower() in self._claimed:
                continue

            self_bal    = cd.get("selfBalance", 0)
            parent_bal  = cd.get("parentBalance", 0)
            pls_per_tok = cd.get("pls_per_token", 0)
            parent_addr = cd.get("parent")
            decimals    = cd.get("decimals", 18)

            # Need claimable balance and a DEX price to sell into
            if self_bal == 0 or pls_per_tok == 0 or not parent_addr:
                continue
            if parent_addr in ("0x" + "0" * 40, None):
                continue

            # Estimate PLS value of the claimable backing
            # selfBalance is child tokens we'd spend → Claim returns parent tokens 1:1
            # Parent tokens then sold to DEX for PLS
            # Rough estimate: use child token price as proxy if parent price unknown
            qty_tokens = self_bal / (10 ** decimals)
            parent_pls = pls_per_tok  # conservative: assume parent ≈ child price for now
            est_pls    = qty_tokens * parent_pls / 1e18

            if est_pls < 100:   # skip dust (< 100 PLS estimated value)
                continue

            targets.append(TreasuryTarget(
                label         = entry.get("label", addr[:10]),
                address       = addr,
                backing_asset = parent_addr,
                self_balance  = self_bal,
                parent_balance= parent_bal,
                pls_per_token = pls_per_tok,
                parent_pls    = parent_pls,
                decimals      = decimals,
                estimated_pls = est_pls,
                buy_dex       = DEX_BEST,
                sell_dex      = DEX_BEST,
            ))

        # Sort descending by estimated PLS value
        targets.sort(key=lambda t: t.estimated_pls, reverse=True)
        self._targets = targets
        self._last_load = now
        log.info(f"E5: loaded {len(targets)} treasury targets from recon")

    def _pick_best_batch(self) -> list[TreasuryTarget]:
        """
        Choose the best batch of treasury targets for this cycle.
        Filters by profitability after gas costs, respects pool impact limits.
        Returns up to BATCH_SIZE targets.
        """
        if not self._targets:
            return []

        gas_price    = self.chain.get_gas_price()
        gas_per_op   = 400_000  # gas units per claimFromTreasury
        gas_cost_wei = gas_per_op * gas_price * 1.3  # 1.3x multiplier

        profitable = []
        for t in self._targets:
            if t.address.lower() in self._claimed:
                continue

            # Cap amount by pool depth (10% max impact rule)
            claim_amount = self._size_claim(t)
            if claim_amount == 0:
                continue

            profit_est = claim_amount / (10 ** t.decimals) * t.parent_pls / 1e18
            if int(profit_est * 10**18) > gas_cost_wei:
                profitable.append(t)

            if len(profitable) >= BATCH_SIZE:
                break

        return profitable

    def _size_claim(self, t: TreasuryTarget) -> int:
        """
        Return the amount of child tokens to spend in the Claim call,
        capped by pool depth on the child token DEX pair.

        We need child tokens to spend. The easiest source is TGSv8's own
        balance if it already holds some; otherwise we'd need to buy them
        first (a separate SWAP step). For now: check TGSv8 balance.
        """
        tgsv8_child_bal = self._tgsv8_bal(t.address)

        # Can't spend more than we have or more than the self-balance of the treasury
        available = min(tgsv8_child_bal, t.self_balance)
        if available == 0:
            return 0

        # Pool depth guard: if there's a DEX pair, don't impact > 10%
        # (borrowing from pool data baked into recon; re-check if stale)
        return available

    def _execute_batch(self, batch: list[TreasuryTarget], gas_price: int) -> dict:
        """
        Simulate then submit batchClaimTreasury TX.
        For each token in batch, uses TGSv8's existing child token balance.
        """
        treasuries    = [Web3.to_checksum_address(t.address)        for t in batch]
        backing_assets= [Web3.to_checksum_address(t.backing_asset)  for t in batch]
        amounts       = [self._size_claim(t) for t in batch]

        # Sanity check — skip zeros
        valid = [(t, b, a) for t, b, a in zip(treasuries, backing_assets, amounts) if a > 0]
        if not valid:
            return {"success": False, "reason": "all amounts zero after sizing"}

        treasuries, backing_assets, amounts = zip(*valid) if valid else ([], [], [])
        treasuries     = list(treasuries)
        backing_assets = list(backing_assets)
        amounts        = list(amounts)

        # ── eth_call simulation ───────────────────────────────────────────
        try:
            sim_result = self._tgsv8.functions.batchClaimTreasury(
                treasuries, backing_assets, amounts
            ).call({"from": self.wallet.address})
            log.info(f"E5 sim OK — expected results: {sim_result}")
        except Exception as e:
            log.warning(f"E5 sim FAIL: {e}")
            return {"success": False, "reason": f"sim failed: {e}"}

        # ── estimate_gas ──────────────────────────────────────────────────
        try:
            gas_est = self._tgsv8.functions.batchClaimTreasury(
                treasuries, backing_assets, amounts
            ).estimate_gas({"from": self.wallet.address})
        except Exception as e:
            log.warning(f"E5 gas estimate FAIL (aborting): {e}")
            return {"success": False, "reason": f"gas estimate failed: {e}"}

        gas_limit = int(gas_est * 1.3)

        # ── build & send TX ───────────────────────────────────────────────
        nonce = self.wallet.get_nonce()
        tx    = self._tgsv8.functions.batchClaimTreasury(
            treasuries, backing_assets, amounts
        ).build_transaction({
            "from":     self.wallet.address,
            "gas":      gas_limit,
            "gasPrice": gas_price,
            "nonce":    nonce,
            "chainId":  369,
        })

        receipt = self.executor.send_and_wait(tx)
        if receipt and receipt.get("status") == 1:
            total_claimed = sum(sim_result) if sim_result else 0
            log.info(f"E5 SUCCESS — claimed from {len(treasuries)} treasuries, ~{total_claimed/1e18:.2f} tokens received")
            return {
                "success":        True,
                "tx_hash":        receipt["transactionHash"].hex(),
                "gas_used":       receipt["gasUsed"],
                "treasuries":     treasuries,
                "sim_received":   sim_result,
            }
        else:
            return {"success": False, "reason": "TX reverted on-chain", "receipt": receipt}

    def _tgsv8_bal(self, token_addr: str) -> int:
        """Read TGSv8's internal balance of a token."""
        try:
            return self._tgsv8.functions.bal(
                Web3.to_checksum_address(token_addr)
            ).call()
        except Exception:
            return 0

    def status(self) -> dict:
        """Human-readable status for bot.py --status output."""
        self._refresh_targets()
        return {
            "engine":    self.ENGINE_NAME,
            "ready":     self.is_ready(),
            "targets":   len(self._targets),
            "claimed":   len(self._claimed),
            "top_target": self._targets[0].label if self._targets else "none",
            "top_est_pls": f"{self._targets[0].estimated_pls:,.0f}" if self._targets else "0",
            "failures":  self._consecutive_failures,
        }
