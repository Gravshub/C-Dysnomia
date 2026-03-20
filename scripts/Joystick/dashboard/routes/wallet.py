"""
/wallet — Joey's wallet state.
PLS balance, validator progress, gas buffer status, token holdings.
"""

from fastapi import APIRouter
from ..models import WalletResponse, TokenBalance
from ..chain_reader import get_reader
from .. import config

router = APIRouter()


def _wei_to_human(wei: int, decimals: int = 18) -> float:
    """Convert wei to human-readable float."""
    return wei / (10 ** decimals)


@router.get("/wallet", response_model=WalletResponse)
async def get_wallet():
    reader = get_reader()
    snapshot = reader.get_dashboard_snapshot()

    balances = snapshot["balances"]
    pls_wei = balances.get("PLS", 0)
    pls_human = _wei_to_human(pls_wei)

    # Validator progress
    progress = (pls_human / config.VALIDATOR_TARGET_PLS) * 100

    # Token balances (ERC20)
    tokens = []
    for sym, wei_bal in balances.items():
        if sym == "PLS":
            continue
        tokens.append(TokenBalance(
            symbol=sym,
            balance=round(_wei_to_human(wei_bal), 4),
            balance_wei=str(wei_bal),
            pls_value=None,  # TODO: price oracle integration
            usd_value=None,
        ))

    # TGSv8 contract balance
    tgsv8_pls = _wei_to_human(snapshot.get("tgsv8_pls_wei", 0))

    return WalletResponse(
        address=config.JOEY_WALLET,
        pls_balance=round(pls_human, 2),
        pls_balance_wei=str(pls_wei),
        pls_usd=None,          # TODO: PLS/USD price feed
        pls_price_usd=None,
        validator_target=config.VALIDATOR_TARGET_PLS,
        validator_progress_pct=round(progress, 4),
        gas_buffer_ok=pls_human >= config.GAS_BUFFER_FLOOR,
        tokens=tokens,
        tgsv8_balance_pls=round(tgsv8_pls, 4),
        block_number=snapshot["block_number"],
    )
