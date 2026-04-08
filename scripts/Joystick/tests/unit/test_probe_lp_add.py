"""Test lp_add_target lifecycle."""
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


def test_lp_add_target_none_initially(pc):
    assert pc.lp_add_target() is None


def test_lp_add_target_set_after_arb(pc):
    """After an arb is detected, lp_add_target returns its size."""
    sell_block = 100
    pc.record_sell(8 * 10**18, sell_block, "0xdead")
    fake_swap = {
        "blockNumber": sell_block + 2,
        "transactionHash": "0xfeed",
        "args": {
            "sender": "0xc078c8da" + "0" * 32,
            "amount0In": 0,
            "amount1In": 2000 * 10**18,
            "amount0Out": 47 * 10**18,
            "amount1Out": 0,
        },
    }
    with patch.object(pc, "_get_swap_logs", return_value=[fake_swap]), \
         patch.object(pc, "_current_block", return_value=sell_block + 3):
        pc.check_arb_response()

    assert pc.lp_add_target() == 47 * 10**18


def test_clear_lp_add_target_resets(pc):
    """Calling clear_lp_add_target() resets to None."""
    pc.state.last_arb_gibs = 47 * 10**18
    assert pc.lp_add_target() == 47 * 10**18
    pc.clear_lp_add_target()
    assert pc.lp_add_target() is None


def test_clear_lp_add_target_resets_failure_count(pc):
    """clear_lp_add_target also clears the failure counter (success path)."""
    pc.state.last_arb_gibs = 47 * 10**18
    pc.state.lp_add_failure_count = 2
    pc.clear_lp_add_target()
    assert pc.state.lp_add_failure_count == 0


def test_record_lp_add_failure_increments_and_clears_at_limit(pc):
    """record_lp_add_failure increments; force-clears after PROBE_LP_ADD_RETRY_LIMIT."""
    pc.state.last_arb_gibs = 47 * 10**18
    # First failure below limit: counter increments, target retained
    pc.record_lp_add_failure()
    assert pc.state.lp_add_failure_count == 1
    assert pc.state.last_arb_gibs == 47 * 10**18

    # Keep failing up to the limit (total = limit)
    for _ in range(config.PROBE_LP_ADD_RETRY_LIMIT - 1):
        pc.record_lp_add_failure()

    # At the limit, target is force-cleared and counter resets
    assert pc.state.lp_add_failure_count == 0
    assert pc.state.last_arb_gibs is None
