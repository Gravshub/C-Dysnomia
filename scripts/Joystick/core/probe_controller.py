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

from dataclasses import dataclass, field
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
