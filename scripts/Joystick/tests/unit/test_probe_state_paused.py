"""Test PAUSED entry on cap_loop_count and 30-block auto-reset."""
from unittest.mock import patch

import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
)
from scripts.Joystick.core import config


@pytest.fixture
def pc(tmp_path):
    return ProbeController(state_path=str(tmp_path / "probe.json"))


def test_paused_entered_after_cap_loop_threshold(pc):
    """cap_loop_count reaching threshold triggers PAUSED."""
    # Force cap_loop_count to threshold - 1 so the next CAPPED entry pushes to PAUSED
    pc.state.cap_loop_count = config.PROBE_CAP_LOOP_PAUSE_THRESHOLD - 1
    pc.state.mode = ProbeMode.PROBING
    pc.state.probe_pct = config.PROBE_MAX_IMPACT_PCT  # one step from cap

    sell_block = 100
    pc.record_sell(8 * 10**18, sell_block, "0xdead")
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block",
                      return_value=sell_block + config.PROBE_RESPONSE_WINDOW_BLOCKS + 1):
        pc.check_arb_response()

    assert pc.state.mode == ProbeMode.PAUSED
    assert pc.state.paused_entry_block is not None


def test_paused_returns_baseline_size(pc):
    """In PAUSED, sell size is baseline (during cooldown, before reset)."""
    pc.state.mode = ProbeMode.PAUSED
    pc.state.paused_entry_block = 500
    pc.state.cap_loop_count = config.PROBE_CAP_LOOP_PAUSE_THRESHOLD
    R = (5000 * 10**18, 210_000 * 10**18)
    # Poll at a block BEFORE the pause-reset threshold
    still_paused = pc.state.paused_entry_block + config.PROBE_CAP_LOOP_PAUSE_BLOCKS - 5
    with patch.object(pc, "_current_block", return_value=still_paused):
        result = pc.next_sell_gibs(1000 * 10**18, R)
    # Baseline 0.3% impact ≈ 7.5 GIBS on a 5000 GIBS pool
    assert 7.0 < result / 1e18 < 8.0


def test_paused_resets_after_pause_blocks_elapsed(pc):
    """At paused_entry + PROBE_CAP_LOOP_PAUSE_BLOCKS, auto-reset to PROBING."""
    pc.state.mode = ProbeMode.PAUSED
    pc.state.paused_entry_block = 500
    pc.state.cap_loop_count = config.PROBE_CAP_LOOP_PAUSE_THRESHOLD
    R = (5000 * 10**18, 210_000 * 10**18)
    reset_block = pc.state.paused_entry_block + config.PROBE_CAP_LOOP_PAUSE_BLOCKS
    with patch.object(pc, "_current_block", return_value=reset_block):
        pc.next_sell_gibs(1000 * 10**18, R)
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.cap_loop_count == 0
    assert pc.state.paused_entry_block is None


def test_paused_does_not_reset_before_pause_blocks_elapsed(pc):
    """At paused_entry + PAUSE_BLOCKS - 1, still PAUSED."""
    pc.state.mode = ProbeMode.PAUSED
    pc.state.paused_entry_block = 500
    pc.state.cap_loop_count = config.PROBE_CAP_LOOP_PAUSE_THRESHOLD
    R = (5000 * 10**18, 210_000 * 10**18)
    almost_reset = pc.state.paused_entry_block + config.PROBE_CAP_LOOP_PAUSE_BLOCKS - 1
    with patch.object(pc, "_current_block", return_value=almost_reset):
        pc.next_sell_gibs(1000 * 10**18, R)
    assert pc.state.mode == ProbeMode.PAUSED
