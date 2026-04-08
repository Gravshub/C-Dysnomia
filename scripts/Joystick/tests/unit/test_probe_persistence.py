"""Test ProbeState load/save round-trip and corruption handling."""
import json
import os
from pathlib import Path

import pytest

from scripts.Joystick.core.probe_controller import (
    ProbeMode,
    ProbeState,
    PendingSell,
    save_state,
    load_state,
)


def _make_state():
    return ProbeState(
        mode=ProbeMode.LOCKED,
        probe_pct=4.0,
        sweet_spot_pct=4.0,
        consecutive_failures=0,
        capped_entry_block=None,
        paused_entry_block=None,
        cap_loop_count=0,
        lp_add_failure_count=0,
        pending_sell=None,
        last_arb_gibs=47880000000000000000,
        last_transition_ts="2026-04-08T17:30:00+00:00",
    )


def test_save_and_load_roundtrip(tmp_path):
    state = _make_state()
    path = str(tmp_path / "probe_state.json")
    save_state(state, path)
    loaded = load_state(path)
    assert loaded is not None
    assert loaded.mode == ProbeMode.LOCKED
    assert loaded.sweet_spot_pct == 4.0
    assert loaded.last_arb_gibs == 47880000000000000000


def test_load_missing_returns_none(tmp_path):
    path = str(tmp_path / "does_not_exist.json")
    assert load_state(path) is None


def test_load_corrupt_renames_and_returns_none(tmp_path):
    path = tmp_path / "probe_state.json"
    path.write_text("not valid json {{{")
    assert load_state(str(path)) is None
    # Original should be renamed
    assert not path.exists()
    broken = list(tmp_path.glob("probe_state.json.broken-*"))
    assert len(broken) == 1


def test_save_uses_atomic_write_with_group_read(tmp_path):
    """Saved file should be mode 0o664 (group-readable)."""
    state = _make_state()
    path = str(tmp_path / "probe_state.json")
    save_state(state, path)
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o664


def test_save_load_with_pending_sell(tmp_path):
    state = _make_state()
    state.pending_sell = PendingSell(
        sell_gibs_wei=8 * 10**18,
        sell_block=100,
        sell_tx_hash="0xdead",
        impact_pct_at_sell=0.3,
        deadline_block=105,
    )
    path = str(tmp_path / "probe_state.json")
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.pending_sell is not None
    assert loaded.pending_sell.sell_block == 100


def test_load_unknown_schema_version_treated_as_corrupt(tmp_path):
    path = tmp_path / "probe_state.json"
    path.write_text(json.dumps({"schema_version": 999, "state": {}}))
    assert load_state(str(path)) is None
    broken = list(tmp_path.glob("probe_state.json.broken-*"))
    assert len(broken) == 1
