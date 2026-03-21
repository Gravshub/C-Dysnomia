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
                  total_pls, gibs_price, gas_beats, block,
                  and optionally token_prices, portfolio_value_pls.
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
    # Portfolio extensions
    if snapshot.get("token_prices"):
        record["token_prices"] = snapshot["token_prices"]
    if snapshot.get("portfolio_value_pls"):
        record["portfolio_value_pls"] = snapshot["portfolio_value_pls"]

    records = _load()
    records.append(record)
    records = _prune(records)
    _save(records)
    _last_record_ts = now
    logger.info(f"History recorded: total_pls={record['total_pls']:.2f} ({len(records)} points)")


def get_history(span_seconds: int = None) -> list[dict]:
    """Return records within the given time span, sorted by timestamp.

    Args:
        span_seconds: How far back to look (default: HISTORY_MAX_AGE from config).
    """
    records = _load()
    records = _prune(records)  # always prune stale data on read
    if span_seconds is not None:
        cutoff = time.time() - span_seconds
        records = [r for r in records if r.get("ts", 0) >= cutoff]
    return records


def get_snapshot_24h_ago() -> dict | None:
    """Return the history record closest to 24h ago, or None."""
    records = _load()
    target = time.time() - 86400
    closest = None
    min_diff = float('inf')
    for r in records:
        diff = abs(r.get("ts", 0) - target)
        if diff < min_diff:
            min_diff = diff
            closest = r
    # Only return if within 2 hours of the target
    return closest if closest and min_diff < 7200 else None


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
