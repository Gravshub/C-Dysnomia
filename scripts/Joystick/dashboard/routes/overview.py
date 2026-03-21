"""
/overview — Single-call dashboard payload.
Returns wallet + engines + gas + strategy in one response.
This is what the frontend polls every N seconds.
"""

import json
import logging
from pathlib import Path
from fastapi import APIRouter
from ..models import (
    OverviewResponse, WalletResponse, TokenBalance,
    EnginesResponse, GasResponse, GasCondition,
    StrategyResponse, TxRecord,
    MintEconomics, WmMintEconomics, AffMintEconomics, AffRouteEconomics,
)
from ..chain_reader import get_reader
from ..routes.engines import _load_bot_state, KNOWN_STATES
from ..routes.tgsv8 import _build_tgsv8, _build_tgsv8plus
from ..models import EngineInfo, EngineStatus
from .. import config
from .. import history

router = APIRouter()
logger = logging.getLogger("joystick.routes.overview")


def _wei_to_human(wei: int, decimals: int = 18) -> float:
    return wei / (10 ** decimals)


def _build_wallet(snapshot: dict) -> WalletResponse:
    """Build wallet response from chain snapshot."""
    balances = snapshot["balances"]
    pls_wei = balances.get("PLS", 0)
    pls_human = _wei_to_human(pls_wei)
    progress = (pls_human / config.VALIDATOR_TARGET_PLS) * 100

    tokens = []
    for sym, wei_bal in balances.items():
        if sym == "PLS":
            continue
        tokens.append(TokenBalance(
            symbol=sym,
            balance=round(_wei_to_human(wei_bal), 4),
            balance_wei=str(wei_bal),
        ))

    tgsv8_pls = _wei_to_human(snapshot.get("tgsv8_pls_wei", 0))

    return WalletResponse(
        address=config.JOEY_WALLET,
        pls_balance=round(pls_human, 2),
        pls_balance_wei=str(pls_wei),
        validator_target=config.VALIDATOR_TARGET_PLS,
        validator_progress_pct=round(progress, 4),
        gas_buffer_ok=pls_human >= config.GAS_BUFFER_FLOOR,
        tokens=tokens,
        tgsv8_balance_pls=round(tgsv8_pls, 4),
        block_number=snapshot["block_number"],
    )


def _build_gas(snapshot: dict, reader=None) -> GasResponse:
    """Build gas response from chain snapshot, including live mint economics."""
    gas_beats = snapshot["gas_price_beats"]
    ceiling = config.GAS_CEILING_BEATS

    if gas_beats > ceiling:
        condition = GasCondition.SKIP
    elif gas_beats > ceiling * 0.75:
        condition = GasCondition.CAUTION
    else:
        condition = GasCondition.CLEAR

    # Live mint economics
    mint_data = None
    if reader:
        try:
            raw = reader.get_mint_economics(snapshot["gas_price_impulses"])
            wm = raw["wm"]
            aff = raw["aff"]
            mint_data = MintEconomics(
                wm=WmMintEconomics(**wm),
                aff=AffMintEconomics(
                    dex_value=aff["dex_value"],
                    cheapest_route=aff.get("cheapest_route"),
                    cheapest_cost=aff.get("cheapest_cost"),
                    routes=[AffRouteEconomics(**r) for r in aff.get("routes", [])],
                ),
            )
        except Exception as e:
            logger.warning(f"Mint economics failed: {e}")

    return GasResponse(
        gas_price_beats=round(gas_beats, 2),
        gas_price_impulses=snapshot["gas_price_impulses"],
        gas_ceiling_beats=ceiling,
        condition=condition,
        aff_breakeven_beats=38.0,
        block_number=snapshot["block_number"],
        mint=mint_data,
    )


def _build_engines(bot_state: dict | None) -> EnginesResponse:
    """Build engines response from bot state or known fallbacks."""
    engines = []
    for eng_def in config.ENGINES:
        eid = eng_def["id"]
        state = KNOWN_STATES.get(eid, {})

        if bot_state and eid in bot_state:
            bs = bot_state[eid]
            state = {
                "status": EngineStatus(bs.get("status", state.get("status", "disabled"))),
                "enabled": bs.get("enabled", state.get("enabled", False)),
                "roi_pct": bs.get("roi_pct"),
                "total_earned_pls": bs.get("total_earned_pls"),
                "last_run_block": bs.get("last_run_block"),
                "last_run_profit_pls": bs.get("last_run_profit_pls"),
                "error": bs.get("error"),
            }

        engines.append(EngineInfo(
            id=eid,
            name=eng_def["name"],
            engine_type=eng_def["type"],
            description=eng_def["description"],
            status=state.get("status", EngineStatus.DISABLED),
            enabled=state.get("enabled", False),
            roi_pct=state.get("roi_pct"),
            total_earned_pls=state.get("total_earned_pls"),
            last_run_block=state.get("last_run_block"),
            last_run_profit_pls=state.get("last_run_profit_pls"),
            error=state.get("error"),
        ))

    active = None
    best_roi = float("-inf")
    for eng in engines:
        if eng.enabled and eng.status == EngineStatus.RUNNING and eng.roi_pct is not None:
            if eng.roi_pct > best_roi:
                best_roi = eng.roi_pct
                active = eng.id

    return EnginesResponse(
        engines=engines,
        active_engine=active,
        cycle_count=bot_state.get("cycle_count", 0) if bot_state else 0,
    )


def _build_strategy() -> StrategyResponse:
    """Current active strategy. Hardcoded to Strat F for now.
    TODO: Read from bot's strategist state when available.
    """
    return StrategyResponse(
        active_strategy="STRAT_F",
        strategy_name="AFF generate",
        description="multiGenerate(100) → AFF → sell on DEX",
        gas_cost_pls=4273,
        expected_yield_pls=15450,
        net_pls=11177,
        roi_pct=262.0,
        notes="82% of 1B AFF supply still mintable. No tax.",
    )


def _load_recent_txs(limit: int = 10) -> list[TxRecord]:
    """Load recent transactions from bot's TX log file."""
    if not config.TX_LOG_FILE:
        return []

    path = Path(config.TX_LOG_FILE)
    if not path.exists():
        return []

    try:
        with open(path, "r") as f:
            txs = json.load(f)
        # Take the most recent N
        recent = txs[-limit:] if len(txs) > limit else txs
        recent.reverse()  # newest first
        return [TxRecord(**tx) for tx in recent]
    except Exception as e:
        logger.warning(f"Could not load TX log: {e}")
        return []


@router.get("/overview", response_model=OverviewResponse)
async def get_overview():
    """Single endpoint for the entire dashboard.

    Makes ~4 RPC round-trips for wallet + gas data,
    plus additional multicall batches for TGSv8 and TGSv8+.
    Also records a balance history point every 15 minutes.
    """
    reader = get_reader()
    snapshot = reader.get_dashboard_snapshot()
    bot_state = _load_bot_state()

    wallet_resp = _build_wallet(snapshot)
    tgsv8_resp = _build_tgsv8()
    tgsv8plus_resp = _build_tgsv8plus()

    # Record balance history point (every 15 min)
    history.maybe_record({
        "block": snapshot["block_number"],
        "joey_pls": wallet_resp.pls_balance,
        "tgsv8_pls": tgsv8_resp.native_pls,
        "tgsv8plus_pls": tgsv8plus_resp.native_pls,
        "total_pls": wallet_resp.pls_balance + tgsv8_resp.native_pls + tgsv8plus_resp.native_pls,
        "gibs_price": None,  # TODO: wire up GIBS price oracle
        "gas_beats": snapshot["gas_price_beats"],
    })

    return OverviewResponse(
        wallet=wallet_resp,
        engines=_build_engines(bot_state),
        gas=_build_gas(snapshot, reader=reader),
        strategy=_build_strategy(),
        tgsv8=tgsv8_resp,
        tgsv8plus=tgsv8plus_resp,
        recent_txs=_load_recent_txs(),
        poll_interval_sec=config.POLL_INTERVAL_SEC,
        bot_online=bot_state is not None,
    )
