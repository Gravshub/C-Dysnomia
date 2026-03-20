"""
/tgsv8 — TGSv8 + TGSv8+ contract state.
Ownership, auth, registry, balances, reference addresses.
"""

import logging
from fastapi import APIRouter
from ..models import (
    TGSv8Response, TGSv8AuthStatus,
    TGSv8PlusResponse, TGSv8PlusAuthStatus, TGSv8PlusStats,
    ContractsResponse,
)
from ..chain_reader import get_reader
from .. import config

router = APIRouter()
logger = logging.getLogger("joystick.routes.tgsv8")


def _build_tgsv8() -> TGSv8Response:
    """Fetch TGSv8 state from chain."""
    try:
        reader = get_reader()
        state = reader.get_tgsv8_state()
        return TGSv8Response(
            address=state["address"],
            owner=state.get("owner"),
            owner_is_joey=state.get("owner_is_joey", False),
            paused=state.get("paused", False),
            authorized=TGSv8AuthStatus(**state.get("authorized", {})),
            op_nonce=state.get("op_nonce", 0),
            registry_len=state.get("registry_len", 0),
            max_batch=state.get("max_batch", 0),
            native_pls=state.get("native_pls", 0.0),
            token_balances=state.get("token_balances", {}),
            refs=state.get("refs", {}),
            refs_valid=state.get("refs_valid", False),
        )
    except Exception as e:
        logger.error(f"Failed to fetch TGSv8 state: {e}")
        return TGSv8Response(address=config.TGSV8)


def _build_tgsv8plus() -> TGSv8PlusResponse:
    """Fetch TGSv8+ state from chain."""
    try:
        reader = get_reader()
        state = reader.get_tgsv8plus_state()
        return TGSv8PlusResponse(
            address=state["address"],
            owner=state.get("owner"),
            owner_is_joey=state.get("owner_is_joey", False),
            authorized=TGSv8PlusAuthStatus(**state.get("authorized", {})),
            stats=TGSv8PlusStats(**state.get("stats", {})),
            native_pls=state.get("native_pls", 0.0),
            token_balances=state.get("token_balances", {}),
            refs=state.get("refs", {}),
            refs_valid=state.get("refs_valid", False),
        )
    except Exception as e:
        logger.error(f"Failed to fetch TGSv8+ state: {e}")
        return TGSv8PlusResponse(address=config.TGSV8PLUS)


@router.get("/tgsv8", response_model=TGSv8Response)
async def get_tgsv8():
    """TGSv8 execution contract state — ownership, auth, registry, balances."""
    return _build_tgsv8()


@router.get("/tgsv8plus", response_model=TGSv8PlusResponse)
async def get_tgsv8plus():
    """TGSv8+ companion contract state — ownership, auth, stats, balances."""
    return _build_tgsv8plus()


@router.get("/contracts", response_model=ContractsResponse)
async def get_contracts():
    """Combined TGSv8 + TGSv8+ state in one call."""
    return ContractsResponse(
        tgsv8=_build_tgsv8(),
        tgsv8plus=_build_tgsv8plus(),
    )
