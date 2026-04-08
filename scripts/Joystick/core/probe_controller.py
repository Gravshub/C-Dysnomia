"""
probe_controller.py — Adaptive sell-sizing advisor for E2 CEREAL.

Finds the minimum sell size that attracts external arb bot responses on
GIBS/WPLS, locks onto it, re-probes when conditions change, and triggers
LP-add follow-ups sized to match each successful arb.

This module is a pure advisor — E2 still owns all TX submission. See
docs/superpowers/specs/2026-04-08-adaptive-probe-controller-design.md
for the full design.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ProbeMode(str, Enum):
    PROBING = "PROBING"
    LOCKED = "LOCKED"
    RE_PROBING = "RE_PROBING"
    CAPPED = "CAPPED"
    PAUSED = "PAUSED"


class ArbResponseKind(str, Enum):
    PENDING = "PENDING"
    ARB_DETECTED = "ARB_DETECTED"
    NO_RESPONSE = "NO_RESPONSE"


@dataclass
class ArbResponse:
    kind: ArbResponseKind
    gibs_size_wei: Optional[int] = None
    tx_hash: Optional[str] = None
    block: Optional[int] = None
    sender: Optional[str] = None


@dataclass
class PendingSell:
    sell_gibs_wei: int
    sell_block: int
    sell_tx_hash: str
    impact_pct_at_sell: float
    deadline_block: int


@dataclass
class ProbeState:
    mode: ProbeMode
    probe_pct: float
    sweet_spot_pct: Optional[float]
    consecutive_failures: int
    capped_entry_block: Optional[int]
    paused_entry_block: Optional[int]
    cap_loop_count: int
    lp_add_failure_count: int
    pending_sell: Optional[PendingSell]
    last_arb_gibs: Optional[int]
    last_transition_ts: str


def solve_for_impact(impact_pct: float, reserves: tuple[int, int]) -> int:
    """
    Solve for the GIBS amount (wei) that produces a given price impact %
    on a Uniswap v2 pool.

    Args:
        impact_pct: target price impact as a percentage (e.g. 0.3 for 0.3%)
        reserves: (R_gibs_wei, R_wpls_wei) — the pool's GIBS and WPLS sides

    Returns:
        GIBS amount in wei to sell. Zero if impact_pct is zero.

    Raises:
        ValueError: impact_pct < 0 or any reserve is zero/negative.

    Math:
        x_gibs = R_gibs × (sqrt(1 + p) − 1) / 0.997

        This is the exact algebraic inverse of the squared reserve-ratio
        impact definition: p = 1 − (R_gibs / (R_gibs + x·0.997))²

        The formula consistently under-delivers vs execution-price impact
        by p/(1+p): at 5% target it produces ~4.76% execution impact, at
        10% target ~9.09%. For our arb-attraction use case this is in the
        safe direction — we sell slightly smaller than requested.

        Only R_gibs enters the formula; R_wpls is validated for pool sanity
        but does not affect the output.
    """
    if impact_pct < 0:
        raise ValueError(f"impact_pct must be non-negative, got {impact_pct}")
    if impact_pct == 0:
        return 0
    R_gibs, R_wpls = reserves
    if R_gibs <= 0 or R_wpls <= 0:
        raise ValueError(f"reserves must be positive, got {reserves}")
    p = impact_pct / 100.0
    x_gibs = R_gibs * (math.sqrt(1.0 + p) - 1.0) / 0.997
    return int(x_gibs)


# Path constant for the live state file. Tests pass an explicit path.
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STATE_PATH = os.path.join(_DATA_DIR, "probe_state.json")
SCHEMA_VERSION = 1


def _atomic_write_json(path: str, data: dict) -> None:
    """
    Atomic write via tempfile + rename. Sets mode 0o664 so the dashboard
    (running as joystick user) can read files the bot writes (as joey).
    """
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


def _state_to_dict(state: ProbeState) -> dict:
    """Serialize ProbeState to a JSON-friendly dict."""
    d = asdict(state)
    # Enum and int conversions for JSON compatibility
    d["mode"] = state.mode.value
    if state.last_arb_gibs is not None:
        d["last_arb_gibs"] = str(state.last_arb_gibs)
    if state.pending_sell is not None:
        d["pending_sell"]["sell_gibs_wei"] = str(state.pending_sell.sell_gibs_wei)
    return d


def _state_from_dict(d: dict) -> ProbeState:
    """Deserialize a dict back to ProbeState. Raises on invalid shape."""
    pending_d = d.get("pending_sell")
    pending = None
    if pending_d is not None:
        pending = PendingSell(
            sell_gibs_wei=int(pending_d["sell_gibs_wei"]),
            sell_block=int(pending_d["sell_block"]),
            sell_tx_hash=pending_d["sell_tx_hash"],
            impact_pct_at_sell=float(pending_d["impact_pct_at_sell"]),
            deadline_block=int(pending_d["deadline_block"]),
        )
    last_arb = d.get("last_arb_gibs")
    if last_arb is not None:
        last_arb = int(last_arb)
    return ProbeState(
        mode=ProbeMode(d["mode"]),
        probe_pct=float(d["probe_pct"]),
        sweet_spot_pct=d.get("sweet_spot_pct"),
        consecutive_failures=int(d["consecutive_failures"]),
        capped_entry_block=d.get("capped_entry_block"),
        paused_entry_block=d.get("paused_entry_block"),
        cap_loop_count=int(d["cap_loop_count"]),
        lp_add_failure_count=int(d["lp_add_failure_count"]),
        pending_sell=pending,
        last_arb_gibs=last_arb,
        last_transition_ts=d["last_transition_ts"],
    )


def save_state(state: ProbeState, path: str = STATE_PATH) -> None:
    """Persist a ProbeState atomically to disk."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "state": _state_to_dict(state),
    }
    _atomic_write_json(path, payload)


def load_state(path: str = STATE_PATH) -> Optional[ProbeState]:
    """
    Load a ProbeState from disk.

    Returns None if:
      - File does not exist
      - File is unparseable (renamed to .broken-<ts> for forensics)
      - Schema version is unknown (treated as corrupt, also renamed)
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unknown schema_version {payload.get('schema_version')}")
        return _state_from_dict(payload["state"])
    except Exception:
        # Rename to .broken-<ts> sidecar
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        broken = f"{path}.broken-{ts}"
        try:
            os.rename(path, broken)
        except OSError:
            pass
        return None
