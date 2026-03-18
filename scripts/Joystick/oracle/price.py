"""
price.py — Live DEX price queries via PulseX V1/V2 routers.

All prices return amounts in wei (int) unless _human suffix is used.
V1 router is default for most queries; V2 added for cross-pair graph arb.
"""
import logging

from ..core.log_names import get_logger
from typing import Sequence

from web3 import Web3

from ..core.config import WPLS, AFFECTION, PULSEX_V1_ROUTER, PULSEX_V2_ROUTER
from ..core.chain import router_contract, safe, w3_read, factory_contract, pair_contract
from ..core.config import PULSEX_V1_FACTORY, PULSEX_V2_FACTORY

log = get_logger(__name__)

# V2 router ABI (same interface as V1 for getAmountsOut)
_v2_router = None


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


def get_amounts_out_v2(amount_in: int, path: Sequence[str]) -> list[int] | None:
    """
    Query PulseX V2 router.getAmountsOut.
    Separate function because V1 and V2 routers have different pair sets.
    """
    global _v2_router
    if _v2_router is None:
        from ..core.chain import ROUTER_ABI
        _v2_router = w3_read.eth.contract(
            address=Web3.to_checksum_address(PULSEX_V2_ROUTER), abi=ROUTER_ABI
        )
    path_checksum = [Web3.to_checksum_address(a) for a in path]
    result = safe(_v2_router, "getAmountsOut", amount_in, path_checksum)
    return list(result) if result else None


def get_reserves(token_a: str, token_b: str, factory: str = "V1") -> tuple[int, int] | None:
    """
    Get raw reserves for a pair from a specific factory.
    Returns (reserve_a, reserve_b) normalized so token_a's reserve is first.
    Returns None if no pair exists.
    """
    factory_addr = PULSEX_V1_FACTORY if factory == "V1" else PULSEX_V2_FACTORY
    fc = factory_contract(factory_addr)
    pair_addr = safe(fc, "getPair", Web3.to_checksum_address(token_a), Web3.to_checksum_address(token_b))
    if not pair_addr or pair_addr == "0x" + "0" * 40:
        return None
    pc = pair_contract(pair_addr)
    reserves = safe(pc, "getReserves")
    if not reserves:
        return None
    t0 = safe(pc, "token0")
    if t0 is None:
        return None
    token_a_cs = Web3.to_checksum_address(token_a)
    if t0.lower() == token_a_cs.lower():
        return (reserves[0], reserves[1])
    else:
        return (reserves[1], reserves[0])


def simulate_swap_exact(amount_in: int, reserve_in: int, reserve_out: int) -> int:
    """
    Pure Uniswap v2 output calculation — no RPC call.
    Used by graph.py for fast cycle scoring.

    out = (amount_in * 997 * reserve_out) / (reserve_in * 1000 + amount_in * 997)
    """
    if reserve_in == 0 or reserve_out == 0 or amount_in == 0:
        return 0
    amount_in_with_fee = amount_in * 997
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in * 1000 + amount_in_with_fee
    return numerator // denominator


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
