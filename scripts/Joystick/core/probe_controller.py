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

import math
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
