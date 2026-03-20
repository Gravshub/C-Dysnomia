"""
history.py — 24H balance history for the dashboard chart.

Records a snapshot every RECORD_INTERVAL seconds (default 900 = 15 min).
Keeps max 24H of data (96 points). Older entries auto-pruned on write.
File: data/balance_history.json (atomic writes via os.replace).
"""

import json
import logging
import os
import time
from pathlib import Path

from . import config

logger = logging.getLogger("joystick.history")

_last_record_ts: float = 0.0


def maybe_record(snapshot: dict) -> None:
    """Called after every /api/overview fetch. Records if interval elapsed.

    Args:
        snapshot: dict with keys joey_pls, tgsv8_pls, tgsv8plus_pls,
                  total_pls, gibs_price, gas_beats, block.
    """
    global _last_record_ts

    now = time.time()
    if now - _last_record_ts < config.HISTORY_RECORD_INTERVAL:
        return

    record = {
        "ts": int(now),
        "block": snapshot.get("block", 0),
        "joey_pls": snapshot.get("joey_pls", 0.0),
        "tgsv8_pls": snapshot.get("tgsv8_pls", 0.0),
        "tgsv8plus_pls": snapshot.get("tgsv8plus_pls", 0.0),
        "total_pls": snapshot.get("total_pls", 0.0),
        "gibs_price": snapshot.get("gibs_price"),
        "gas_beats": snapshot.get("gas_beats", 0.0),
    }

    records = _load()
    records.append(record)
    records = _prune(records)
    _save(records)
    _last_record_ts = now
    logger.info(f"History recorded: total_pls={record['total_pls']:.2f} ({len(records)} points)")


def get_history() -> list[dict]:
    """Return all records within the last 24H, sorted by timestamp."""
    records = _load()
    return _prune(records)


def _prune(records: list[dict]) -> list[dict]:
    """Remove records older than MAX_AGE_SECONDS."""
    cutoff = time.time() - config.HISTORY_MAX_AGE
    return [r for r in records if r.get("ts", 0) >= cutoff]


def _load() -> list[dict]:
    """Load history from disk."""
    path = config.HISTORY_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.warning(f"Could not load history: {e}")
        return []


def _save(records: list[dict]) -> None:
    """Atomic write to history file."""
    path = config.HISTORY_FILE
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, separators=(",", ":"))
    os.replace(tmp, path)
