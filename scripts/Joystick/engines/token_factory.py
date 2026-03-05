"""
token_factory.py — Engine 4: TGSV8 Token Factory + WM Batch Minter

Uses TGSV8 as on-chain execution substrate for:
  Strategy A — MINT_WM: batch mint WM tokens via TGSv8.mintWM(N)
  Strategy B — MINT_AND_SELL: mint existing tokens via parent → sell on DEX
  Strategy C — CREATE_AND_PAIR: create new V4 token → add LP (deferred)

Also exports LPStrategy dataclass and optimize_lp_ratio() for use by
the mint test tool script.

is_ready():  TGSV8 deployed, not paused, Joey authorized
simulate():  Estimate gas for mintWM(N) or find mintable tokens
execute():   Call TGSv8.mintWM(N) or mintTokens → swap → PLS
"""
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, AFFECTION, WM, WPLS, TGSV8,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    GAS_PRICE_CEIL, GAS_MULT,
)
from ..core.chain import (
    w3_read, w3_submit, erc20, safe, multicall,
    factory_contract, tgsv8_contract,
    TGSV8_ABI,
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
    Engine 4: TGSV8 Token Factory — mintWM batch minting + token mint/sell.

    Primary strategy: TGSv8.mintWM(N) — batch-mint WM tokens (1 per RHO call).
    WM is required to deploy new V2/V4 tokens. Accumulate WM early.

    Secondary strategy: mint existing tokens via parent → sell on DEX.
    """
    name = "TokenFactory"
    MAX_FAILURES = 3
    DISABLE_SECS = 600

    # Start conservative — seeded working balance was 7
    DEFAULT_MINT_COUNT = 7

    def __init__(self):
        super().__init__()
        self._tgsv8 = None
        self._tgsv8_submit = None
        self._cached_target = None
        self._cache_time = 0
        self._cache_ttl = 300  # 5 minute target cache

    def _get_tgsv8(self, for_submit: bool = False):
        """Lazy-load TGSV8 contract."""
        if not TGSV8:
            return None
        if for_submit:
            if self._tgsv8_submit is None:
                self._tgsv8_submit = tgsv8_contract(w3=w3_submit)
            return self._tgsv8_submit
        if self._tgsv8 is None:
            self._tgsv8 = tgsv8_contract()
        return self._tgsv8

    def is_ready(self) -> bool:
        if not TGSV8:
            log.debug("TokenFactory: TGSV8_ADDRESS not set")
            return False

        tgsv8 = self._get_tgsv8()
        if tgsv8 is None:
            return False

        try:
            paused = safe(tgsv8, "paused")
            if paused:
                log.debug("TokenFactory: TGSV8 is paused")
                return False

            authorized = safe(tgsv8, "authorized", JOEY_WALLET)
            if not authorized:
                log.debug("TokenFactory: Joey not authorized on TGSV8")
                return False

            return True
        except Exception as exc:
            log.debug("TokenFactory is_ready error: %s", exc)
            return False

    def _find_mint_target(self) -> dict | None:
        """
        Find the most profitable token to mint via TGSV8.
        Returns dict with keys: child, amount, expected_out, gas_cost, net_profit
        or None if nothing profitable.
        """
        # Use cached target if fresh
        if self._cached_target and (time.time() - self._cache_time) < self._cache_ttl:
            return self._cached_target

        tgsv8 = self._get_tgsv8()
        if tgsv8 is None:
            return None

        # Check registry for known tokens
        reg_len = safe(tgsv8, "registryLen") or 0
        if reg_len == 0:
            log.debug("TokenFactory: Empty registry — no tokens to mint")
            return None

        # Get children of AFFECTION (tokens mintable with AFFECTION as parent)
        children = safe(tgsv8, "getChildren", AFFECTION)
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
            debenture = safe(tgsv8, "checkDebenture", child)
            if not debenture:
                continue

            # Check DEX pair exists
            v1_pair = safe(v1_factory, "getPair", child, WPLS)
            v2_pair = safe(v2_factory, "getPair", child, WPLS)
            if (not v1_pair or v1_pair == ZERO) and (not v2_pair or v2_pair == ZERO):
                continue

            # Get best DEX output
            try:
                result = tgsv8.functions.getBestAmountsOut(
                    mint_amount, [child, WPLS]
                ).call()
                v1_out, v2_out, best_dex, best_out = result
            except Exception:
                continue

            if best_out == 0:
                continue

            # Estimate gas for mint + swap
            try:
                mint_gas = tgsv8.functions.mintTokens(child, mint_amount).estimate_gas(
                    {"from": JOEY_WALLET}
                )
                swap_gas = tgsv8.functions.swapExact(
                    child, WPLS, mint_amount, 0, best_dex
                ).estimate_gas({"from": JOEY_WALLET})
            except Exception:
                continue

            total_gas = int((mint_gas + swap_gas) * GAS_MULT)
            gas_cost_wei = total_gas * gas_price

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
        """
        Estimate profit and gas for either mintWM or mint-and-sell.
        WM minting: strategic (0 profit), gas-only cost.
        Token minting: profit = DEX output, gas = mint + swap gas.
        """
        # Try token mint/sell first (has direct profit)
        target = self._find_mint_target()
        if target is not None:
            log.info(
                "TokenFactory target: %s net=%.4f PLS",
                target["child"][:10], target["net_profit"] / 1e18,
            )
            return target["expected_out"], target["gas_cost"]

        # Fall back to mintWM (strategic, no direct profit)
        tgsv8 = self._get_tgsv8()
        if tgsv8 is None:
            raise SimulationFailed("TokenFactory: TGSV8 unavailable")

        count = self.DEFAULT_MINT_COUNT
        try:
            from ..core.simulator import simulate as sim_call
            sim_call(tgsv8.functions.mintWM(count))
        except SimulationFailed as e:
            raise SimulationFailed(f"TokenFactory: mintWM({count}) would revert: {e}")

        gas_price = w3_read.eth.gas_price
        gas_est = int(count * 130_000 * gas_price * GAS_MULT)  # ~130K gas per RHO
        log.info("TokenFactory: mintWM(%d) est gas=%.4f PLS", count, gas_est / 1e18)

        return 0, gas_est  # Strategic — no direct profit

    def execute(self, dry_run: bool = False) -> EngineResult:
        # Try token mint/sell first
        target = self._find_mint_target()
        if target is not None:
            return self._execute_mint_sell(target, dry_run)

        # Fall back to mintWM
        return self._execute_mint_wm(dry_run)

    def _execute_mint_wm(self, dry_run: bool) -> EngineResult:
        """Batch mint WM via TGSv8.mintWM(N)."""
        count = self.DEFAULT_MINT_COUNT
        tgsv8 = self._get_tgsv8(for_submit=True)
        if tgsv8 is None:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes="TGSV8 unavailable")

        # Pre-check WM working balance
        tgsv8_read = self._get_tgsv8()
        wm_before = safe(tgsv8_read, "bal", WM) or 0

        if dry_run:
            log.info("[dry-run] TokenFactory: would mintWM(%d), WM balance=%d",
                     count, wm_before)
            return EngineResult(
                success=True, profit_wei=0,
                gas_wei=int(count * 130_000 * w3_read.eth.gas_price),
                notes=f"dry-run: mintWM({count})",
            )

        try:
            from ..core.executor import send_tx as _send_tx
            receipt = _send_tx(
                tgsv8.functions.mintWM(count),
                f"TGSv8.mintWM({count})",
            )
            if receipt:
                gas_used = receipt.get("gasUsed", 0)
                gas_price = receipt.get("effectiveGasPrice", w3_submit.eth.gas_price)
                gas_cost = gas_used * gas_price
                tx_hash = f"0x{receipt['transactionHash'].hex()}"

                wm_after = safe(tgsv8_read, "bal", WM) or 0
                log.info(
                    "TGSv8.mintWM(%d) → gas=%d, working_balance_after=%d WM",
                    count, gas_used, wm_after,
                )

                return EngineResult(
                    success=True, profit_wei=0, gas_wei=gas_cost,
                    tx_hashes=[tx_hash],
                    notes=f"mintWM({count}) gas={gas_used} wm_after={wm_after}",
                )

            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes="No receipt")
        except Exception as exc:
            log.error("TokenFactory mintWM failed: %s", exc)
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))

    def _execute_mint_sell(self, target: dict, dry_run: bool) -> EngineResult:
        """Mint token via TGSV8.mintTokens → swap on DEX."""
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

        tgsv8 = self._get_tgsv8(for_submit=True)
        if tgsv8 is None:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes="TGSV8 unavailable")

        tx_hashes = []
        total_gas = 0

        try:
            # Ensure TGSV8 has AFFECTION
            aff_in_tgsv8 = safe(self._get_tgsv8(), "bal", AFFECTION) or 0
            if aff_in_tgsv8 < target["amount"]:
                from ..core.executor import approve_if_needed
                aff_submit = w3_submit.eth.contract(
                    address=Web3.to_checksum_address(AFFECTION),
                    abi=erc20(AFFECTION).abi,
                )
                approve_if_needed(
                    aff_submit, TGSV8, target["amount"],
                    "AFFECTION → TGSV8",
                )
                from ..core.executor import send_tx as _send_tx
                dep_receipt = _send_tx(
                    tgsv8.functions.deposit(AFFECTION, target["amount"]),
                    "Deposit AFFECTION into TGSV8",
                )
                if dep_receipt:
                    tx_hashes.append(f"0x{dep_receipt['transactionHash'].hex()}")
                    total_gas += dep_receipt["gasUsed"]

            # Mint tokens
            from ..core.executor import send_tx as _send_tx
            mint_receipt = _send_tx(
                tgsv8.functions.mintTokens(target["child"], target["amount"]),
                f"TGSV8.mintTokens({target['child'][:10]})",
            )
            if mint_receipt:
                tx_hashes.append(f"0x{mint_receipt['transactionHash'].hex()}")
                total_gas += mint_receipt["gasUsed"]

            # Swap to WPLS
            min_out = int(target["expected_out"] * 0.95)  # 5% slippage tolerance
            swap_receipt = _send_tx(
                tgsv8.functions.swapExact(
                    target["child"], WPLS, target["amount"],
                    min_out, target["best_dex"]
                ),
                f"TGSV8.swapExact({target['child'][:10]} → WPLS)",
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
