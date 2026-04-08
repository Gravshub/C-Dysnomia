"""Test RE_PROBING → LOCKED with the new (lower) sweet spot."""
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
    # Manually enter RE_PROBING from sweet_spot=4 → probe_pct=3
    pc.state.mode = ProbeMode.RE_PROBING
    pc.state.probe_pct = 3.0
    pc.state.sweet_spot_pct = None
    pc.state.consecutive_failures = 0
    return pc


def test_reprobing_arb_locks_at_new_sweet_spot(pc):
    """Arb fires during RE_PROBING → LOCKED at the lower sweet_spot."""
    sell_block = 100
    pc.record_sell(50 * 10**18, sell_block, "0xdead")
    # Arb lands inside the response window (sell_block + 2)
    arb_block = sell_block + 2
    fake_swap = {
        "blockNumber": arb_block,
        "transactionHash": "0xbeef",
        "args": {
            "sender": "0xc078c8da" + "0" * 32,
            "amount0In": 0,
            "amount1In": 1500 * 10**18,
            "amount0Out": 35 * 10**18,
            "amount1Out": 0,
        },
    }
    # Current block is within the window
    current = sell_block + 3
    with patch.object(pc, "_get_swap_logs", return_value=[fake_swap]), \
         patch.object(pc, "_current_block", return_value=current):
        pc.check_arb_response()

    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.sweet_spot_pct == pytest.approx(3.0)
    assert pc.state.last_arb_gibs == 35 * 10**18


def test_reprobing_no_response_escalates(pc):
    """RE_PROBING + no_response → probe_pct + PROBE_STEP_PCT."""
    sell_block = 100
    pc.record_sell(50 * 10**18, sell_block, "0xdead")
    # Advance past the deadline
    current = sell_block + config.PROBE_RESPONSE_WINDOW_BLOCKS + 1
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=current):
        pc.check_arb_response()
    assert pc.state.mode == ProbeMode.RE_PROBING
    assert pc.state.probe_pct == pytest.approx(3.0 + config.PROBE_STEP_PCT)  # 4.0


def test_reprobing_can_hit_cap(pc):
    """RE_PROBING escalation can also reach CAPPED."""
    # Start one step away from the cap so a single escalation crosses it
    pc.state.probe_pct = config.PROBE_MAX_IMPACT_PCT - config.PROBE_STEP_PCT + 0.5
    sell_block = 100
    pc.record_sell(50 * 10**18, sell_block, "0xdead")
    current = sell_block + config.PROBE_RESPONSE_WINDOW_BLOCKS + 1
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=current):
        pc.check_arb_response()
    assert pc.state.mode == ProbeMode.CAPPED
