"""
profitability.py — Economic gate: is an arb opportunity actually profitable?

Uses the exact Uniswap v2 constant-product formula for price impact.
Spot price alone is misleading for thin pools — the actual output after
price impact can eliminate the profit. This module computes exact expected output.

Formula (Uniswap v2 amountOut with 0.3% fee):
    amount_out = (reserve_out * amount_in * 997) / (reserve_in * 1000 + amount_in * 997)
"""
import logging
from decimal import Decimal, getcontext

from ..core.chain import w3_read

getcontext().prec = 28
log = logging.getLogger(__name__)


def uniswap_v2_out(
    amount_in: int,
    reserve_in: int,
    reserve_out: int,
) -> int:
    """
    Exact Uniswap v2 output calculation with 0.3% fee.

    Args:
        amount_in:   Input amount in wei
        reserve_in:  DEX reserve of input token (wei)
        reserve_out: DEX reserve of output token (wei)

    Returns:
        Expected output amount in wei (0 if reserves are zero)
    """
    if reserve_in == 0 or reserve_out == 0 or amount_in == 0:
        return 0
    amount_in_with_fee = amount_in * 997
    numerator   = amount_in_with_fee * reserve_out
    denominator = reserve_in * 1000 + amount_in_with_fee
    return numerator // denominator


def price_impact_pct(amount_in: int, reserve_in: int) -> float:
    """
    Estimate price impact as a percentage of the pool.
    High impact (> 2-3%) means the trade materially moves the price.
    """
    if reserve_in == 0:
        return 100.0
    return (amount_in / reserve_in) * 100.0


def arb_profit(
    token_record: dict,
    gas_cost_wei: int,
) -> dict:
    """
    Compute precise expected profit for one arb opportunity.

    token_record is a dict from scanner.scan_tokens() with keys:
        address, rate, payment, r_token, r_wpls, self_bal

    gas_cost_wei: estimated gas cost in wei for the full arb TX sequence

    Returns dict with:
        profitable: bool
        profit_wei: expected net profit in wei (negative if unprofitable)
        token_amount: recommended purchase amount in wei
        payment_cost_wei: cost in payment tokens (wei)
        dex_out_wei: expected DEX output in wei
        gas_wei: gas cost used
        impact_pct: price impact percentage
        reason: human-readable explanation
    """
    rate    = token_record["rate"]      # payment tokens per target token (1e18 units)
    r_tok   = token_record["r_token"]   # DEX reserve: target token
    r_wpls  = token_record["r_wpls"]    # DEX reserve: WPLS
    self_bal = token_record["self_bal"] # Contract's own token balance (purchaseable)

    # We can only buy what the contract holds
    # Also cap at what the DEX can absorb (< 10% of pool to limit impact)
    max_by_pool   = r_tok // 10  # 10% pool depth cap
    token_amount  = min(self_bal, max_by_pool)

    if token_amount == 0:
        return {
            "profitable": False, "profit_wei": 0, "token_amount": 0,
            "reason": "No tokens available to purchase",
        }

    # Cost in payment tokens
    payment_cost = token_amount * rate // 10**18

    # Payment tokens → PLS cost (using spot price approximation for payment side)
    # For AFFECTION: use its r_wpls/r_token from a separate pair call
    # For now: use simple getAmountsOut from oracle (imported lazily to avoid circular)
    from .price import get_amounts_out
    from ..core.config import WPLS

    payment_path = [token_record["payment"], WPLS]
    payment_amounts = get_amounts_out(payment_cost, payment_path)
    payment_pls = payment_amounts[-1] if payment_amounts else 0

    # DEX output using exact Uniswap v2 formula
    dex_out = uniswap_v2_out(token_amount, r_tok, r_wpls)
    impact  = price_impact_pct(token_amount, r_tok)

    net_profit = dex_out - payment_pls - gas_cost_wei

    result = {
        "profitable":       net_profit > 0,
        "profit_wei":       net_profit,
        "token_amount":     token_amount,
        "payment_cost_wei": payment_cost,
        "dex_out_wei":      dex_out,
        "payment_pls_wei":  payment_pls,
        "gas_wei":          gas_cost_wei,
        "impact_pct":       impact,
        "reason":           "",
    }

    if net_profit <= 0:
        result["reason"] = (
            f"Unprofitable: dex_out {dex_out/1e18:.4f} PLS "
            f"< payment_pls {payment_pls/1e18:.4f} + gas {gas_cost_wei/1e18:.4f}"
        )
    elif impact > 5.0:
        result["reason"] = f"High impact trade ({impact:.1f}% of pool) — proceed with caution"
    else:
        result["reason"] = (
            f"Profit: {net_profit/1e18:.4f} PLS "
            f"(dex {dex_out/1e18:.4f} - cost {payment_pls/1e18:.4f} - gas {gas_cost_wei/1e18:.4f})"
        )

    return result


def rank_opportunities(
    token_records: list[dict],
    gas_cost_wei: int,
) -> list[dict]:
    """
    Evaluate all token records, compute profit for each, filter unprofitable,
    sort by profit descending.

    Returns list of dicts combining token_record + arb_profit output.
    """
    ranked = []
    for record in token_records:
        profit_info = arb_profit(record, gas_cost_wei)
        if profit_info["profitable"]:
            ranked.append({**record, **profit_info})

    ranked.sort(key=lambda r: r["profit_wei"], reverse=True)
    return ranked
