"""
price.py — Live DEX price queries via PulseX V1 router.

All prices return amounts in wei (int) unless _human suffix is used.
Always uses the V1 router — V2 router has incorrect factory reference for many pairs.
"""
import logging
from typing import Sequence

from web3 import Web3

from ..core.config import WPLS, AFFECTION, PULSEX_V1_ROUTER
from ..core.chain import router_contract, safe

log = logging.getLogger(__name__)


def get_amounts_out(amount_in: int, path: Sequence[str]) -> list[int] | None:
    """
    Query PulseX V1 router.getAmountsOut.

    Args:
        amount_in: Input amount in wei
        path: List of token addresses (minimum 2)

    Returns:
        List of amounts [in, ..., out] in wei, or None if pair doesn't exist / call fails.
    """
    router = router_contract()
    path_checksum = [Web3.to_checksum_address(a) for a in path]
    result = safe(router, "getAmountsOut", amount_in, path_checksum)
    return list(result) if result else None


def token_price_pls(token_addr: str, amount: int = 10**18) -> int | None:
    """
    Get how many wei of native PLS you'd receive for `amount` wei of token_addr.
    Path: token → WPLS (direct pair, V1).
    Returns None if no pair or call fails.
    """
    amounts = get_amounts_out(amount, [token_addr, WPLS])
    return amounts[-1] if amounts else None


def token_price_pls_via_affection(token_addr: str, amount: int = 10**18) -> int | None:
    """
    Multi-hop: token → AFFECTION → WPLS.
    Used for tokens that don't have a direct WPLS pair.
    """
    amounts = get_amounts_out(amount, [token_addr, AFFECTION, WPLS])
    return amounts[-1] if amounts else None


def affection_price_pls(amount: int = 10**18) -> int | None:
    """How many wei PLS for `amount` wei AFFECTION (direct pair)."""
    return token_price_pls(AFFECTION, amount)


def pls_price_affection(amount_pls: int = 10**18) -> int | None:
    """How many wei AFFECTION for `amount_pls` wei WPLS (direct pair)."""
    amounts = get_amounts_out(amount_pls, [WPLS, AFFECTION])
    return amounts[-1] if amounts else None


def simulate_arb(
    token_addr: str,
    payment_addr: str,
    token_amount: int,
    market_rate: int,
) -> tuple[int, int] | None:
    """
    Simulate the full arb: payment → Purchase(token) → DEX → PLS.

    Uses exact Uniswap v2 reserves formula for price impact (not just spot price).
    This prevents arbing thin pools where the price impact would eat the profit.

    Args:
        token_addr:    Target token address
        payment_addr:  Payment token (AFFECTION or pDAI)
        token_amount:  Tokens to purchase (in wei)
        market_rate:   GetMarketRate(payment_addr) from the token contract

    Returns:
        (pls_out_wei, payment_cost_pls_wei) or None on failure
    """
    # Cost in payment tokens
    payment_cost = token_amount * market_rate // 10**18

    # What the payment tokens are worth in PLS
    payment_pls = token_price_pls(payment_addr, payment_cost)
    if payment_pls is None:
        # Try via AFFECTION hop
        payment_pls = token_price_pls_via_affection(payment_addr, payment_cost)
    if payment_pls is None:
        return None

    # DEX output for purchased tokens → PLS
    pls_out = token_price_pls(token_addr, token_amount)
    if pls_out is None:
        return None

    return pls_out, payment_pls
