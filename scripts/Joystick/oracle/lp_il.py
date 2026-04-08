"""
lp_il.py — Impermanent loss decomposition for GIBS LP positions.

Decomposes the total value delta of an LP position between baseline and
current snapshot into:
    * IL (impermanent loss vs HODL)
    * fees earned (from k_per_lp growth, computed here — not from lp_fees)
    * price appreciation (HODL value change)

Classic Uniswap v2 IL, given r = price_new / price_old:
    IL_pct = 2*sqrt(r)/(1+r) - 1       # always <= 0, zero when r == 1

We compute IL in PLS directly rather than via the pct formula, since
position composition may have drifted due to fees and additional LP adds:

    hodl_value_pls = pooled_a_0 * price_a_now + pooled_b_0 * price_b_now
    lp_value_pls   = pooled_a_now * price_a_now + pooled_b_now * price_b_now
    il_pls         = lp_value_pls - hodl_value_pls

When either price is zero in either snapshot, IL is reported as None.
"""

from __future__ import annotations

from ..core.log_names import get_logger
from .lp_fees import LPPosition

log = get_logger(__name__)


def _price_divergence_pct(price_a_0: float, price_b_0: float,
                          price_a_now: float, price_b_now: float) -> float | None:
    """Return |Δr|% where r = (price_a/price_b) ratio change since baseline."""
    if price_a_0 <= 0 or price_b_0 <= 0 or price_a_now <= 0 or price_b_now <= 0:
        return None
    r0 = price_a_0 / price_b_0
    rn = price_a_now / price_b_now
    if r0 <= 0:
        return None
    return ((rn / r0) - 1.0) * 100.0


def compute_il_report(baseline_dict: dict,
                      current_positions: list[LPPosition]) -> list[dict]:
    """
    Compute per-pair IL decomposition.

    Args:
        baseline_dict: the payload returned by lp_fees.load_baseline()
                       (with "baselines" key), or just the inner dict.
        current_positions: list of LPPosition from scan_joey_lp_positions().

    Returns a list of dicts, one per pair in current_positions that has a
    baseline entry. Missing pairs are skipped.
    """
    if not baseline_dict:
        return []

    bl_map = baseline_dict.get("baselines", baseline_dict)
    out: list[dict] = []

    for pos in current_positions:
        key = pos.pair_addr.lower()
        bl = bl_map.get(key)
        if not bl:
            continue

        label = f"{pos.symbol_a}/{pos.symbol_b}"

        price_a_0 = float(bl.get("price_a_pls", 0) or 0)
        price_b_0 = float(bl.get("price_b_pls", 0) or 0)
        price_a_now = float(pos.price_a_pls or 0)
        price_b_now = float(pos.price_b_pls or 0)

        pooled_a_0 = int(bl.get("pooled_a", 0) or 0)
        pooled_b_0 = int(bl.get("pooled_b", 0) or 0)
        bl_value = float(bl.get("value_pls", 0) or 0)
        bl_k = float(bl.get("k_per_lp", 0) or 0)

        pooled_a_now = pos.pooled_a
        pooled_b_now = pos.pooled_b

        # Fee signal from k_growth × baseline value. Matches
        # lp_fees.compute_fee_accrual fees_low derivation: value growth ratio
        # equals k_per_lp growth ratio for a fixed LP share at ~stable prices.
        # Prior version multiplied by 2 — factor already absorbed in bl_value.
        if bl_k > 0:
            growth = (pos.k_per_lp / bl_k) - 1.0
            fees_earned_pls = bl_value * growth
        else:
            fees_earned_pls = 0.0

        missing_price = (price_a_0 <= 0 or price_b_0 <= 0
                         or price_a_now <= 0 or price_b_now <= 0)

        if missing_price:
            out.append({
                "pair": pos.pair_addr,
                "label": label,
                "il_pls": None,
                "hodl_value_pls": None,
                "lp_value_pls": None,
                "fees_earned_pls": fees_earned_pls,
                "net_delta_pls": pos.value_pls - bl_value,
                "price_divergence_pct": None,
                "note": "missing_price_route",
            })
            continue

        hodl_value_pls = (pooled_a_0 / 1e18) * price_a_now + (pooled_b_0 / 1e18) * price_b_now
        lp_value_pls = (pooled_a_now / 1e18) * price_a_now + (pooled_b_now / 1e18) * price_b_now
        il_pls = lp_value_pls - hodl_value_pls
        net_delta_pls = pos.value_pls - bl_value
        divergence_pct = _price_divergence_pct(price_a_0, price_b_0,
                                               price_a_now, price_b_now)

        out.append({
            "pair": pos.pair_addr,
            "label": label,
            "il_pls": il_pls,
            "hodl_value_pls": hodl_value_pls,
            "lp_value_pls": lp_value_pls,
            "fees_earned_pls": fees_earned_pls,
            "net_delta_pls": net_delta_pls,
            "price_divergence_pct": divergence_pct,
            "note": None,
        })

    return out
