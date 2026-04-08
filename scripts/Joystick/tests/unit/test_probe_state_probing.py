"""End-to-end test of the PROBING → CAPPED escalation walk."""
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


def _force_no_response(pc, current_block_after_deadline):
    """Helper: simulate one sell with no response, advance state."""
    # Derived so it remains correct if PROBE_RESPONSE_WINDOW_BLOCKS changes
    sell_block = current_block_after_deadline - config.PROBE_RESPONSE_WINDOW_BLOCKS - 1
    pc.record_sell(8 * 10**18, sell_block, f"0x{sell_block:x}")
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=current_block_after_deadline):
        pc.check_arb_response()


def test_probing_escalates_one_step_per_failure(pc):
    """Each NO_RESPONSE bumps probe_pct by PROBE_STEP_PCT (1.0)."""
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.probe_pct == config.PROBE_BASELINE_PCT  # 0.3

    _force_no_response(pc, 110)
    assert pc.state.probe_pct == pytest.approx(1.3)
    assert pc.state.mode == ProbeMode.PROBING

    _force_no_response(pc, 120)
    assert pc.state.probe_pct == pytest.approx(2.3)
    assert pc.state.mode == ProbeMode.PROBING


def test_probing_walks_to_cap_then_enters_capped(pc):
    """After enough escalations to exceed MAX, mode becomes CAPPED."""
    block = 100
    while pc.state.mode == ProbeMode.PROBING:
        block += 10
        _force_no_response(pc, block)
        if block > 1000:
            pytest.fail("escalation never hit cap")

    assert pc.state.mode == ProbeMode.CAPPED
    assert pc.state.capped_entry_block is not None
    assert pc.state.cap_loop_count == 1


def test_capped_returns_baseline_size(pc):
    """In CAPPED, next_sell_gibs returns the baseline-impact size."""
    # Force into CAPPED
    pc.state.mode = ProbeMode.CAPPED
    pc.state.capped_entry_block = 200
    pc.state.probe_pct = 11.0  # whatever
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    # Mock _current_block to a value within the CAPPED window (no auto-reset)
    with patch.object(pc, "_current_block", return_value=201):
        result = pc.next_sell_gibs(1000 * 10**18, (R_gibs, R_wpls))
    # Baseline of 0.3% on this pool ≈ 7.5 GIBS
    assert 7.0 < result / 1e18 < 8.0
