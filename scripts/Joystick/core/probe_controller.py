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
import logging
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from . import config as _config

_log = logging.getLogger(__name__)


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


def _fresh_state() -> ProbeState:
    return ProbeState(
        mode=ProbeMode.PROBING,
        probe_pct=_config.PROBE_BASELINE_PCT,
        sweet_spot_pct=None,
        consecutive_failures=0,
        capped_entry_block=None,
        paused_entry_block=None,
        cap_loop_count=0,
        lp_add_failure_count=0,
        pending_sell=None,
        last_arb_gibs=None,
        last_transition_ts=datetime.now(timezone.utc).isoformat(),
    )


class ProbeController:
    """
    Adaptive sell-sizing advisor for E2 CEREAL.

    Holds the state machine that finds, locks, and re-discovers the minimum
    sell size that triggers external arb bot responses on GIBS/WPLS.
    """

    # Addresses to ignore in arb-detection — our own infrastructure that
    # generates GIBS pool swaps. Lowercase for case-insensitive comparison.
    _SELF_ADDRESSES = {
        "0x17367877af5a8d0eb33ba5689a880f696386e24d",  # Joey wallet
        "0x7bd76a0f7e03a3ba76a621ba0988c7db0adbab14",  # JoystickHub
        "0x165c3410fc91ef562c50559f7d2289febed552d9",  # PulseX V2 Router
    }

    def __init__(self, state_path: str = STATE_PATH):
        self.state_path = state_path
        loaded = load_state(state_path)
        self.state: ProbeState = loaded if loaded is not None else _fresh_state()

    def _persist(self) -> None:
        """
        Write current state to disk. Called on every transition.

        Persistence failures (disk full, permission error, etc.) are logged
        but do not raise — a missed persist is recoverable on the next
        transition, whereas propagating the exception would crash the bot
        main loop for a transient infrastructure issue.
        """
        self.state.last_transition_ts = datetime.now(timezone.utc).isoformat()
        try:
            save_state(self.state, self.state_path)
        except Exception as exc:
            _log.warning(
                "ProbeController._persist failed (state not saved): %s", exc
            )

    def next_sell_gibs(
        self,
        hub_gibs_balance: int,
        pool_reserves: tuple[int, int],
    ) -> int:
        """
        Returns the GIBS amount (wei) E2 should sell this cycle.

        Returns 0 in these cases:
          - hub_gibs_balance is zero (nothing to sell)
          - a previous sell is still within its monitoring window

        In CAPPED or PAUSED modes, returns a sell sized to PROBE_BASELINE_PCT
        (productive fallback). In PROBING/RE_PROBING modes, sized to probe_pct.
        In LOCKED mode, sized to sweet_spot_pct.

        Always capped at hub_gibs_balance.
        """
        if hub_gibs_balance <= 0:
            return 0
        if self.state.pending_sell is not None:
            # One pending sell at a time — return 0 until window resolves
            return 0

        # Determine which impact % to use this call
        if self.state.mode == ProbeMode.LOCKED:
            target_pct = self.state.sweet_spot_pct or _config.PROBE_BASELINE_PCT
        elif self.state.mode in (ProbeMode.CAPPED, ProbeMode.PAUSED):
            target_pct = _config.PROBE_BASELINE_PCT
        else:  # PROBING or RE_PROBING
            target_pct = self.state.probe_pct

        target_wei = solve_for_impact(target_pct, pool_reserves)
        if target_wei > hub_gibs_balance:
            return hub_gibs_balance
        return target_wei

    def record_sell(
        self,
        sell_gibs_wei: int,
        block_number: int,
        tx_hash: str,
    ) -> None:
        """
        Record that E2 has just submitted a sell. Starts the response window.

        Block number MUST come from the TX receipt, not w3.eth.block_number,
        to anchor the deadline correctly.

        Raises RuntimeError if a pending sell is already in progress (caller
        bug — should have called check_arb_response first).
        """
        if self.state.pending_sell is not None:
            raise RuntimeError("pending sell already in progress")
        # The probe_pct or sweet_spot_pct in effect when this sell was sized
        if self.state.mode == ProbeMode.LOCKED:
            impact = self.state.sweet_spot_pct or _config.PROBE_BASELINE_PCT
        elif self.state.mode in (ProbeMode.CAPPED, ProbeMode.PAUSED):
            impact = _config.PROBE_BASELINE_PCT
        else:
            impact = self.state.probe_pct
        self.state.pending_sell = PendingSell(
            sell_gibs_wei=sell_gibs_wei,
            sell_block=block_number,
            sell_tx_hash=tx_hash,
            impact_pct_at_sell=impact,
            deadline_block=block_number + _config.PROBE_RESPONSE_WINDOW_BLOCKS,
        )
        self._persist()

    def check_arb_response(self) -> ArbResponse:
        """
        Polls Swap events on GIBS/WPLS in the pending sell's window.

        Returns:
          - PENDING: still within window, no matching swap seen
          - ARB_DETECTED: a non-self GIBS-buy swap was found
          - NO_RESPONSE: window expired with no match
        """
        if self.state.pending_sell is None:
            return ArbResponse(kind=ArbResponseKind.NO_RESPONSE)

        ps = self.state.pending_sell
        current = self._current_block()

        # Window: (sell_block, deadline_block] inclusive
        from_block = ps.sell_block + 1
        to_block = min(current, ps.deadline_block)

        if to_block >= from_block:
            logs = self._get_swap_logs(from_block, to_block)
            for log in logs:
                args = log.get("args", {})
                sender = (args.get("sender") or "").lower()
                if sender in self._SELF_ADDRESSES:
                    continue
                # GIBS-buy: WPLS in, GIBS out (token0=GIBS, token1=WPLS on V2 pair)
                gibs_out = int(args.get("amount0Out", 0))
                wpls_in = int(args.get("amount1In", 0))
                if gibs_out > 0 and wpls_in > 0:
                    self._on_arb_detected(gibs_out, log["blockNumber"], log["transactionHash"], sender)
                    return ArbResponse(
                        kind=ArbResponseKind.ARB_DETECTED,
                        gibs_size_wei=gibs_out,
                        tx_hash=log["transactionHash"],
                        block=log["blockNumber"],
                        sender=sender,
                    )

        if current > ps.deadline_block:
            self._on_no_response()
            return ArbResponse(kind=ArbResponseKind.NO_RESPONSE)

        return ArbResponse(kind=ArbResponseKind.PENDING)

    def _current_block(self) -> int:
        """Return current chain head. Overridden in tests via patch."""
        from .chain import w3_read
        return w3_read.eth.block_number

    def _get_swap_logs(self, from_block: int, to_block: int) -> list:
        """
        Fetch decoded Swap events on GIBS/WPLS for the given block range.

        Returns a list of dicts with 'blockNumber', 'transactionHash', and
        'args' keys (matching web3.py event log shape). Returns [] on RPC error.
        """
        try:
            from .chain import pair_contract
            from .config import GIBS_WPLS_V2_PAIR
            pair = pair_contract(GIBS_WPLS_V2_PAIR)
            event_filter = pair.events.Swap.create_filter(
                fromBlock=from_block, toBlock=to_block
            )
            return [
                {
                    "blockNumber": e["blockNumber"],
                    "transactionHash": e["transactionHash"].hex() if hasattr(e["transactionHash"], "hex") else e["transactionHash"],
                    "args": dict(e["args"]),
                }
                for e in event_filter.get_all_entries()
            ]
        except Exception:
            return []

    def _on_arb_detected(self, gibs_size: int, block: int, tx_hash: str, sender: str) -> None:
        """State transition: arb response received."""
        self.state.last_arb_gibs = gibs_size
        if self.state.mode in (ProbeMode.PROBING, ProbeMode.RE_PROBING):
            # Lock at the current probe_pct
            self.state.sweet_spot_pct = self.state.probe_pct
            self.state.mode = ProbeMode.LOCKED
            self.state.consecutive_failures = 0
        elif self.state.mode == ProbeMode.LOCKED:
            self.state.consecutive_failures = 0
        # CAPPED / PAUSED arb_detected is treated like PROBING — promote to LOCKED
        elif self.state.mode in (ProbeMode.CAPPED, ProbeMode.PAUSED):
            self.state.sweet_spot_pct = _config.PROBE_BASELINE_PCT
            self.state.mode = ProbeMode.LOCKED
            self.state.consecutive_failures = 0
            self.state.capped_entry_block = None
            self.state.paused_entry_block = None
        self.state.pending_sell = None
        self._persist()

    def _on_no_response(self) -> None:
        """State transition: window expired with no arb response."""
        self.state.pending_sell = None
        if self.state.mode in (ProbeMode.PROBING, ProbeMode.RE_PROBING):
            self.state.probe_pct += _config.PROBE_STEP_PCT
            if self.state.probe_pct > _config.PROBE_MAX_IMPACT_PCT:
                self._enter_capped()
        elif self.state.mode == ProbeMode.LOCKED:
            self.state.consecutive_failures += 1
            if self.state.consecutive_failures >= _config.PROBE_FAILURE_THRESHOLD:
                self._enter_re_probing()
        # CAPPED / PAUSED no_response — no state change, fallback continues
        self._persist()

    def _enter_capped(self) -> None:
        """Enter CAPPED state, increment cap_loop_count, possibly trigger PAUSED."""
        self.state.mode = ProbeMode.CAPPED
        self.state.capped_entry_block = self._current_block()
        self.state.cap_loop_count += 1
        if self.state.cap_loop_count >= _config.PROBE_CAP_LOOP_PAUSE_THRESHOLD:
            self.state.mode = ProbeMode.PAUSED
            self.state.paused_entry_block = self._current_block()

    def _enter_re_probing(self) -> None:
        """Transition LOCKED → RE_PROBING starting at sweet_spot - 1."""
        prev_sweet = self.state.sweet_spot_pct or _config.PROBE_BASELINE_PCT
        self.state.probe_pct = max(_config.PROBE_BASELINE_PCT, prev_sweet - 1.0)
        self.state.sweet_spot_pct = None
        self.state.consecutive_failures = 0
        self.state.mode = ProbeMode.RE_PROBING
