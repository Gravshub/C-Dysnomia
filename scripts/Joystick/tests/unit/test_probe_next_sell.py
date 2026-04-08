"""Test next_sell_gibs for the three primary cases."""
import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
    PendingSell,
)


@pytest.fixture
def pc(tmp_path):
    return ProbeController(state_path=str(tmp_path / "probe.json"))


def test_next_sell_in_probing_at_baseline(pc):
    """Fresh PROBING at 0.3% on a 5000 GIBS pool → ~7.5 GIBS."""
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    hub_balance = 1000 * 10**18  # plenty
    result = pc.next_sell_gibs(hub_balance, (R_gibs, R_wpls))
    result_gibs = result / 1e18
    assert 7.0 < result_gibs < 8.0


def test_next_sell_caps_at_hub_balance(pc):
    """If target > hub_balance, return hub_balance."""
    pc.state.probe_pct = 5.0  # ~125 GIBS target
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    hub_balance = 50 * 10**18  # only 50 GIBS available
    result = pc.next_sell_gibs(hub_balance, (R_gibs, R_wpls))
    assert result == hub_balance


def test_next_sell_returns_zero_when_pending_unresolved(pc):
    """If a pending sell is still within its window, return 0."""
    pc.state.pending_sell = PendingSell(
        sell_gibs_wei=8 * 10**18,
        sell_block=100,
        sell_tx_hash="0xdead",
        impact_pct_at_sell=0.3,
        deadline_block=105,
    )
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result = pc.next_sell_gibs(1000 * 10**18, (R_gibs, R_wpls))
    assert result == 0


def test_next_sell_zero_when_balance_zero(pc):
    """Hub balance of zero short-circuits to 0 regardless of state."""
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result = pc.next_sell_gibs(0, (R_gibs, R_wpls))
    assert result == 0
