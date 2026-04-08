"""Test CAPPED auto-reset behavior."""
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
    # Force into CAPPED state at block 200
    pc.state.mode = ProbeMode.CAPPED
    pc.state.capped_entry_block = 200
    pc.state.probe_pct = 11.0
    return pc


def test_capped_resets_after_3_blocks(pc):
    """At block 203, calling next_sell_gibs auto-resets to PROBING."""
    R = (5000 * 10**18, 210_000 * 10**18)
    with patch.object(pc, "_current_block", return_value=203):
        pc.next_sell_gibs(1000 * 10**18, R)
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.probe_pct == config.PROBE_BASELINE_PCT
    assert pc.state.capped_entry_block is None


def test_capped_does_not_reset_before_3_blocks(pc):
    """At block 202 (only 2 blocks elapsed), still CAPPED."""
    R = (5000 * 10**18, 210_000 * 10**18)
    with patch.object(pc, "_current_block", return_value=202):
        pc.next_sell_gibs(1000 * 10**18, R)
    assert pc.state.mode == ProbeMode.CAPPED


def test_capped_returns_baseline_size_during_cooldown(pc):
    """While in CAPPED cooldown, sell size is baseline."""
    R = (5000 * 10**18, 210_000 * 10**18)
    with patch.object(pc, "_current_block", return_value=201):
        result = pc.next_sell_gibs(1000 * 10**18, R)
    # Baseline 0.3% impact ≈ 7.5 GIBS
    assert 7.0 < result / 1e18 < 8.0
