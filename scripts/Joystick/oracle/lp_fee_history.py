"""
lp_fee_history.py — Time-series persistence for GIBS LP fee accrual.

Stores snapshots of scanned LP positions so we can chart fee growth over
time. Reads from (but does not modify) lp_fees.py — consumes LPPosition
instances produced by scan_joey_lp_positions().

Schema (data/lp_fee_history.json):
    {
      "schema_version": 1,
      "snapshots": [
        {
          "ts": "...iso...",
          "block": 26149418,
          "per_pair": {
            "<pair_addr_lowercase>": {
              "k_per_lp": float,
              "lp_balance": str,      # wei
              "pooled_a_wei": str,
              "pooled_b_wei": str,
              "value_pls": float
            },
            ...
          },
          "totals": {"value_pls": float}
        },
        ...
      ]
    }

Pruning: keeps only the most recent MAX_SNAPSHOTS entries on write.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from ..core.log_names import get_logger
from .lp_fees import HISTORY_PATH, LPPosition

log = get_logger(__name__)

MAX_SNAPSHOTS = 10_000


def _atomic_write_json(path: str, data: dict) -> None:
    # mkstemp creates files with mode 600 — chmod to 664 so the dashboard
    # (running as the joystick user) can read files the bot writes (as joey).
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load_raw(path: str = HISTORY_PATH) -> dict:
    if not os.path.exists(path):
        return {"schema_version": 1, "snapshots": []}
    try:
        with open(path) as f:
            data = json.load(f)
        if "snapshots" not in data:
            data["snapshots"] = []
        return data
    except Exception as exc:
        log.warning("lp_fee_history: corrupt file, starting fresh: %s", exc)
        return {"schema_version": 1, "snapshots": []}


def record_snapshot(positions: list[LPPosition], path: str = HISTORY_PATH) -> None:
    """Append one snapshot of the current LP positions, atomically."""
    if not positions:
        return

    snap_block = 0
    snap_ts = datetime.now(timezone.utc).isoformat()
    per_pair: dict[str, dict] = {}
    total_value = 0.0

    for p in positions:
        snap_block = max(snap_block, p.snapshot_block)
        per_pair[p.pair_addr.lower()] = {
            "k_per_lp": p.k_per_lp,
            "lp_balance": str(p.lp_balance),
            "pooled_a_wei": str(p.pooled_a),
            "pooled_b_wei": str(p.pooled_b),
            "value_pls": p.value_pls,
            "symbol_a": p.symbol_a,
            "symbol_b": p.symbol_b,
        }
        total_value += p.value_pls

    snapshot = {
        "ts": snap_ts,
        "block": snap_block,
        "per_pair": per_pair,
        "totals": {"value_pls": total_value},
    }

    data = _load_raw(path)
    data["snapshots"].append(snapshot)

    if len(data["snapshots"]) > MAX_SNAPSHOTS:
        data["snapshots"] = data["snapshots"][-MAX_SNAPSHOTS:]

    _atomic_write_json(path, data)
    log.info("lp_fee_history: recorded snapshot — %d pairs, total %.2f PLS",
             len(per_pair), total_value)


def load_history(max_entries: int = 1000, path: str = HISTORY_PATH) -> list[dict]:
    """Return the most recent max_entries snapshots (oldest first)."""
    data = _load_raw(path)
    snaps = data.get("snapshots", [])
    if max_entries and len(snaps) > max_entries:
        snaps = snaps[-max_entries:]
    return snaps


def compute_history_deltas(history: list[dict], baseline_k_map: dict) -> list[dict]:
    """
    For each snapshot, compute per-pair fee delta vs baseline using k_per_lp
    growth × baseline value. Returns chart-ready rows.

    baseline_k_map: {pair_addr_lower: {"k_per_lp": float, "value_pls": float}}
                    (usually derived from lp_fees.load_baseline()["baselines"])
    """
    out: list[dict] = []
    for snap in history:
        per_pair = snap.get("per_pair", {})
        per_pair_fees: dict[str, float] = {}
        total_fees = 0.0
        for addr, entry in per_pair.items():
            bl = baseline_k_map.get(addr)
            if not bl:
                continue
            bl_k = float(bl.get("k_per_lp", 0) or 0)
            if bl_k <= 0:
                continue
            cur_k = float(entry.get("k_per_lp", 0) or 0)
            growth = (cur_k / bl_k) - 1.0
            bl_value = float(bl.get("value_pls", 0) or 0)
            # Matches lp_fees.compute_fee_accrual fees_low derivation.
            # Prior version multiplied by 2 — that factor is already absorbed
            # in bl_value via both-sides-of-pool summation at equilibrium.
            fee_pls = bl_value * growth
            per_pair_fees[addr] = fee_pls
            total_fees += fee_pls
        out.append({
            "ts": snap.get("ts"),
            "block": snap.get("block", 0),
            "per_pair_fees": per_pair_fees,
            "total_fees_pls": total_fees,
        })
    return out
