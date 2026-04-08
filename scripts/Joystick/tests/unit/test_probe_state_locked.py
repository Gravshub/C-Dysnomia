"""Test LOCKED mode failure counting and RE_PROBING entry."""
from unittest.mock import patch

import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
)
from scripts.Joystick.core import config


@pytest.fixture
def pc(tmp_path):
    pc = ProbeController(state_path=str(tmp_path / "probe.json"))
    # Set up: locked at sweet_spot 4.0
    pc.state.mode = ProbeMode.LOCKED
    pc.state.sweet_spot_pct = 4.0
    pc.state.probe_pct = 4.0
    pc.state.consecutive_failures = 0
    return pc


def _no_response_cycle(pc, sell_block):
    """Helper: simulate one sell with no response, window elapsed by 1 block."""
    pc.record_sell(8 * 10**18, sell_block, f"0x{sell_block:x}")
    current = sell_block + config.PROBE_RESPONSE_WINDOW_BLOCKS + 1
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=current):
        pc.check_arb_response()


def test_locked_failure_increments_counter(pc):
    _no_response_cycle(pc, 100)
    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.consecutive_failures == 1


def test_locked_to_reprobing_after_two_failures(pc):
    _no_response_cycle(pc, 100)
    _no_response_cycle(pc, 110)
    assert pc.state.mode == ProbeMode.RE_PROBING
    assert pc.state.sweet_spot_pct is None
    assert pc.state.probe_pct == pytest.approx(3.0)  # 4.0 - 1.0
    assert pc.state.consecutive_failures == 0


def test_locked_arb_resets_failure_counter(pc):
    """A successful arb during LOCKED resets failures back to 0."""
    _no_response_cycle(pc, 100)
    assert pc.state.consecutive_failures == 1

    pc.record_sell(8 * 10**18, 110, "0xabc")
    fake_swap = {
        "blockNumber": 112,
        "transactionHash": "0xfeed",
        "args": {
            "sender": "0xc078c8da" + "0" * 32,
            "amount0In": 0,
            "amount1In": 2000 * 10**18,
            "amount0Out": 50 * 10**18,
            "amount1Out": 0,
        },
    }
    with patch.object(pc, "_get_swap_logs", return_value=[fake_swap]), \
         patch.object(pc, "_current_block", return_value=113):
        pc.check_arb_response()

    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.consecutive_failures == 0
    assert pc.state.last_arb_gibs == 50 * 10**18


def test_reprobing_floor_is_baseline(pc):
    """If sweet_spot - 1 would go below baseline, clamp to baseline."""
    pc.state.sweet_spot_pct = 0.5  # already very close to baseline 0.3
    _no_response_cycle(pc, 200)
    _no_response_cycle(pc, 210)
    assert pc.state.mode == ProbeMode.RE_PROBING
    assert pc.state.probe_pct == pytest.approx(config.PROBE_BASELINE_PCT)
