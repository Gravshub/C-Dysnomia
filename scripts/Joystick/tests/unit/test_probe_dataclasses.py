"""Test the dataclass and enum surface of the probe controller module."""
from datetime import datetime, timezone

from scripts.Joystick.core.probe_controller import (
    ProbeMode,
    PendingSell,
    ProbeState,
    ArbResponse,
    ArbResponseKind,
)


def test_probe_mode_enum_has_five_states():
    assert ProbeMode.PROBING.value == "PROBING"
    assert ProbeMode.LOCKED.value == "LOCKED"
    assert ProbeMode.RE_PROBING.value == "RE_PROBING"
    assert ProbeMode.CAPPED.value == "CAPPED"
    assert ProbeMode.PAUSED.value == "PAUSED"


def test_pending_sell_dataclass_fields():
    p = PendingSell(
        sell_gibs_wei=8 * 10**18,
        sell_block=100,
        sell_tx_hash="0xdead",
        impact_pct_at_sell=0.3,
        deadline_block=105,
    )
    assert p.sell_gibs_wei == 8 * 10**18
    assert p.deadline_block == 105


def test_probe_state_default_construction():
    s = ProbeState(
        mode=ProbeMode.PROBING,
        probe_pct=0.3,
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
    assert s.mode == ProbeMode.PROBING
    assert s.probe_pct == 0.3
    assert s.sweet_spot_pct is None


def test_arb_response_pending():
    r = ArbResponse(kind=ArbResponseKind.PENDING)
    assert r.kind == ArbResponseKind.PENDING
    assert r.gibs_size_wei is None


def test_arb_response_detected():
    r = ArbResponse(
        kind=ArbResponseKind.ARB_DETECTED,
        gibs_size_wei=47 * 10**18,
        tx_hash="0xfeed",
        block=104,
        sender="0xc078c8da",
    )
    assert r.kind == ArbResponseKind.ARB_DETECTED
    assert r.gibs_size_wei == 47 * 10**18


def test_arb_response_no_response():
    r = ArbResponse(kind=ArbResponseKind.NO_RESPONSE)
    assert r.kind == ArbResponseKind.NO_RESPONSE
