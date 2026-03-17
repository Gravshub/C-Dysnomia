"""
/engines — Engine status panel.
Returns status, ROI, earnings for all 8 engines.
Reads from bot's engine_state.json if the bot is running,
otherwise returns static config with status from known state.
"""

import json
import logging
from pathlib import Path
from fastapi import APIRouter
from ..models import EnginesResponse, EngineInfo, EngineStatus
from .. import config

router = APIRouter()
logger = logging.getLogger("joystick.routes.engines")

# ─── Known engine states (fallback when bot isn't running) ───────────
# These reflect the last known state from diary entries / memory.
# When the bot is live, engine_state.json overrides these.
KNOWN_STATES: dict[str, dict] = {
    "E1": {"status": EngineStatus.READY, "enabled": True, "roi_pct": -12.0, "total_earned_pls": 0},
    "E2": {"status": EngineStatus.RUNNING, "enabled": True, "roi_pct": 840.0, "total_earned_pls": 24100},
    "E3": {"status": EngineStatus.RUNNING, "enabled": True, "roi_pct": 62.0, "total_earned_pls": 8300},
    "E4": {"status": EngineStatus.RUNNING, "enabled": True, "roi_pct": 262.0, "total_earned_pls": 142000},
    "E5": {"status": EngineStatus.GATED, "enabled": False},
    "E6": {"status": EngineStatus.RECON, "enabled": False},
    "E7": {"status": EngineStatus.BLOCKED, "enabled": False},
    "E8": {"status": EngineStatus.DESIGN, "enabled": False},
}


def _load_bot_state() -> dict | None:
    """Try to load engine state from bot's data file.
    Returns None if file doesn't exist or is unreadable.
    """
    if not config.ENGINE_STATE_FILE:
        return None

    path = Path(config.ENGINE_STATE_FILE)
    if not path.exists():
        return None

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load engine state: {e}")
        return None


@router.get("/engines", response_model=EnginesResponse)
async def get_engines():
    bot_state = _load_bot_state()

    engines = []
    for eng_def in config.ENGINES:
        eid = eng_def["id"]

        # Start with known fallback state
        state = KNOWN_STATES.get(eid, {})

        # Override with bot state if available
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

    # Determine active engine (highest ROI among running+enabled)
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
