"""
token_factory.py — Engine 5: TGSV7 Token Factory

Uses TGSV7 as on-chain execution substrate for:
  Strategy A — MINT_AND_SELL: mint existing tokens via parent → sell on DEX
  Strategy B — CREATE_AND_PAIR: create new V4 token → add LP (deferred)

Also exports LPStrategy dataclass and optimize_lp_ratio() for use by
the mint test tool script.

is_ready():  TGSV7 deployed, not paused, Joey authorized, MV available
simulate():  Find mintable tokens with profitable DEX arbitrage
execute():   Mint via TGSV7.mintTokens() → swap on DEX → PLS profit
"""
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, AFFECTION, WM, WPLS, TGSV7,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    GAS_PRICE_CEIL, GAS_MULT,
)
from ..core.chain import (
    w3_read, w3_submit, erc20, safe, multicall,
    factory_contract, tgsv7_contract,
    TGSV7_ABI,
)
from ..core.simulator import SimulationFailed

log = logging.getLogger(__name__)

ZERO = "0x" + "0" * 40

# TokenCreated event topic
TOKEN_CREATED_TOPIC = Web3.keccak(
    text="TokenCreated(uint256,address,address,uint256,uint8)"
).hex()


def parse_token_created(receipt) -> str | None:
    """Extract new token address from createV4/createV3 TX receipt."""
    for log_entry in receipt.get("logs", []):
        topics = log_entry.get("topics", [])
        if not topics:
            continue
        t0 = topics[0].hex() if hasattr(topics[0], "hex") else topics[0]
        if t0.lower() == TOKEN_CREATED_TOPIC[2:].lower() and len(topics) >= 3:
            token_hex = topics[2].hex() if hasattr(topics[2], "hex") else topics[2]
            return Web3.to_checksum_address("0x" + token_hex[-40:])
    return None


# ── LP Strategy ──────────────────────────────────────────────────────────────

@dataclass
class LPStrategy:
    """Configurable LP pairing parameters for new token deployment."""
    initial_mint: int           # tokens created in wei
    lp_token_fraction: float    # fraction of minted supply → LP (0.0 to 1.0)
    lp_wpls_amount: int         # WPLS to pair (in wei)
    burn_lp: bool               # True = send LP tokens to 0xdead
    dex: int                    # 0=V1, 1=V2, 2=BEST

    @property
    def lp_token_amount(self) -> int:
        return int(self.initial_mint * self.lp_token_fraction)

    @property
    def held_inventory(self) -> int:
        return self.initial_mint - self.lp_token_amount

    @property
    def implied_price_pls(self) -> float:
        if self.lp_token_amount == 0:
            return 0.0
        return (self.lp_wpls_amount / 1e18) / (self.lp_token_amount / 1e18)

    @property
    def inventory_value_pls(self) -> float:
        return (self.held_inventory / 1e18) * self.implied_price_pls

    def breakeven_report(self, gas_cost_pls: float, mv_cost_pls: float) -> dict:
        total_capital = gas_cost_pls + mv_cost_pls + (self.lp_wpls_amount / 1e18)
        inventory_val = self.inventory_value_pls
        paper_profit = inventory_val - total_capital

        return {
            "implied_price_pls": self.implied_price_pls,
            "lp_tokens": self.lp_token_amount / 1e18,
            "held_tokens": self.held_inventory / 1e18,
            "wpls_locked": self.lp_wpls_amount / 1e18,
            "total_capital_pls": total_capital,
            "inventory_value_pls": inventory_val,
            "paper_profit_pls": paper_profit,
            "profitable": paper_profit > 0,
            "roi_pct": (paper_profit / total_capital * 100) if total_capital > 0 else 0,
        }


def optimize_lp_ratio(
    initial_mint: int,
    available_wpls: int,
    gas_cost_pls: float,
    mv_cost_pls: float,
) -> list[dict]:
    """
    Evaluate multiple LP ratio scenarios and rank by ROI.
    Pure math — no eth_calls, no gas.
    """
    scenarios = []
    fractions = [0.01, 0.05, 0.10, 0.20, 0.50]
    wpls_amounts = [10, 50, 100, 500]

    for frac in fractions:
        for wpls in wpls_amounts:
            if wpls > available_wpls / 1e18:
                continue

            strategy = LPStrategy(
                initial_mint=initial_mint,
                lp_token_fraction=frac,
                lp_wpls_amount=int(wpls * 1e18),
                burn_lp=False,
                dex=2,
            )
            report = strategy.breakeven_report(gas_cost_pls, mv_cost_pls)
            report["fraction"] = frac
            report["wpls_input"] = wpls
            scenarios.append(report)

    scenarios.sort(key=lambda s: s["roi_pct"], reverse=True)
    return scenarios


def print_ratio_analysis(scenarios: list[dict]):
    """Pretty-print the ratio optimization results."""
    print("=" * 80)
    print("LP RATIO ANALYSIS")
    print("=" * 80)
    print(f"{'Frac':>6} {'WPLS':>6} {'Price':>10} {'LP Tkn':>10} "
          f"{'Held':>10} {'InvVal':>10} {'Capital':>10} {'P/L':>10} {'ROI':>8}")
    print("-" * 80)
    for s in scenarios[:15]:
        marker = "+" if s["profitable"] else "-"
        print(f"{s['fraction']:>5.0%} {s['wpls_input']:>6.0f} "
              f"{s['implied_price_pls']:>10.4f} {s['lp_tokens']:>10.1f} "
              f"{s['held_tokens']:>10.1f} {s['inventory_value_pls']:>10.2f} "
              f"{s['total_capital_pls']:>10.2f} {s['paper_profit_pls']:>+10.2f} "
              f"{s['roi_pct']:>7.1f}% {marker}")
    print("=" * 80)
    if scenarios and scenarios[0]["profitable"]:
        best = scenarios[0]
        print(f"\n  BEST: {best['fraction']:.0%} to LP, {best['wpls_input']:.0f} WPLS")
        print(f"  Price: {best['implied_price_pls']:.4f} PLS/token")
        print(f"  Inventory: {best['held_tokens']:.0f} tokens worth {best['inventory_value_pls']:.2f} PLS")
        print(f"  ROI: {best['roi_pct']:.1f}%")
    else:
        print("\n  No profitable scenario found at current parameters.")


# ── Token Factory Engine ─────────────────────────────────────────────────────

class TokenFactoryEngine(EngineBase):
    """
    Engine 5: TGSV7 Token Factory — mint tokens and sell on DEX.

    Strategy A (MINT_AND_SELL):
      1. Find tokens where parent=AFFECTION and DEX pair exists
      2. If DEX price > mint cost + gas → profitable
      3. mintTokens(child, amount) on TGSV7
      4. swapExact(child, WPLS, amount, minOut, bestDex) on TGSV7
      5. Withdraw WPLS profit
    """
    name = "TokenFactory"
    MAX_FAILURES = 3
    DISABLE_SECS = 600

    def __init__(self):
        super().__init__()
        self._tgsv7 = None
        self._tgsv7_submit = None
        self._cached_target = None
        self._cache_time = 0
        self._cache_ttl = 300  # 5 minute target cache

    def _get_tgsv7(self, for_submit: bool = False):
        """Lazy-load TGSV7 contract."""
        if not TGSV7:
            return None
        if for_submit:
            if self._tgsv7_submit is None:
                self._tgsv7_submit = tgsv7_contract(w3=w3_submit)
            return self._tgsv7_submit
        if self._tgsv7 is None:
            self._tgsv7 = tgsv7_contract()
        return self._tgsv7

    def is_ready(self) -> bool:
        if not TGSV7:
            log.debug("TokenFactory: TGSV7_ADDRESS not set")
            return False

        tgsv7 = self._get_tgsv7()
        if tgsv7 is None:
            return False

        try:
            paused = safe(tgsv7, "paused")
            if paused:
                log.debug("TokenFactory: TGSV7 is paused")
                return False

            authorized = safe(tgsv7, "authorized", JOEY_WALLET)
            if not authorized:
                log.debug("TokenFactory: Joey not authorized")
                return False

            # Check TGSV7 has AFFECTION or Joey EOA has AFFECTION to deposit
            aff_in_tgsv7 = safe(tgsv7, "bal", AFFECTION) or 0
            aff_in_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
            if aff_in_tgsv7 == 0 and aff_in_joey == 0:
                log.debug("TokenFactory: No AFFECTION available")
                return False

            return True
        except Exception as exc:
            log.debug("TokenFactory is_ready error: %s", exc)
            return False

    def _find_mint_target(self) -> dict | None:
        """
        Find the most profitable token to mint via TGSV7.
        Returns dict with keys: child, amount, expected_out, gas_cost, net_profit
        or None if nothing profitable.
        """
        # Use cached target if fresh
        if self._cached_target and (time.time() - self._cache_time) < self._cache_ttl:
            return self._cached_target

        tgsv7 = self._get_tgsv7()
        if tgsv7 is None:
            return None

        # Check registry for known tokens
        reg_len = safe(tgsv7, "registryLen") or 0
        if reg_len == 0:
            log.debug("TokenFactory: Empty registry — no tokens to mint")
            return None

        # Get children of AFFECTION (tokens mintable with AFFECTION as parent)
        children = safe(tgsv7, "getChildren", AFFECTION)
        if not children:
            log.debug("TokenFactory: No AFFECTION children found")
            return None

        gas_price = w3_read.eth.gas_price
        if gas_price > GAS_PRICE_CEIL:
            return None

        best = None
        mint_amount = int(1e18)  # 1 AFFECTION

        v1_factory = factory_contract(PULSEX_V1_FACTORY)
        v2_factory = factory_contract(PULSEX_V2_FACTORY)

        for child in children[:50]:  # Cap scan to 50 tokens
            if child == ZERO:
                continue

            # Check if mintable
            debenture = safe(tgsv7, "checkDebenture", child)
            if not debenture:
                continue

            # Check DEX pair exists
            v1_pair = safe(v1_factory, "getPair", child, WPLS)
            v2_pair = safe(v2_factory, "getPair", child, WPLS)
            if (not v1_pair or v1_pair == ZERO) and (not v2_pair or v2_pair == ZERO):
                continue

            # Get best DEX output
            try:
                result = tgsv7.functions.getBestAmountsOut(
                    mint_amount, [child, WPLS]
                ).call()
                v1_out, v2_out, best_dex, best_out = result
            except Exception:
                continue

            if best_out == 0:
                continue

            # Estimate gas for mint + swap
            try:
                mint_gas = tgsv7.functions.mintTokens(child, mint_amount).estimate_gas(
                    {"from": JOEY_WALLET}
                )
                swap_gas = tgsv7.functions.swapExact(
                    child, WPLS, mint_amount, 0, best_dex
                ).estimate_gas({"from": JOEY_WALLET})
            except Exception:
                continue

            total_gas = int((mint_gas + swap_gas) * GAS_MULT)
            gas_cost_wei = total_gas * gas_price

            # Net profit = DEX output - gas cost - AFFECTION cost (valued at DEX rate)
            # For simplicity, assume AFFECTION cost ~ gas cost equivalent
            net = best_out - gas_cost_wei
            if net <= 0:
                continue

            candidate = {
                "child": child,
                "amount": mint_amount,
                "expected_out": best_out,
                "gas_cost": gas_cost_wei,
                "net_profit": net,
                "best_dex": best_dex,
                "mint_gas": mint_gas,
                "swap_gas": swap_gas,
            }

            if best is None or net > best["net_profit"]:
                best = candidate

        self._cached_target = best
        self._cache_time = time.time()
        return best

    def simulate(self) -> tuple[int, int]:
        target = self._find_mint_target()
        if target is None:
            raise SimulationFailed("TokenFactory: No profitable mint target found")

        log.info(
            "TokenFactory target: %s net=%.4f PLS",
            target["child"][:10], target["net_profit"] / 1e18,
        )
        return target["expected_out"], target["gas_cost"]

    def execute(self, dry_run: bool = False) -> EngineResult:
        target = self._find_mint_target()
        if target is None:
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                notes="No profitable target",
            )

        if dry_run:
            log.info(
                "[dry-run] TokenFactory: would mint %s, net %.4f PLS",
                target["child"][:10], target["net_profit"] / 1e18,
            )
            return EngineResult(
                success=True,
                profit_wei=target["expected_out"],
                gas_wei=target["gas_cost"],
                notes=f"dry-run: {target['child'][:10]}",
            )

        tgsv7 = self._get_tgsv7(for_submit=True)
        if tgsv7 is None:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes="TGSV7 unavailable")

        tx_hashes = []
        total_gas = 0

        try:
            # Ensure TGSV7 has AFFECTION
            aff_in_tgsv7 = safe(self._get_tgsv7(), "bal", AFFECTION) or 0
            if aff_in_tgsv7 < target["amount"]:
                from ..core.executor import approve_if_needed
                aff_submit = w3_submit.eth.contract(
                    address=Web3.to_checksum_address(AFFECTION),
                    abi=erc20(AFFECTION).abi,
                )
                approve_if_needed(
                    aff_submit, TGSV7, target["amount"],
                    "AFFECTION → TGSV7",
                )
                from ..core.executor import send_tx as _send_tx
                dep_receipt = _send_tx(
                    tgsv7.functions.deposit(AFFECTION, target["amount"]),
                    "Deposit AFFECTION into TGSV7",
                )
                if dep_receipt:
                    tx_hashes.append(f"0x{dep_receipt['transactionHash'].hex()}")
                    total_gas += dep_receipt["gasUsed"]

            # Mint tokens
            from ..core.executor import send_tx as _send_tx
            mint_receipt = _send_tx(
                tgsv7.functions.mintTokens(target["child"], target["amount"]),
                f"TGSV7.mintTokens({target['child'][:10]})",
            )
            if mint_receipt:
                tx_hashes.append(f"0x{mint_receipt['transactionHash'].hex()}")
                total_gas += mint_receipt["gasUsed"]

            # Swap to WPLS
            min_out = int(target["expected_out"] * 0.95)  # 5% slippage tolerance
            swap_receipt = _send_tx(
                tgsv7.functions.swapExact(
                    target["child"], WPLS, target["amount"],
                    min_out, target["best_dex"]
                ),
                f"TGSV7.swapExact({target['child'][:10]} → WPLS)",
            )
            if swap_receipt:
                tx_hashes.append(f"0x{swap_receipt['transactionHash'].hex()}")
                total_gas += swap_receipt["gasUsed"]

            gas_price = w3_submit.eth.gas_price
            gas_cost_wei = total_gas * gas_price

            return EngineResult(
                success=True,
                profit_wei=target["expected_out"],
                gas_wei=gas_cost_wei,
                tx_hashes=tx_hashes,
                notes=f"Minted+swapped {target['child'][:10]}",
            )

        except Exception as exc:
            log.error("TokenFactory execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=tx_hashes,
                notes=str(exc),
            )
