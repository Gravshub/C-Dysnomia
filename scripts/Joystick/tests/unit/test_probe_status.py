"""Test the status() snapshot and stats counter accounting."""
from unittest.mock import patch

import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
)


@pytest.fixture
def pc(tmp_path):
    return ProbeController(state_path=str(tmp_path / "probe.json"))


def test_status_fresh_shape(pc):
    s = pc.status()
    assert s["mode"] == "PROBING"
    assert s["sweet_spot_pct"] is None
    assert s["consecutive_failures"] == 0
    assert s["pending_sell"] is None
    assert s["last_arb_gibs"] is None
    assert s["cap_loop_count"] == 0
    assert s["lp_add_failure_count"] == 0
    assert "last_transition_ts" in s
    assert "stats" in s
    assert s["stats"]["sells_total"] == 0
    assert s["stats"]["arbs_detected_total"] == 0


def test_record_sell_increments_sells_total(pc):
    pc.record_sell(8 * 10**18, 100, "0xdead")
    assert pc.status()["stats"]["sells_total"] == 1


def test_arb_detected_increments_arbs_total(pc):
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

    assert pc.status()["stats"]["arbs_detected_total"] == 1


def test_status_includes_human_readable_arb_size(pc):
    """last_arb_gibs in status is float GIBS, not wei."""
    pc.state.last_arb_gibs = 47_500_000_000_000_000_000
    s = pc.status()
    assert s["last_arb_gibs"] == pytest.approx(47.5)
