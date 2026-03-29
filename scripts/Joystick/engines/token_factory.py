"""
token_factory.py — Engine 4: Dual-Mode AFFECTION + WM Mint Engine

Parallel evaluation of two independent mint paths every cycle:
  1. AFFECTION via multiBuyWith — PLS → payment token → multiBuyWith → AFF → PLS
  2. WM via TGSv8.mintWM(N) — strategic WM accumulation

The engine prices all 5 AFFECTION payment routes (MATH, PI, G5, Fa, Faung),
picks the cheapest, compares against WM economics, and executes whichever
(or both) are profitable.

multiBuyWith(address, loops) is the ONLY path that delivers AFF to the caller.
multiGenerate() alone mints AFF to the AFFECTION contract's self-balance.

is_ready():  Multi AFFECTION contract available OR TGSV8 deployed + authorized
simulate():  Evaluate all AFF routes + WM, return best combined SimResult
execute():   Run profitable modes (or force-test on command)

Also exports LPStrategy dataclass and optimize_lp_ratio() for use by
the mint test tool script.
"""
import logging

from ..core.log_names import get_logger
import os
import time
from dataclasses import dataclass, field
from typing import Any

from web3 import Web3

from .base import EngineBase, EngineResult, SimResult
from ..core.config import (
    JOEY_WALLET, AFFECTION, WM, WPLS, TGSV8,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    PULSEX_V1_ROUTER, PULSEX_V2_ROUTER,
    MULTI_AFFECTION,
    GAS_PRICE_CEIL, GAS_MULT, MAX_SLIPPAGE,
    AFF_G5, AFF_PI, AFF_MATH, AFF_FA, AFF_FAUNG,
)
from ..core.chain import (
    w3_read, w3_submit, erc20, safe, multicall,
    factory_contract, tgsv8_contract,
    multi_affection_contract,
    TGSV8_ABI, ROUTER_ABI,
)
from ..core.simulator import SimulationFailed
from ..oracle.price import get_amounts_out, get_amounts_out_v2, get_reserves

log = get_logger(__name__)

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


# ── Route Data Classes ───────────────────────────────────────────────────────

@dataclass
class AffectionMintRoute:
    """One BuyWith path: PLS → payment token → multiBuyWith → AFF → PLS."""
    name: str                    # "G5", "PI", "MATH", "Fa", "Faung"
    payment_token: str           # checksum address
    per_loop_wei: int            # payment tokens consumed per loop
    buy_fn: str                  # "BuyWithG5", etc.
    loops: int                   # number of loops
    aff_output: int              # loops * 3 (in whole tokens)
    aff_output_wei: int          # loops * 3 * 1e18
    payment_total_wei: int       # per_loop_wei * loops
    payment_cost_pls: int        # PLS to acquire payment tokens (via getAmountsOut)
    aff_value_pls: int           # PLS from selling AFF (via getAmountsOut)
    gas_est: int                 # estimated gas units
    gas_cost_pls: int            # gas_est * gas_price (in wei)
    total_cost_pls: int          # payment_cost_pls + gas_cost_pls (in wei)
    net_profit_pls: int          # aff_value_pls - total_cost_pls (in wei)
    roi_pct: float               # (net / total_cost) * 100
    sell_dex: str                # "V1" or "V2"
    buy_dex: str                 # "V1" or "V2" (for acquiring payment token)
    timestamp: float             # time.time() when evaluated

    @property
    def profitable(self) -> bool:
        return self.net_profit_pls > 0

    def to_log_dict(self) -> dict:
        return {
            "name": self.name,
            "payment_cost_pls": round(self.payment_cost_pls / 1e18, 2),
            "aff_value_pls": round(self.aff_value_pls / 1e18, 2),
            "gas_pls": round(self.gas_cost_pls / 1e18, 2),
            "net": round(self.net_profit_pls / 1e18, 2),
            "roi": round(self.roi_pct, 1),
        }


@dataclass
class WmMintRoute:
    """WM minting via TGSv8.mintWM(N)."""
    count: int                   # N tokens to mint
    wm_value_pls: int            # PLS value of N WM on DEX (in wei)
    gas_est: int
    gas_cost_pls: int            # in wei
    net_profit_pls: int          # wm_value - gas_cost (in wei)
    roi_pct: float
    sell_dex: str
    timestamp: float

    @property
    def profitable(self) -> bool:
        return self.net_profit_pls > 0

    def to_log_dict(self) -> dict:
        return {
            "count": self.count,
            "value_pls": round(self.wm_value_pls / 1e18, 2),
            "gas_pls": round(self.gas_cost_pls / 1e18, 2),
            "net": round(self.net_profit_pls / 1e18, 2),
            "roi": round(self.roi_pct, 1),
        }


@dataclass
class DualSimResult:
    """Combined simulation result for both AFF and WM paths."""
    aff_routes: list[AffectionMintRoute] = field(default_factory=list)
    best_aff: AffectionMintRoute | None = None
    wm_route: WmMintRoute | None = None
    mode: str = "none"  # "aff_only" | "wm_only" | "dual" | "none"
    gas_price: int = 0
    block: int = 0


# ── Static route definitions ────────────────────────────────────────────────

_AFF_ROUTE_DEFS = [
    {"name": "MATH",  "addr": AFF_MATH,  "per_loop_wei": int(3e18),    "buy_fn": "BuyWithMATH"},
    {"name": "PI",    "addr": AFF_PI,    "per_loop_wei": int(0.01e18), "buy_fn": "BuyWithPI"},
    {"name": "G5",    "addr": AFF_G5,    "per_loop_wei": int(0.6e18),  "buy_fn": "BuyWithG5"},
    {"name": "Fa",    "addr": AFF_FA,    "per_loop_wei": int(12e18),   "buy_fn": "BuyWithFa"},
    {"name": "Faung", "addr": AFF_FAUNG, "per_loop_wei": int(6e18),    "buy_fn": "BuyWithFaung"},
]


# ── Token Factory Engine ─────────────────────────────────────────────────────

class TokenFactoryEngine(EngineBase):
    """
    Engine 4: Dual-mode AFFECTION + WM mint engine.

    Evaluates all 5 AFFECTION payment routes and WM minting every cycle.
    Executes whichever (or both) are profitable.
    """
    name = "TokenFactory"
    MAX_FAILURES = 3
    DISABLE_SECS = 600

    # Default parameters
    DEFAULT_WM_COUNT = 7
    DEFAULT_AFF_LOOPS = 100        # production batch size
    TEST_AFF_LOOPS = 10            # force-test batch size
    TEST_WM_COUNT = 2              # force-test WM count
    TEST_BUDGET_CEIL_PLS = 10_000  # max PLS for force-test (whole tokens)

    AFF_MINTS_PER_LOOP = 3         # multiBuyWith delivers 3 AFF per loop
    AFF_MAX_POOL_IMPACT_PCT = 2.0  # max % of pool reserves to trade in one TX
    AFF_MIN_ROI_PCT = 5.0          # skip if ROI below this (production)

    # Force-test mode: set via env var FORCE_AFF_TEST=1 or --force-test CLI flag
    FORCE_TEST = os.getenv("FORCE_AFF_TEST", "0") == "1"

    def __init__(self):
        super().__init__()
        self._tgsv8 = None
        self._tgsv8_submit = None
        self._multi_aff = None
        self._multi_aff_submit = None
        self._cached_target = None
        self._cache_time = 0
        self._cache_ttl = 300  # 5 minute target cache
        self._last_dual_sim: DualSimResult | None = None

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
        # Multi AFFECTION is always available (no auth needed for multiBuyWith)
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

    # ── Route evaluation ─────────────────────────────────────────────────────

    def _evaluate_all_aff_routes(
        self, loops: int, gas_price: int
    ) -> list[AffectionMintRoute]:
        """
        Price all 5 AFFECTION payment routes.
        Returns sorted list (best first) of AffectionMintRoute.
        """
        aff_output = loops * self.AFF_MINTS_PER_LOOP
        aff_output_wei = aff_output * 10**18
        now = time.time()

        # Get AFF sell price (check both DEXes)
        best_aff_out = 0
        best_sell_dex = "V2"
        for label, fn in [("V1", get_amounts_out), ("V2", get_amounts_out_v2)]:
            result = fn(aff_output_wei, [AFFECTION, WPLS])
            if result and result[-1] > best_aff_out:
                best_aff_out = result[-1]
                best_sell_dex = label

        if best_aff_out == 0:
            log.debug("AFF: No DEX output for %d AFF on either DEX", aff_output)
            return []

        # Pool impact check on AFF sell side
        for factory_label in ("V2", "V1"):
            reserves = get_reserves(AFFECTION, WPLS, factory_label)
            if reserves and reserves[0] > 0:
                impact = aff_output_wei / reserves[0] * 100
                if impact > self.AFF_MAX_POOL_IMPACT_PCT:
                    log.debug("AFF sell impact %.1f%% > %.1f%% cap — skipping",
                              impact, self.AFF_MAX_POOL_IMPACT_PCT)
                    return []
                break

        routes = []
        for rdef in _AFF_ROUTE_DEFS:
            payment_total = rdef["per_loop_wei"] * loops

            # Price payment token acquisition: PLS → payment token
            best_buy_cost = 0
            best_buy_dex = "V2"
            for label, fn in [("V1", get_amounts_out), ("V2", get_amounts_out_v2)]:
                # Reverse: how much PLS to get payment_total of the token?
                # Use getAmountsOut with [WPLS, token] to see how much token we get for X PLS
                # Instead: getAmountsOut(payment_total, [token, WPLS]) tells us PLS value
                result = fn(payment_total, [rdef["addr"], WPLS])
                if result and result[-1] > 0:
                    # This is PLS value of the payment tokens
                    cost = result[-1]
                    if best_buy_cost == 0 or cost < best_buy_cost:
                        best_buy_cost = cost
                        best_buy_dex = label

            if best_buy_cost == 0:
                log.debug("AFF route %s: no DEX pair for payment token", rdef["name"])
                continue

            # Pool impact on payment token buy side
            skip = False
            for factory_label in ("V2", "V1"):
                reserves = get_reserves(rdef["addr"], WPLS, factory_label)
                if reserves and reserves[0] > 0:
                    impact = payment_total / reserves[0] * 100
                    if impact > self.AFF_MAX_POOL_IMPACT_PCT:
                        log.debug("AFF route %s: buy impact %.1f%% > cap",
                                  rdef["name"], impact)
                        skip = True
                    break
            if skip:
                continue

            # Estimate gas for multiBuyWith
            try:
                multi = self._get_multi_aff()
                gas_est = multi.functions.multiBuyWith(
                    Web3.to_checksum_address(rdef["addr"]), loops
                ).estimate_gas({"from": JOEY_WALLET})
            except Exception as exc:
                log.debug("AFF route %s: gas estimate failed: %s", rdef["name"], exc)
                # Use a conservative default for pricing purposes
                gas_est = 4_000_000 + loops * 40_000

            # Total gas includes: swap PLS→token + approve + multiBuyWith + swap AFF→PLS
            # Approximate the swap/approve overhead
            swap_gas_overhead = 200_000  # 2 swaps + 1 approve typical
            total_gas = int((gas_est + swap_gas_overhead) * GAS_MULT)
            gas_cost = total_gas * gas_price

            # Payment cost: we need to BUY payment tokens, so cost is PLS we spend
            # best_buy_cost is what the payment tokens are WORTH in PLS (sell direction)
            # Buying costs more due to swap fee. Approximate with 0.3% fee each way:
            # Cost to buy = payment_value * (1000/997) ≈ payment_value * 1.003
            payment_cost_pls = int(best_buy_cost * 1000 / 997)

            total_cost = payment_cost_pls + gas_cost
            net_profit = best_aff_out - total_cost
            roi = (net_profit / total_cost * 100) if total_cost > 0 else 0

            routes.append(AffectionMintRoute(
                name=rdef["name"],
                payment_token=rdef["addr"],
                per_loop_wei=rdef["per_loop_wei"],
                buy_fn=rdef["buy_fn"],
                loops=loops,
                aff_output=aff_output,
                aff_output_wei=aff_output_wei,
                payment_total_wei=payment_total,
                payment_cost_pls=payment_cost_pls,
                aff_value_pls=best_aff_out,
                gas_est=gas_est,
                gas_cost_pls=gas_cost,
                total_cost_pls=total_cost,
                net_profit_pls=net_profit,
                roi_pct=roi,
                sell_dex=best_sell_dex,
                buy_dex=best_buy_dex,
                timestamp=now,
            ))

        routes.sort(key=lambda r: r.net_profit_pls, reverse=True)
        return routes

    def _evaluate_wm_mint(self, count: int, gas_price: int) -> WmMintRoute | None:
        """Evaluate WM minting via TGSv8.mintWM(N)."""
        tgsv8 = self._get_tgsv8()
        if tgsv8 is None:
            return None

        now = time.time()

        # Check WM DEX value
        wm_amount_wei = count * 10**18
        best_wm_out = 0
        best_sell_dex = "V2"
        for label, fn in [("V1", get_amounts_out), ("V2", get_amounts_out_v2)]:
            result = fn(wm_amount_wei, [WM, WPLS])
            if result and result[-1] > best_wm_out:
                best_wm_out = result[-1]
                best_sell_dex = label

        # Gas estimate
        try:
            gas_est = tgsv8.functions.mintWM(count).estimate_gas(
                {"from": JOEY_WALLET}
            )
        except Exception as exc:
            log.debug("WM mintWM(%d) gas estimate failed: %s", count, exc)
            gas_est = count * 130_000

        gas_cost = int(gas_est * GAS_MULT * gas_price)
        net = best_wm_out - gas_cost
        roi = (net / gas_cost * 100) if gas_cost > 0 else 0

        return WmMintRoute(
            count=count,
            wm_value_pls=best_wm_out,
            gas_est=gas_est,
            gas_cost_pls=gas_cost,
            net_profit_pls=net,
            roi_pct=roi,
            sell_dex=best_sell_dex,
            timestamp=now,
        )

    # Cache TTL for dual sim — economics don't change in <60s
    _DUAL_SIM_TTL = 60

    def _build_dual_sim(self) -> DualSimResult:
        """Build full dual-mode simulation. Cached for _DUAL_SIM_TTL seconds."""
        # Return cached result if fresh enough (avoids RPC storms in parallel sim)
        if (self._last_dual_sim is not None
                and hasattr(self._last_dual_sim, '_timestamp')
                and time.time() - self._last_dual_sim._timestamp < self._DUAL_SIM_TTL):
            return self._last_dual_sim

        gas_price = w3_read.eth.gas_price
        if gas_price > GAS_PRICE_CEIL:
            return DualSimResult(gas_price=gas_price)

        loops = self.TEST_AFF_LOOPS if self.FORCE_TEST else self.DEFAULT_AFF_LOOPS
        wm_count = self.TEST_WM_COUNT if self.FORCE_TEST else self.DEFAULT_WM_COUNT

        try:
            block = w3_read.eth.block_number
        except Exception:
            block = 0

        aff_routes = self._evaluate_all_aff_routes(loops, gas_price)
        best_aff = aff_routes[0] if aff_routes else None

        wm_route = self._evaluate_wm_mint(wm_count, gas_price)

        # Determine mode
        aff_go = best_aff is not None and (best_aff.profitable or self.FORCE_TEST)
        wm_go = wm_route is not None and (wm_route.profitable or self.FORCE_TEST)

        if aff_go and wm_go:
            mode = "dual"
        elif aff_go:
            mode = "aff_only"
        elif wm_go:
            mode = "wm_only"
        else:
            mode = "none"

        result = DualSimResult(
            aff_routes=aff_routes,
            best_aff=best_aff,
            wm_route=wm_route,
            mode=mode,
            gas_price=gas_price,
            block=block,
        )
        result._timestamp = time.time()
        self._last_dual_sim = result
        return result

    # ── EngineBase interface ──────────────────────────────────────────────────

    def simulate(self) -> tuple[int, int]:
        """
        Evaluate all routes and return (best_profit_wei, best_gas_wei).
        """
        dual = self._build_dual_sim()

        # Log route monitor
        self._log_route_monitor(dual)

        if dual.mode == "none" and not self.FORCE_TEST:
            # Fall back to legacy token mint/sell scan
            target = self._find_mint_target()
            if target is not None:
                log.info(
                    "TokenFactory target: %s net=%.4f PLS",
                    target["child"][:10], target["net_profit"] / 1e18,
                )
                return target["expected_out"], target["gas_cost"]
            raise SimulationFailed("TokenFactory: no profitable route")

        # Report the best available route
        best_profit = 0
        best_gas = 0

        if dual.best_aff and (dual.best_aff.profitable or self.FORCE_TEST):
            log.info(
                "TokenFactory AFF %s: %d loops → %d AFF, "
                "cost=%.1f PLS, value=%.1f PLS, net=%.1f PLS (%.1f%% ROI)",
                dual.best_aff.name, dual.best_aff.loops, dual.best_aff.aff_output,
                dual.best_aff.total_cost_pls / 1e18,
                dual.best_aff.aff_value_pls / 1e18,
                dual.best_aff.net_profit_pls / 1e18,
                dual.best_aff.roi_pct,
            )
            best_profit = dual.best_aff.aff_value_pls
            best_gas = dual.best_aff.total_cost_pls

        if dual.wm_route:
            log.info(
                "TokenFactory WM: mintWM(%d), value=%.1f PLS, gas=%.1f PLS, "
                "net=%.1f PLS (%.1f%% ROI)",
                dual.wm_route.count,
                dual.wm_route.wm_value_pls / 1e18,
                dual.wm_route.gas_cost_pls / 1e18,
                dual.wm_route.net_profit_pls / 1e18,
                dual.wm_route.roi_pct,
            )
            # If WM is better than AFF (or AFF not available)
            if dual.wm_route.net_profit_pls > (dual.best_aff.net_profit_pls if dual.best_aff else 0):
                best_profit = dual.wm_route.wm_value_pls
                best_gas = dual.wm_route.gas_cost_pls

        if best_profit == 0 and best_gas == 0:
            if self.FORCE_TEST and dual.best_aff:
                return dual.best_aff.aff_value_pls, dual.best_aff.total_cost_pls
            raise SimulationFailed("TokenFactory: no viable route")

        return best_profit, best_gas

    def sim_result(self) -> SimResult:
        """Override to provide dual-mode sim result with mode info."""
        try:
            profit, gas = self.simulate()
            dual = self._last_dual_sim
            mode = dual.mode if dual else "unknown"
            return SimResult(
                profit_wei=profit,
                gas_wei=gas,
                wallet_role=self.wallet_role,
                mode=f"factory_{mode}",
                notes=f"mode={mode}",
            )
        except Exception as e:
            return SimResult.failed(str(e))

    def execute(self, dry_run: bool = False) -> EngineResult:
        # Re-evaluate fresh (or use cached sim)
        dual = self._last_dual_sim
        if dual is None or time.time() - (dual.best_aff.timestamp if dual.best_aff else 0) > 30:
            dual = self._build_dual_sim()

        tx_hashes = []
        total_profit = 0
        total_gas = 0
        notes_parts = []

        # Execute AFF if profitable (or force-test)
        if dual.best_aff and (dual.best_aff.profitable or self.FORCE_TEST):
            if self.FORCE_TEST:
                # Budget check
                est_cost_pls = dual.best_aff.total_cost_pls / 1e18
                if est_cost_pls > self.TEST_BUDGET_CEIL_PLS:
                    return EngineResult(
                        success=False, profit_wei=0, gas_wei=0,
                        notes=f"Force-test budget exceeded: {est_cost_pls:.0f} > "
                              f"{self.TEST_BUDGET_CEIL_PLS} PLS",
                    )

            result = self._execute_aff_mint(dual.best_aff, dry_run)
            tx_hashes.extend(result.tx_hashes)
            total_profit += result.profit_wei
            total_gas += result.gas_wei
            notes_parts.append(f"AFF_{dual.best_aff.name}: {result.notes}")

            if not result.success:
                return result  # AFF failure stops the cycle

        # Execute WM if profitable (or force-test)
        if dual.wm_route and (dual.wm_route.profitable or self.FORCE_TEST):
            result = self._execute_mint_wm(
                dual.wm_route.count if self.FORCE_TEST else self.DEFAULT_WM_COUNT,
                dry_run,
            )
            tx_hashes.extend(result.tx_hashes)
            total_gas += result.gas_wei
            notes_parts.append(f"WM: {result.notes}")

        # If nothing was executed, try legacy token mint/sell
        if not tx_hashes and not dry_run:
            target = self._find_mint_target()
            if target is not None:
                return self._execute_mint_sell(target, dry_run)

            # Last resort: strategic WM mint
            return self._execute_mint_wm(self.DEFAULT_WM_COUNT, dry_run)

        # Reset force-test after one cycle
        if self.FORCE_TEST:
            self.FORCE_TEST = False
            os.environ.pop("FORCE_AFF_TEST", None)

        return EngineResult(
            success=True,
            profit_wei=total_profit,
            gas_wei=total_gas,
            tx_hashes=tx_hashes,
            notes=" | ".join(notes_parts) if notes_parts else "no action",
        )

    # ── AFF mint execution ───────────────────────────────────────────────────

    def _execute_aff_mint(
        self, route: AffectionMintRoute, dry_run: bool
    ) -> EngineResult:
        """
        Full AFF mint pipeline via Joey's EOA:
          TX1: Swap PLS → payment token on best DEX
          TX2: Approve payment token → Multi AFFECTION contract
          TX3: multiBuyWith(payment_addr, loops) → receive AFF
          TX4: Swap AFF → WPLS on best DEX
        """
        if dry_run:
            log.info(
                "[dry-run] TokenFactory AFF %s: %d loops → %d AFF, "
                "est net=%.1f PLS (%.1f%% ROI)",
                route.name, route.loops, route.aff_output,
                route.net_profit_pls / 1e18, route.roi_pct,
            )
            return EngineResult(
                success=True,
                profit_wei=route.aff_value_pls,
                gas_wei=route.gas_cost_pls,
                notes=f"dry-run: multiBuyWith({route.name}, {route.loops}) → {route.aff_output} AFF",
            )

        tx_hashes = []
        total_gas_cost = 0

        try:
            from ..core.executor import send_tx as _send_tx, approve_if_needed

            gas_price = w3_submit.eth.gas_price

            # ── TX1: Swap PLS → payment token (skip if already have enough) ─
            payment_erc20 = erc20(route.payment_token)
            existing_bal = safe(payment_erc20, "balanceOf", JOEY_WALLET) or 0
            need_tokens = route.payment_total_wei

            if existing_bal >= need_tokens:
                log.info("Already have %.4f %s (need %.4f) — skipping swap",
                         existing_bal / 1e18, route.name, need_tokens / 1e18)
            else:
                shortfall = need_tokens - existing_bal
                router_addr = (PULSEX_V1_ROUTER if route.buy_dex == "V1"
                               else PULSEX_V2_ROUTER)
                swap_router = w3_submit.eth.contract(
                    address=Web3.to_checksum_address(router_addr),
                    abi=ROUTER_ABI,
                )
                deadline = w3_read.eth.get_block("latest")["timestamp"] + 300

                path_buy = [
                    Web3.to_checksum_address(WPLS),
                    Web3.to_checksum_address(route.payment_token),
                ]

                # payment_cost_pls is the sell-side value; buying costs more.
                # Scale PLS spend proportionally to the shortfall.
                shortfall_ratio = shortfall / need_tokens if need_tokens > 0 else 1.0
                pls_to_spend = int(route.payment_cost_pls * shortfall_ratio * 1.05)

                buy_fn = get_amounts_out if route.buy_dex == "V1" else get_amounts_out_v2
                preview = buy_fn(pls_to_spend, path_buy)
                if not preview or preview[-1] < shortfall:
                    pls_to_spend = int(route.payment_cost_pls * shortfall_ratio * 1.15)
                    preview = buy_fn(pls_to_spend, path_buy)
                    if not preview or preview[-1] < shortfall:
                        return EngineResult(
                            success=False, profit_wei=0, gas_wei=0,
                            notes=f"Cannot buy enough {route.name}: "
                                  f"need {shortfall / 1e18:.4f}, "
                                  f"get {(preview[-1] if preview else 0) / 1e18:.4f}",
                        )

                min_payment = int(shortfall * (1 - MAX_SLIPPAGE))

                receipt = _send_tx(
                    swap_router.functions.swapExactETHForTokens(
                        min_payment, path_buy, JOEY_WALLET, deadline,
                    ),
                    f"Swap {pls_to_spend / 1e18:.1f} PLS → {route.name} ({route.buy_dex})",
                    value=pls_to_spend,
                    skip_simulate=True,  # payable
                )
                if not receipt:
                    return EngineResult(
                        success=False, profit_wei=0, gas_wei=0,
                        notes=f"TX1 failed: PLS → {route.name}",
                    )
                tx_hashes.append(f"0x{receipt['transactionHash'].hex()}")
                total_gas_cost += receipt["gasUsed"] * gas_price

            payment_bal = safe(payment_erc20, "balanceOf", JOEY_WALLET) or 0
            log.info("Payment token %s balance = %.4f (need %.4f)",
                     route.name, payment_bal / 1e18, need_tokens / 1e18)

            if payment_bal < route.payment_total_wei:
                log.warning(
                    "Insufficient %s after swap: have %d, need %d",
                    route.name, payment_bal, route.payment_total_wei,
                )
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=total_gas_cost,
                    tx_hashes=tx_hashes,
                    notes=f"Insufficient {route.name} after swap",
                )

            # ── TX2: Approve payment token → Multi AFFECTION ──────────────
            payment_submit = w3_submit.eth.contract(
                address=Web3.to_checksum_address(route.payment_token),
                abi=payment_erc20.abi,
            )
            max_uint = 2**256 - 1
            approve_receipt = approve_if_needed(
                payment_submit,
                MULTI_AFFECTION,
                max_uint,
                f"{route.name} → Multi AFFECTION",
            )
            if approve_receipt:
                tx_hashes.append(f"0x{approve_receipt['transactionHash'].hex()}")
                total_gas_cost += approve_receipt["gasUsed"] * gas_price

            # ── TX3: multiBuyWith → receive AFF ───────────────────────────
            aff_erc20 = erc20(AFFECTION)
            aff_before = safe(aff_erc20, "balanceOf", JOEY_WALLET) or 0

            multi_submit = self._get_multi_aff(for_submit=True)
            receipt = _send_tx(
                multi_submit.functions.multiBuyWith(
                    Web3.to_checksum_address(route.payment_token),
                    route.loops,
                ),
                f"multiBuyWith({route.name}, {route.loops}) → {route.aff_output} AFF",
            )
            if not receipt:
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=total_gas_cost,
                    tx_hashes=tx_hashes,
                    notes="TX3 multiBuyWith failed",
                )
            tx_hashes.append(f"0x{receipt['transactionHash'].hex()}")
            total_gas_cost += receipt["gasUsed"] * gas_price

            # Verify AFF received
            aff_after = safe(aff_erc20, "balanceOf", JOEY_WALLET) or 0
            aff_received = aff_after - aff_before
            log.info("multiBuyWith: AFF received = %.2f (expected %d)",
                     aff_received / 1e18, route.aff_output)

            if aff_received <= 0:
                log.warning("multiBuyWith: NO AFF received! before=%d after=%d",
                            aff_before, aff_after)
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=total_gas_cost,
                    tx_hashes=tx_hashes,
                    notes=f"AFF not received (before={aff_before} after={aff_after})",
                )

            # ── TX4: Swap AFF → WPLS ─────────────────────────────────────
            sell_router_addr = (PULSEX_V1_ROUTER if route.sell_dex == "V1"
                                else PULSEX_V2_ROUTER)

            # Approve AFF to sell router
            aff_submit = w3_submit.eth.contract(
                address=Web3.to_checksum_address(AFFECTION),
                abi=aff_erc20.abi,
            )
            approve_receipt = approve_if_needed(
                aff_submit,
                sell_router_addr,
                aff_received,
                f"AFF → {route.sell_dex} router",
            )
            if approve_receipt:
                tx_hashes.append(f"0x{approve_receipt['transactionHash'].hex()}")
                total_gas_cost += approve_receipt["gasUsed"] * gas_price

            # Swap AFF → WPLS
            sell_router = w3_submit.eth.contract(
                address=Web3.to_checksum_address(sell_router_addr),
                abi=ROUTER_ABI,
            )
            min_out = int(route.aff_value_pls * (1 - MAX_SLIPPAGE))
            path_sell = [
                Web3.to_checksum_address(AFFECTION),
                Web3.to_checksum_address(WPLS),
            ]
            deadline = w3_read.eth.get_block("latest")["timestamp"] + 300

            swap_receipt = _send_tx(
                sell_router.functions.swapExactTokensForTokens(
                    aff_received, min_out, path_sell, JOEY_WALLET, deadline,
                ),
                f"Swap {aff_received / 1e18:.1f} AFF → WPLS ({route.sell_dex})",
            )
            if not swap_receipt:
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=total_gas_cost,
                    tx_hashes=tx_hashes,
                    notes="AFF sell swap failed — AFF in wallet",
                )
            tx_hashes.append(f"0x{swap_receipt['transactionHash'].hex()}")
            total_gas_cost += swap_receipt["gasUsed"] * gas_price

            # Parse actual WPLS received
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

            # Log TX history
            self._log_tx_history(
                tx_hash=f"0x{swap_receipt['transactionHash'].hex()}",
                action=f"multiBuyWith_{route.name}",
                gas_used=swap_receipt["gasUsed"],
                gas_price=gas_price,
                tokens_in={route.name: route.payment_total_wei / 1e18},
                tokens_out={"AFF": aff_received / 1e18},
                pls_net=(actual_wpls - total_gas_cost) / 1e18,
                block=swap_receipt.get("blockNumber", 0),
            )

            log.info(
                "AFF mint complete: %d AFF → %.2f WPLS, "
                "gas=%.2f PLS, net=%.2f PLS",
                route.aff_output, actual_wpls / 1e18,
                total_gas_cost / 1e18,
                (actual_wpls - total_gas_cost) / 1e18,
            )

            return EngineResult(
                success=True,
                profit_wei=actual_wpls,
                gas_wei=total_gas_cost,
                tx_hashes=tx_hashes,
                notes=f"AFF {route.name}: {route.aff_output} AFF "
                      f"→ {actual_wpls / 1e18:.2f} WPLS",
            )

        except Exception as exc:
            log.error("AFF mint execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=total_gas_cost,
                tx_hashes=tx_hashes, notes=str(exc),
            )

    # ── WM mint execution ────────────────────────────────────────────────────

    def _execute_mint_wm(self, count: int, dry_run: bool) -> EngineResult:
        """Batch mint WM via TGSv8.mintWM(N)."""
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

                # Log TX history
                self._log_tx_history(
                    tx_hash=tx_hash,
                    action=f"mintWM_{count}",
                    gas_used=gas_used,
                    gas_price=gas_price,
                    tokens_in={},
                    tokens_out={"WM": count},
                    pls_net=-gas_cost / 1e18,
                    block=receipt.get("blockNumber", 0),
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

    # ── Legacy token mint/sell ───────────────────────────────────────────────

    def _find_mint_target(self) -> dict | None:
        """
        Find the most profitable token to mint via TGSV8.
        Returns dict with keys: child, amount, expected_out, gas_cost, net_profit
        or None if nothing profitable.
        """
        if self._cached_target and (time.time() - self._cache_time) < self._cache_ttl:
            return self._cached_target

        tgsv8 = self._get_tgsv8()
        if tgsv8 is None:
            return None

        reg_len = safe(tgsv8, "registryLen") or 0
        if reg_len == 0:
            return None

        children = safe(tgsv8, "getChildren", AFFECTION)
        if not children:
            return None

        gas_price = w3_read.eth.gas_price
        if gas_price > GAS_PRICE_CEIL:
            return None

        best = None
        mint_amount = int(1e18)

        from ..oracle.data_store import DataStore
        store = DataStore.get()

        for child in children[:50]:
            if child == ZERO:
                continue

            debenture = safe(tgsv8, "checkDebenture", child)
            if not debenture:
                continue

            if not store.has_pair(child, WPLS):
                continue

            try:
                result = tgsv8.functions.getBestAmountsOut(
                    mint_amount, [child, WPLS]
                ).call()
                v1_out, v2_out, best_dex, best_out = result
            except Exception:
                continue

            if best_out == 0:
                continue

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

            from ..core.executor import send_tx as _send_tx
            mint_receipt = _send_tx(
                tgsv8.functions.mintTokens(target["child"], target["amount"]),
                f"TGSV8.mintTokens({target['child'][:10]})",
            )
            if mint_receipt:
                tx_hashes.append(f"0x{mint_receipt['transactionHash'].hex()}")
                total_gas += mint_receipt["gasUsed"]

            min_out = int(target["expected_out"] * 0.95)
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

    # ── Logging ──────────────────────────────────────────────────────────────

    def _log_route_monitor(self, dual: DualSimResult) -> None:
        """Write route monitor entry to data/route_monitor.jsonl."""
        from ..core.event_logger import events as _events

        routes_data = [r.to_log_dict() for r in dual.aff_routes]
        wm_data = dual.wm_route.to_log_dict() if dual.wm_route else None

        action = "none"
        if dual.mode != "none":
            action = dual.mode
        if self.FORCE_TEST:
            action = "force_test"

        data = {
            "block": dual.block,
            "gas_price_gwei": round(dual.gas_price / 1e9, 0) if dual.gas_price else 0,
            "aff_price_pls": round(dual.best_aff.aff_value_pls / dual.best_aff.aff_output / 1e18, 2)
            if dual.best_aff and dual.best_aff.aff_output > 0 else 0,
            "routes": routes_data,
            "wm": wm_data,
            "best_aff_route": dual.best_aff.name if dual.best_aff else "none",
            "action_taken": action,
        }

        _events.log(
            "engine.tokenfactory.route_monitor",
            engine="TokenFactory",
            data=data,
            block=dual.block,
        )

    def _log_tx_history(
        self,
        tx_hash: str,
        action: str,
        gas_used: int,
        gas_price: int,
        tokens_in: dict,
        tokens_out: dict,
        pls_net: float,
        block: int,
    ) -> None:
        """Write TX history entry."""
        from ..core.event_logger import events as _events

        _events.log(
            "engine.tokenfactory.tx",
            engine="TokenFactory",
            tx_hash=tx_hash,
            gas_used=gas_used,
            gas_price=gas_price,
            block=block,
            data={
                "action": action,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "pls_net": round(pls_net, 4),
                "wallet": JOEY_WALLET,
            },
        )
