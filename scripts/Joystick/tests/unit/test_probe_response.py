"""Test record_sell and check_arb_response with mocked log retrieval."""
from unittest.mock import patch

import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
    ArbResponseKind,
)


@pytest.fixture
def pc(tmp_path):
    return ProbeController(state_path=str(tmp_path / "probe.json"))


def test_record_sell_stores_pending(pc):
    pc.record_sell(
        sell_gibs_wei=8 * 10**18,
        block_number=100,
        tx_hash="0xdead",
    )
    assert pc.state.pending_sell is not None
    assert pc.state.pending_sell.sell_block == 100
    assert pc.state.pending_sell.deadline_block == 105  # 100 + 5


def test_record_sell_rejects_overlap(pc):
    pc.record_sell(8 * 10**18, 100, "0xdead")
    with pytest.raises(RuntimeError, match="pending sell already in progress"):
        pc.record_sell(8 * 10**18, 101, "0xfeed")


def test_check_arb_response_pending_returns_pending(pc):
    """No matching swap, current_block <= deadline → PENDING."""
    pc.record_sell(8 * 10**18, 100, "0xdead")
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=102):
        r = pc.check_arb_response()
    assert r.kind == ArbResponseKind.PENDING
    # State unchanged
    assert pc.state.pending_sell is not None


def test_check_arb_response_no_response_after_deadline(pc):
    """No matching swap, current_block > deadline → NO_RESPONSE, escalation."""
    pc.record_sell(8 * 10**18, 100, "0xdead")
    initial_pct = pc.state.probe_pct
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=106):
        r = pc.check_arb_response()
    assert r.kind == ArbResponseKind.NO_RESPONSE
    assert pc.state.pending_sell is None  # cleared
    assert pc.state.probe_pct == initial_pct + 1.0  # escalated


def test_check_arb_response_arb_detected(pc):
    """Matching swap log → ARB_DETECTED, transition to LOCKED."""
    pc.record_sell(8 * 10**18, 100, "0xdead")
    fake_swap = {
        "blockNumber": 103,
        "transactionHash": "0xbeef",
        "args": {
            "sender": "0xc078c8da" + "0" * 32,
            "amount0In": 0,
            "amount1In": 2000 * 10**18,  # WPLS in
            "amount0Out": 47 * 10**18,   # GIBS out
            "amount1Out": 0,
        },
    }
    with patch.object(pc, "_get_swap_logs", return_value=[fake_swap]), \
         patch.object(pc, "_current_block", return_value=104):
        r = pc.check_arb_response()
    assert r.kind == ArbResponseKind.ARB_DETECTED
    assert r.gibs_size_wei == 47 * 10**18
    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.sweet_spot_pct is not None
    assert pc.state.last_arb_gibs == 47 * 10**18


def test_check_arb_response_ignores_self_swaps(pc):
    """A swap where sender is Joey or Hub should NOT count as an arb."""
    pc.record_sell(8 * 10**18, 100, "0xdead")
    self_swap = {
        "blockNumber": 102,
        "transactionHash": "0xself",
        "args": {
            "sender": "0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14",  # Hub
            "amount0In": 0,
            "amount1In": 100 * 10**18,
            "amount0Out": 2 * 10**18,
            "amount1Out": 0,
        },
    }
    with patch.object(pc, "_get_swap_logs", return_value=[self_swap]), \
         patch.object(pc, "_current_block", return_value=103):
        r = pc.check_arb_response()
    assert r.kind == ArbResponseKind.PENDING


def test_check_arb_response_no_pending_returns_no_response(pc):
    """If no pending sell at all, check returns NO_RESPONSE no-op."""
    r = pc.check_arb_response()
    assert r.kind == ArbResponseKind.NO_RESPONSE


def test_enter_capped_resets_probe_pct_to_baseline(pc):
    """_enter_capped must reset probe_pct so CAPPED state is internally consistent."""
    from scripts.Joystick.core import config
    pc.state.probe_pct = 10.5  # over max
    with patch.object(pc, "_current_block", return_value=500):
        pc._enter_capped()
    assert pc.state.mode == ProbeMode.CAPPED
    assert pc.state.probe_pct == config.PROBE_BASELINE_PCT
    assert pc.state.capped_entry_block is not None
    assert pc.state.cap_loop_count == 1
