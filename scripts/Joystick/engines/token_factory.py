"""
token_factory.py — Engine 4: AFFECTION Generate() gas-mint + WM Batch Minter + Token Mint/Sell

Dual-mode token factory with priority:
  1. AFFECTION Generate() — DISABLED: _mintToCap mints to AFFECTION contract,
     not caller. Needs multiBuyWith() + payment tokens or custom contract.
  2. Token mint/sell       — mint existing tokens via parent → sell on DEX
  3. WM batch mint         — strategic WM accumulation via TGSv8.mintWM(N)

Also exports LPStrategy dataclass and optimize_lp_ratio() for use by
the mint test tool script.

is_ready():  Multi AFFECTION contract available OR TGSV8 deployed + authorized
simulate():  Evaluate AFF Generate profitability → token mint/sell → mintWM
execute():   multiGenerate(N) → swap AFF→WPLS, or token mint/sell, or mintWM
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
    PULSEX_V1_ROUTER, PULSEX_V2_ROUTER,
    MULTI_AFFECTION,
    GAS_PRICE_CEIL, GAS_MULT, MAX_SLIPPAGE,
)
from ..core.chain import (
    w3_read, w3_submit, erc20, safe, multicall,
    factory_contract, tgsv8_contract,
    multi_affection_contract,
    TGSV8_ABI, ROUTER_ABI,
)
from ..core.simulator import SimulationFailed
from ..oracle.price import get_amounts_out, get_amounts_out_v2, get_reserves

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
    Engine 4: AFFECTION Generate() gas-mint + WM batch minting + token mint/sell.

    Priority:
      1. AFFECTION Generate() — gas-only mint via Multi AFFECTION contract (262% ROI)
      2. Token mint/sell       — direct profit from existing tokens
      3. WM strategic accumulation — no direct profit
    """
    name = "TokenFactory"
    MAX_FAILURES = 3
    DISABLE_SECS = 600

    # Start conservative — seeded working balance was 7
    DEFAULT_MINT_COUNT = 7

    # AFFECTION Generate() parameters
    AFF_MINTS_PER_LOOP = 3          # Generate() mints 3 AFF per call
    AFF_DEFAULT_BATCH = 100         # optimal batch size (lowest per-AFF gas)
    AFF_MAX_BATCH = 200             # hard cap
    AFF_MIN_ROI_PCT = 20.0          # skip if ROI below this
    AFF_MAX_POOL_IMPACT_PCT = 2.0   # max % of pool reserves to sell in one TX

    # ── CRITICAL FINDING (block 26,007,782) ──────────────────────────────
    # multiGenerate() is NOT profitable standalone:
    #   - _mintToCap() mints AFF to address(this) = AFFECTION contract itself
    #   - multiGenerate() just calls Generate() N times — AFF stays in contract
    #   - Only multiBuyWith() transfers AFF to msg.sender, but requires payment tokens
    #   - At current prices, payment token cost exceeds AFF DEX value
    #
    # AFF Generate mode is DISABLED until one of:
    #   a) multiBuyWith() path implemented with payment token acquisition
    #   b) Custom contract deployed that calls Generate() + transfers AFF out
    #   c) Payment token prices drop enough for multiBuyWith() to be profitable
    AFF_GENERATE_ENABLED = False

    def __init__(self):
        super().__init__()
        self._tgsv8 = None
        self._tgsv8_submit = None
        self._multi_aff = None
        self._multi_aff_submit = None
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

    def _get_multi_aff(self, for_submit: bool = False):
        """Lazy-load Multi AFFECTION contract."""
        if for_submit:
            if self._multi_aff_submit is None:
                self._multi_aff_submit = multi_affection_contract(w3=w3_submit)
            return self._multi_aff_submit
        if self._multi_aff is None:
            self._multi_aff = multi_affection_contract()
        return self._multi_aff

    def is_ready(self) -> bool:
        # AFF Generate mode works independently of TGSv8 (when enabled)
        if self.AFF_GENERATE_ENABLED:
            try:
                multi = self._get_multi_aff()
                if multi is not None:
                    return True
            except Exception:
                pass

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

    def _evaluate_aff_generate(self) -> dict | None:
        """
        Evaluate AFFECTION multiGenerate() profitability.

        Returns dict with keys:
            batch, aff_minted, aff_minted_wei, gas_est, gas_cost_wei,
            gross_output_wei, net_profit_wei, roi_pct, sell_dex
        Or None if not profitable.

        NOTE: Currently disabled — Generate() mints AFF to the AFFECTION
        contract itself (via _mintToCap), not to the caller. multiGenerate()
        alone does not deliver AFF to Joey's EOA. Requires multiBuyWith()
        with a payment token, or a custom contract with explicit transfer.
        See AFF_GENERATE_ENABLED flag.
        """
        if not self.AFF_GENERATE_ENABLED:
            return None

        try:
            multi = self._get_multi_aff()
        except Exception:
            return None
        if multi is None:
            return None

        gas_price = w3_read.eth.gas_price
        if gas_price > GAS_PRICE_CEIL:
            return None

        batch = self.AFF_DEFAULT_BATCH
        aff_minted = batch * self.AFF_MINTS_PER_LOOP
        aff_minted_wei = aff_minted * 10**18

        # Pool impact check — reduce batch if selling would exceed impact cap
        for factory_label in ("V2", "V1"):
            reserves = get_reserves(AFFECTION, WPLS, factory_label)
            if reserves and reserves[0] > 0:
                max_sell = int(reserves[0] * self.AFF_MAX_POOL_IMPACT_PCT / 100)
                if aff_minted_wei > max_sell:
                    batch = max(1, int(max_sell / 10**18 / self.AFF_MINTS_PER_LOOP))
                    aff_minted = batch * self.AFF_MINTS_PER_LOOP
                    aff_minted_wei = aff_minted * 10**18
                break  # use first available pool for impact check

        # Gas estimate via eth_estimateGas (accurate, includes all internal calls)
        try:
            gas_est = multi.functions.multiGenerate(batch).estimate_gas(
                {"from": JOEY_WALLET}
            )
        except Exception as exc:
            log.debug("AFF multiGenerate(%d) gas estimate failed: %s", batch, exc)
            return None

        gas_cost_wei = int(gas_est * GAS_MULT * gas_price)

        # DEX output — check both V1 and V2, pick best
        best_output = 0
        best_dex = "V2"

        v1_out = get_amounts_out(aff_minted_wei, [AFFECTION, WPLS])
        if v1_out:
            v1_pls = v1_out[-1]
            if v1_pls > best_output:
                best_output = v1_pls
                best_dex = "V1"

        v2_out = get_amounts_out_v2(aff_minted_wei, [AFFECTION, WPLS])
        if v2_out:
            v2_pls = v2_out[-1]
            if v2_pls > best_output:
                best_output = v2_pls
                best_dex = "V2"

        if best_output == 0:
            log.debug("AFF: No DEX output for %d AFF", aff_minted)
            return None

        net_profit_wei = best_output - gas_cost_wei
        roi_pct = (net_profit_wei / gas_cost_wei * 100) if gas_cost_wei > 0 else 0

        if roi_pct < self.AFF_MIN_ROI_PCT:
            log.debug("AFF: ROI %.1f%% below min %.1f%% — skipping",
                       roi_pct, self.AFF_MIN_ROI_PCT)
            return None

        return {
            "batch": batch,
            "aff_minted": aff_minted,
            "aff_minted_wei": aff_minted_wei,
            "gas_est": gas_est,
            "gas_cost_wei": gas_cost_wei,
            "gross_output_wei": best_output,
            "net_profit_wei": net_profit_wei,
            "roi_pct": roi_pct,
            "sell_dex": best_dex,
        }

    def simulate(self) -> tuple[int, int]:
        """
        Priority:
          1. AFFECTION Generate() — highest ROI gas-only mint
          2. Token mint/sell — direct profit from existing tokens
          3. WM strategic accumulation — no direct profit
        """
        # 1. AFF Generate
        aff = self._evaluate_aff_generate()
        if aff is not None:
            log.info(
                "TokenFactory AFF mode: batch=%d, mint=%d AFF, net=%.1f PLS (%.0f%% ROI)",
                aff["batch"], aff["aff_minted"],
                aff["net_profit_wei"] / 1e18, aff["roi_pct"],
            )
            return aff["gross_output_wei"], aff["gas_cost_wei"]

        # 2. Token mint/sell (existing logic)
        target = self._find_mint_target()
        if target is not None:
            log.info(
                "TokenFactory target: %s net=%.4f PLS",
                target["child"][:10], target["net_profit"] / 1e18,
            )
            return target["expected_out"], target["gas_cost"]

        # 3. WM strategic accumulation (existing logic)
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
        # 1. Try AFF Generate (highest ROI)
        aff = self._evaluate_aff_generate()
        if aff is not None:
            return self._execute_aff_generate(aff, dry_run)

        # 2. Try token mint/sell
        target = self._find_mint_target()
        if target is not None:
            return self._execute_mint_sell(target, dry_run)

        # 3. Fall back to mintWM
        return self._execute_mint_wm(dry_run)

    def _execute_aff_generate(self, aff: dict, dry_run: bool) -> EngineResult:
        """
        Mint AFFECTION via multiGenerate(N) then swap AFF → WPLS on DEX.

        TX sequence:
          1. multiGenerate(batch) — AFF mints to tx.origin (Joey's EOA)
          2. approve(AFF, router, amount) — if needed
          3. router.swapExactTokensForTokens(AFF → WPLS)
        """
        batch = aff["batch"]
        aff_minted_wei = aff["aff_minted_wei"]

        if dry_run:
            log.info(
                "[dry-run] TokenFactory AFF: multiGenerate(%d) → %d AFF "
                "→ swap → ~%.1f PLS profit",
                batch, aff["aff_minted"], aff["net_profit_wei"] / 1e18,
            )
            return EngineResult(
                success=True,
                profit_wei=aff["gross_output_wei"],
                gas_wei=aff["gas_cost_wei"],
                notes=f"dry-run: multiGenerate({batch}) → {aff['aff_minted']} AFF",
            )

        tx_hashes = []
        total_gas_cost = 0

        try:
            # ── Step 1: multiGenerate ──────────────────────────────────
            multi_submit = self._get_multi_aff(for_submit=True)

            # Check Joey's AFF balance before
            aff_erc20 = erc20(AFFECTION)
            aff_before = safe(aff_erc20, "balanceOf", JOEY_WALLET) or 0

            from ..core.executor import send_tx as _send_tx
            receipt = _send_tx(
                multi_submit.functions.multiGenerate(batch),
                f"multiGenerate({batch}) → {aff['aff_minted']} AFF",
            )
            if not receipt:
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=0,
                    notes="multiGenerate: no receipt",
                )

            gas_used = receipt["gasUsed"]
            gas_price = receipt.get("effectiveGasPrice", w3_submit.eth.gas_price)
            total_gas_cost += gas_used * gas_price
            tx_hashes.append(f"0x{receipt['transactionHash'].hex()}")

            # Verify AFF arrived at Joey's EOA
            aff_after = safe(aff_erc20, "balanceOf", JOEY_WALLET) or 0
            aff_received = aff_after - aff_before

            if aff_received <= 0:
                log.warning(
                    "multiGenerate(%d): AFF balance did NOT increase! "
                    "before=%d after=%d — Generate() may send to contract "
                    "not tx.origin. Need Path B deploy.",
                    batch, aff_before, aff_after,
                )
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=total_gas_cost,
                    tx_hashes=tx_hashes,
                    notes=f"AFF not received at EOA "
                          f"(before={aff_before} after={aff_after})",
                )

            log.info(
                "multiGenerate(%d) → received %d AFF (%.2f)",
                batch, aff_received, aff_received / 1e18,
            )

            # ── Step 2: Swap AFF → WPLS ───────────────────────────────
            router_addr = (PULSEX_V1_ROUTER if aff["sell_dex"] == "V1"
                           else PULSEX_V2_ROUTER)

            # Approve AFF to router (idempotent — skips if allowance sufficient)
            aff_submit = w3_submit.eth.contract(
                address=Web3.to_checksum_address(AFFECTION),
                abi=aff_erc20.abi,
            )
            from ..core.executor import approve_if_needed
            approve_receipt = approve_if_needed(
                aff_submit, router_addr, aff_received,
                f"AFF → {aff['sell_dex']} router",
            )
            if approve_receipt:
                total_gas_cost += approve_receipt["gasUsed"] * gas_price
                tx_hashes.append(
                    f"0x{approve_receipt['transactionHash'].hex()}"
                )

            # Swap
            swap_router = w3_submit.eth.contract(
                address=Web3.to_checksum_address(router_addr),
                abi=ROUTER_ABI,
            )
            min_out = int(aff["gross_output_wei"] * (1 - MAX_SLIPPAGE))
            path = [
                Web3.to_checksum_address(AFFECTION),
                Web3.to_checksum_address(WPLS),
            ]
            deadline = w3_read.eth.get_block("latest")["timestamp"] + 300

            swap_receipt = _send_tx(
                swap_router.functions.swapExactTokensForTokens(
                    aff_received, min_out, path, JOEY_WALLET, deadline,
                ),
                f"Swap {aff_received / 1e18:.1f} AFF → WPLS "
                f"({aff['sell_dex']})",
            )
            if not swap_receipt:
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=total_gas_cost,
                    tx_hashes=tx_hashes,
                    notes="AFF swap failed — AFF sitting in wallet",
                )

            total_gas_cost += swap_receipt["gasUsed"] * gas_price
            tx_hashes.append(f"0x{swap_receipt['transactionHash'].hex()}")

            # Parse actual WPLS received from swap Transfer events
            actual_wpls = 0
            for log_entry in swap_receipt.get("logs", []):
                topics = log_entry.get("topics", [])
                if len(topics) >= 3:
                    sig = (topics[0].hex() if hasattr(topics[0], "hex")
                           else topics[0])
                    to_hex = (topics[2].hex() if hasattr(topics[2], "hex")
                              else topics[2])
                    to_addr = "0x" + to_hex[-40:]
                    if (sig.lower().startswith("ddf252ad")
                            and to_addr.lower() == JOEY_WALLET.lower()):
                        actual_wpls = int(log_entry["data"].hex(), 16)

            log.info(
                "AFF Generate complete: %d AFF → %.2f WPLS, "
                "gas=%.2f PLS, net=%.2f PLS",
                aff["aff_minted"], actual_wpls / 1e18,
                total_gas_cost / 1e18,
                (actual_wpls - total_gas_cost) / 1e18,
            )

            return EngineResult(
                success=True,
                profit_wei=actual_wpls,
                gas_wei=total_gas_cost,
                tx_hashes=tx_hashes,
                notes=f"AFF Generate: {aff['aff_minted']} AFF "
                      f"→ {actual_wpls / 1e18:.2f} WPLS",
            )

        except Exception as exc:
            log.error("AFF Generate execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=total_gas_cost,
                tx_hashes=tx_hashes, notes=str(exc),
            )

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
