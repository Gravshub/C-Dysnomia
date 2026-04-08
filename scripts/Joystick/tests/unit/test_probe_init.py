"""Test ProbeController initialization (fresh, restored, corrupt)."""
import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
    save_state,
    ProbeState,
)
from scripts.Joystick.core import config


def test_init_fresh_when_no_state_file(tmp_path):
    """Missing state file → init at PROBING with baseline."""
    state_path = str(tmp_path / "probe.json")
    pc = ProbeController(state_path=state_path)
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.probe_pct == config.PROBE_BASELINE_PCT
    assert pc.state.sweet_spot_pct is None
    assert pc.state.consecutive_failures == 0
    assert pc.state.cap_loop_count == 0
    assert pc.state.pending_sell is None


def test_init_restores_from_file(tmp_path):
    """Existing state file → restore that state."""
    state_path = str(tmp_path / "probe.json")
    state = ProbeState(
        mode=ProbeMode.LOCKED,
        probe_pct=4.0,
        sweet_spot_pct=4.0,
        consecutive_failures=0,
        capped_entry_block=None,
        paused_entry_block=None,
        cap_loop_count=0,
        lp_add_failure_count=0,
        pending_sell=None,
        last_arb_gibs=None,
        last_transition_ts="2026-04-08T17:00:00+00:00",
    )
    save_state(state, state_path)

    pc = ProbeController(state_path=state_path)
    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.sweet_spot_pct == 4.0


def test_init_corrupt_file_falls_back_to_fresh(tmp_path):
    """Corrupt file → reinit fresh, file renamed to .broken-*."""
    state_path = tmp_path / "probe.json"
    state_path.write_text("garbage")
    pc = ProbeController(state_path=str(state_path))
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.probe_pct == config.PROBE_BASELINE_PCT
    # Original file is gone (renamed)
    assert not state_path.exists()
