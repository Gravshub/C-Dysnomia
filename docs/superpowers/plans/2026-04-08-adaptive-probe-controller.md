# Adaptive Probe Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone advisor module that finds and locks the minimum sell size required to attract external arb bot responses on GIBS/WPLS, then restores the pool via Joey-funded LP-add matching the arb size.

**Architecture:** Pure-Python advisor module (`core/probe_controller.py`) instantiated as a singleton in `bot.py` and consumed by `engines/dss.py` (E2). The controller is a state machine with 5 modes (PROBING, LOCKED, RE_PROBING, CAPPED, PAUSED), persistent JSON state, and Swap-event-based arb-response detection. E2 still owns all TX submission; the controller only sizes sells and triggers LP-add follow-ups.

**Tech Stack:** Python 3.13, web3.py 6+, pytest, existing Joystick infrastructure (`core.chain`, `core.event_logger`, `core.config`). No new dependencies.

**Reference:** See `docs/superpowers/specs/2026-04-08-adaptive-probe-controller-design.md` for the full design rationale and constants table.

---

## Pre-flight checks before starting

- [ ] Bot is stopped (no live TXs during integration testing). Verify with `pgrep -af "scripts.Joystick.bot" | grep -v pgrep` — should be empty.
- [ ] On branch `claude/joystick-V2-FanxJ` (or a worktree from it). Verify with `git status`.
- [ ] Working directory is `/opt/joystick/repo`.

---

## Task 0: Unit test infrastructure (no-Anvil unit test path)

**Why this is task 0**: the existing `tests/conftest.py` has an `autouse=True` fixture (`isolate`) that depends on a running Anvil process. Without this setup, every unit test we write would silently skip when Anvil isn't running, making TDD iteration painful. We need a subdirectory with its own conftest that overrides the autouse to a no-op.

**Files:**
- Create: `scripts/Joystick/tests/unit/__init__.py`
- Create: `scripts/Joystick/tests/unit/conftest.py`
- Create: `scripts/Joystick/tests/unit/test_smoke.py`

- [ ] **Step 1: Create the directory structure**

```bash
mkdir -p scripts/Joystick/tests/unit
touch scripts/Joystick/tests/unit/__init__.py
```

- [ ] **Step 2: Write the conftest override**

Create `scripts/Joystick/tests/unit/conftest.py`:

```python
"""
Unit test conftest — overrides parent tests/conftest.py to disable
Anvil dependency. Tests in this directory must NOT touch the network or
import any module that triggers RPC connections at import time.
"""
import pytest


@pytest.fixture(autouse=True)
def isolate():
    """No-op override of the parent isolate fixture (which requires Anvil)."""
    yield
```

- [ ] **Step 3: Write a smoke test**

Create `scripts/Joystick/tests/unit/test_smoke.py`:

```python
def test_smoke():
    """Sanity check: pytest can collect and run unit tests without Anvil."""
    assert 1 + 1 == 2
```

- [ ] **Step 4: Run smoke test, verify it passes without Anvil**

```bash
cd /opt/joystick/repo
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_smoke.py -v
```

Expected output (key line):
```
scripts/Joystick/tests/unit/test_smoke.py::test_smoke PASSED
```

If you see `SKIPPED [Anvil not running]`, the conftest override didn't work — re-check step 2.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/tests/unit/__init__.py scripts/Joystick/tests/unit/conftest.py scripts/Joystick/tests/unit/test_smoke.py
git commit -m "test(probe): add unit test subdirectory bypassing Anvil autouse"
```

---

## Task 1: Add PROBE_* constants to config.py

**Files:**
- Modify: `scripts/Joystick/core/config.py` (append at end)
- Test: `scripts/Joystick/tests/unit/test_probe_constants.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_constants.py`:

```python
"""Verify PROBE_* constants are defined with the expected default values."""
from scripts.Joystick.core import config


def test_probe_constants_exist_with_defaults():
    assert config.PROBE_BASELINE_PCT == 0.3
    assert config.PROBE_STEP_PCT == 1.0
    assert config.PROBE_MAX_IMPACT_PCT == 10.0
    assert config.PROBE_RESPONSE_WINDOW_BLOCKS == 5
    assert config.PROBE_FAILURE_THRESHOLD == 2
    assert config.PROBE_CAPPED_AUTO_RESET_BLOCKS == 3
    assert config.PROBE_CAP_LOOP_WARN_THRESHOLD == 5
    assert config.PROBE_CAP_LOOP_PAUSE_THRESHOLD == 10
    assert config.PROBE_CAP_LOOP_PAUSE_BLOCKS == 30
    assert config.PROBE_LP_ADD_RETRY_LIMIT == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_constants.py -v
```

Expected: FAIL with `AttributeError: module 'scripts.Joystick.core.config' has no attribute 'PROBE_BASELINE_PCT'`.

- [ ] **Step 3: Add the constants to config.py**

Append to `scripts/Joystick/core/config.py` (at the end of the file, before any `if __name__` block if present):

```python
# ─── Probe Controller (E2 adaptive sell sizing) ──────────────────────
# See docs/superpowers/specs/2026-04-08-adaptive-probe-controller-design.md
PROBE_BASELINE_PCT = 0.3              # starting impact %, matches current ~8 GIBS floor sell
PROBE_STEP_PCT = 1.0                  # linear escalation per failed probe
PROBE_MAX_IMPACT_PCT = 10.0           # safety cap before CAPPED state
PROBE_RESPONSE_WINDOW_BLOCKS = 5      # blocks to wait for arb response after a sell
PROBE_FAILURE_THRESHOLD = 2           # consecutive LOCKED failures → RE_PROBING
PROBE_CAPPED_AUTO_RESET_BLOCKS = 3    # CAPPED → PROBING after this many blocks
PROBE_CAP_LOOP_WARN_THRESHOLD = 5     # log WARN after this many cap_loop entries
PROBE_CAP_LOOP_PAUSE_THRESHOLD = 10   # PAUSED after this many cap_loop entries
PROBE_CAP_LOOP_PAUSE_BLOCKS = 30      # PAUSED → PROBING after this many blocks (~5 min)
PROBE_LP_ADD_RETRY_LIMIT = 3          # max consecutive LP-add failures before clearing target
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_constants.py -v
```

Expected: `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/config.py scripts/Joystick/tests/unit/test_probe_constants.py
git commit -m "feat(probe): add PROBE_* constants to config"
```

---

## Task 2: Module skeleton + dataclasses + ArbResponse ADT

**Files:**
- Create: `scripts/Joystick/core/probe_controller.py`
- Test: `scripts/Joystick/tests/unit/test_probe_dataclasses.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_dataclasses.py`:

```python
"""Test the dataclass and enum surface of the probe controller module."""
from datetime import datetime, timezone

from scripts.Joystick.core.probe_controller import (
    ProbeMode,
    PendingSell,
    ProbeState,
    ArbResponse,
    ArbResponseKind,
)


def test_probe_mode_enum_has_five_states():
    assert ProbeMode.PROBING.value == "PROBING"
    assert ProbeMode.LOCKED.value == "LOCKED"
    assert ProbeMode.RE_PROBING.value == "RE_PROBING"
    assert ProbeMode.CAPPED.value == "CAPPED"
    assert ProbeMode.PAUSED.value == "PAUSED"


def test_pending_sell_dataclass_fields():
    p = PendingSell(
        sell_gibs_wei=8 * 10**18,
        sell_block=100,
        sell_tx_hash="0xdead",
        impact_pct_at_sell=0.3,
        deadline_block=105,
    )
    assert p.sell_gibs_wei == 8 * 10**18
    assert p.deadline_block == 105


def test_probe_state_default_construction():
    s = ProbeState(
        mode=ProbeMode.PROBING,
        probe_pct=0.3,
        sweet_spot_pct=None,
        consecutive_failures=0,
        capped_entry_block=None,
        paused_entry_block=None,
        cap_loop_count=0,
        lp_add_failure_count=0,
        pending_sell=None,
        last_arb_gibs=None,
        last_transition_ts=datetime.now(timezone.utc).isoformat(),
    )
    assert s.mode == ProbeMode.PROBING
    assert s.probe_pct == 0.3
    assert s.sweet_spot_pct is None


def test_arb_response_pending():
    r = ArbResponse(kind=ArbResponseKind.PENDING)
    assert r.kind == ArbResponseKind.PENDING
    assert r.gibs_size_wei is None


def test_arb_response_detected():
    r = ArbResponse(
        kind=ArbResponseKind.ARB_DETECTED,
        gibs_size_wei=47 * 10**18,
        tx_hash="0xfeed",
        block=104,
        sender="0xc078c8da",
    )
    assert r.kind == ArbResponseKind.ARB_DETECTED
    assert r.gibs_size_wei == 47 * 10**18


def test_arb_response_no_response():
    r = ArbResponse(kind=ArbResponseKind.NO_RESPONSE)
    assert r.kind == ArbResponseKind.NO_RESPONSE
```

- [ ] **Step 2: Run test, verify it fails on import**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_dataclasses.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.Joystick.core.probe_controller'`.

- [ ] **Step 3: Create the module with dataclasses**

Create `scripts/Joystick/core/probe_controller.py`:

```python
"""
probe_controller.py — Adaptive sell-sizing advisor for E2 CEREAL.

Finds the minimum sell size that attracts external arb bot responses on
GIBS/WPLS, locks onto it, re-probes when conditions change, and triggers
LP-add follow-ups sized to match each successful arb.

This module is a pure advisor — E2 still owns all TX submission. See
docs/superpowers/specs/2026-04-08-adaptive-probe-controller-design.md
for the full design.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ProbeMode(str, Enum):
    PROBING = "PROBING"
    LOCKED = "LOCKED"
    RE_PROBING = "RE_PROBING"
    CAPPED = "CAPPED"
    PAUSED = "PAUSED"


class ArbResponseKind(str, Enum):
    PENDING = "PENDING"
    ARB_DETECTED = "ARB_DETECTED"
    NO_RESPONSE = "NO_RESPONSE"


@dataclass
class ArbResponse:
    kind: ArbResponseKind
    gibs_size_wei: Optional[int] = None
    tx_hash: Optional[str] = None
    block: Optional[int] = None
    sender: Optional[str] = None


@dataclass
class PendingSell:
    sell_gibs_wei: int
    sell_block: int
    sell_tx_hash: str
    impact_pct_at_sell: float
    deadline_block: int


@dataclass
class ProbeState:
    mode: ProbeMode
    probe_pct: float
    sweet_spot_pct: Optional[float]
    consecutive_failures: int
    capped_entry_block: Optional[int]
    paused_entry_block: Optional[int]
    cap_loop_count: int
    lp_add_failure_count: int
    pending_sell: Optional[PendingSell]
    last_arb_gibs: Optional[int]
    last_transition_ts: str
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_dataclasses.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_dataclasses.py
git commit -m "feat(probe): module skeleton — ProbeMode, ProbeState, ArbResponse"
```

---

## Task 3: Sizing math (solve_for_impact)

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (append `solve_for_impact` function)
- Test: `scripts/Joystick/tests/unit/test_probe_sizing.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_sizing.py`:

```python
"""Test the constant-product sell-sizing math."""
import math
import pytest

from scripts.Joystick.core.probe_controller import solve_for_impact


def test_solve_for_impact_baseline():
    """At 0.3% impact on a 5000 GIBS pool, expect ~7.5 GIBS sell."""
    # x = R_gibs * (sqrt(1 + p) - 1) / 0.997
    # = 5000 * (sqrt(1.003) - 1) / 0.997
    # = 5000 * 0.001498 / 0.997 ≈ 7.51 GIBS
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result_wei = solve_for_impact(0.3, (R_gibs, R_wpls))
    result_gibs = result_wei / 1e18
    assert 7.0 < result_gibs < 8.0


def test_solve_for_impact_5pct():
    """At 5% impact, expect ~125 GIBS sell on the same pool."""
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result_wei = solve_for_impact(5.0, (R_gibs, R_wpls))
    result_gibs = result_wei / 1e18
    assert 120 < result_gibs < 130


def test_solve_for_impact_10pct_cap():
    """At 10% impact, expect ~245 GIBS sell."""
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result_wei = solve_for_impact(10.0, (R_gibs, R_wpls))
    result_gibs = result_wei / 1e18
    assert 240 < result_gibs < 250


def test_solve_for_impact_zero_returns_zero():
    """0% impact should return 0."""
    assert solve_for_impact(0.0, (5000 * 10**18, 210_000 * 10**18)) == 0


def test_solve_for_impact_negative_raises():
    """Negative impact is a usage error."""
    with pytest.raises(ValueError):
        solve_for_impact(-1.0, (5000 * 10**18, 210_000 * 10**18))


def test_solve_for_impact_zero_reserve_raises():
    """Empty pool is undefined."""
    with pytest.raises(ValueError):
        solve_for_impact(1.0, (0, 210_000 * 10**18))
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_sizing.py -v
```

Expected: `ImportError: cannot import name 'solve_for_impact'`.

- [ ] **Step 3: Implement solve_for_impact**

Append to `scripts/Joystick/core/probe_controller.py`:

```python
import math


def solve_for_impact(impact_pct: float, reserves: tuple[int, int]) -> int:
    """
    Solve for the GIBS amount (wei) that produces a given price impact %
    on a Uniswap v2 pool.

    Args:
        impact_pct: target price impact as a percentage (e.g. 0.3 for 0.3%)
        reserves: (R_gibs_wei, R_wpls_wei) — the pool's GIBS and WPLS sides

    Returns:
        GIBS amount in wei to sell. Zero if impact_pct is zero.

    Raises:
        ValueError: impact_pct < 0 or any reserve is zero/negative.

    Math:
        x_gibs = R_gibs × (sqrt(1 + p) − 1) / 0.997
        Small-impact approximation, accurate to ~5% for p in [0.003, 0.10].
    """
    if impact_pct < 0:
        raise ValueError(f"impact_pct must be non-negative, got {impact_pct}")
    if impact_pct == 0:
        return 0
    R_gibs, R_wpls = reserves
    if R_gibs <= 0 or R_wpls <= 0:
        raise ValueError(f"reserves must be positive, got {reserves}")
    p = impact_pct / 100.0
    x_gibs = R_gibs * (math.sqrt(1.0 + p) - 1.0) / 0.997
    return int(x_gibs)
```

(Note: the `import math` line should be added near the top of the file with the other imports if not already present. The task above lists it inline for clarity but place it at the top.)

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_sizing.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_sizing.py
git commit -m "feat(probe): solve_for_impact constant-product sizing math"
```

---

## Task 4: State persistence (load/save with corruption handling)

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (add `_save_state`, `_load_state`, `_atomic_write_json` helpers and a `STATE_PATH` module constant)
- Test: `scripts/Joystick/tests/unit/test_probe_persistence.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_persistence.py`:

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_persistence.py -v
```

Expected: `ImportError: cannot import name 'save_state'`.

- [ ] **Step 3: Implement persistence helpers**

Append to `scripts/Joystick/core/probe_controller.py`:

```python
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone

# Path constant for the live state file. Tests pass an explicit path.
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STATE_PATH = os.path.join(_DATA_DIR, "probe_state.json")
SCHEMA_VERSION = 1


def _atomic_write_json(path: str, data: dict) -> None:
    """
    Atomic write via tempfile + rename. Sets mode 0o664 so the dashboard
    (running as joystick user) can read files the bot writes (as joey).
    """
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _state_to_dict(state: ProbeState) -> dict:
    """Serialize ProbeState to a JSON-friendly dict."""
    d = asdict(state)
    # Enum and int conversions for JSON compatibility
    d["mode"] = state.mode.value
    if state.last_arb_gibs is not None:
        d["last_arb_gibs"] = str(state.last_arb_gibs)
    if state.pending_sell is not None:
        d["pending_sell"]["sell_gibs_wei"] = str(state.pending_sell.sell_gibs_wei)
    return d


def _state_from_dict(d: dict) -> ProbeState:
    """Deserialize a dict back to ProbeState. Raises on invalid shape."""
    pending_d = d.get("pending_sell")
    pending = None
    if pending_d is not None:
        pending = PendingSell(
            sell_gibs_wei=int(pending_d["sell_gibs_wei"]),
            sell_block=int(pending_d["sell_block"]),
            sell_tx_hash=pending_d["sell_tx_hash"],
            impact_pct_at_sell=float(pending_d["impact_pct_at_sell"]),
            deadline_block=int(pending_d["deadline_block"]),
        )
    last_arb = d.get("last_arb_gibs")
    if last_arb is not None:
        last_arb = int(last_arb)
    return ProbeState(
        mode=ProbeMode(d["mode"]),
        probe_pct=float(d["probe_pct"]),
        sweet_spot_pct=d.get("sweet_spot_pct"),
        consecutive_failures=int(d["consecutive_failures"]),
        capped_entry_block=d.get("capped_entry_block"),
        paused_entry_block=d.get("paused_entry_block"),
        cap_loop_count=int(d["cap_loop_count"]),
        lp_add_failure_count=int(d["lp_add_failure_count"]),
        pending_sell=pending,
        last_arb_gibs=last_arb,
        last_transition_ts=d["last_transition_ts"],
    )


def save_state(state: ProbeState, path: str = STATE_PATH) -> None:
    """Persist a ProbeState atomically to disk."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "state": _state_to_dict(state),
    }
    _atomic_write_json(path, payload)


def load_state(path: str = STATE_PATH) -> Optional[ProbeState]:
    """
    Load a ProbeState from disk.

    Returns None if:
      - File does not exist
      - File is unparseable (renamed to .broken-<ts> for forensics)
      - Schema version is unknown (treated as corrupt, also renamed)
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unknown schema_version {payload.get('schema_version')}")
        return _state_from_dict(payload["state"])
    except Exception:
        # Rename to .broken-<ts> sidecar
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        broken = f"{path}.broken-{ts}"
        try:
            os.rename(path, broken)
        except OSError:
            pass
        return None
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_persistence.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_persistence.py
git commit -m "feat(probe): atomic state persistence with corruption recovery"
```

---

## Task 5: ProbeController.__init__ + fresh state factory

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (add `ProbeController` class)
- Test: `scripts/Joystick/tests/unit/test_probe_init.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_init.py`:

```python
"""Test ProbeController initialization (fresh, restored, corrupt)."""
import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
    save_state,
    ProbeState,
)
from scripts.Joystick.core import config


def test_init_fresh_when_no_state_file(tmp_path):
    """Missing state file → init at PROBING with baseline."""
    state_path = str(tmp_path / "probe.json")
    pc = ProbeController(state_path=state_path)
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.probe_pct == config.PROBE_BASELINE_PCT
    assert pc.state.sweet_spot_pct is None
    assert pc.state.consecutive_failures == 0
    assert pc.state.cap_loop_count == 0
    assert pc.state.pending_sell is None


def test_init_restores_from_file(tmp_path):
    """Existing state file → restore that state."""
    state_path = str(tmp_path / "probe.json")
    state = ProbeState(
        mode=ProbeMode.LOCKED,
        probe_pct=4.0,
        sweet_spot_pct=4.0,
        consecutive_failures=0,
        capped_entry_block=None,
        paused_entry_block=None,
        cap_loop_count=0,
        lp_add_failure_count=0,
        pending_sell=None,
        last_arb_gibs=None,
        last_transition_ts="2026-04-08T17:00:00+00:00",
    )
    save_state(state, state_path)

    pc = ProbeController(state_path=state_path)
    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.sweet_spot_pct == 4.0


def test_init_corrupt_file_falls_back_to_fresh(tmp_path):
    """Corrupt file → reinit fresh, file renamed to .broken-*."""
    state_path = tmp_path / "probe.json"
    state_path.write_text("garbage")
    pc = ProbeController(state_path=str(state_path))
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.probe_pct == config.PROBE_BASELINE_PCT
    # Original file is gone (renamed)
    assert not state_path.exists()
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_init.py -v
```

Expected: `ImportError: cannot import name 'ProbeController'`.

- [ ] **Step 3: Implement ProbeController.__init__**

Append to `scripts/Joystick/core/probe_controller.py`:

```python
from ..core import config as _config


def _fresh_state() -> ProbeState:
    return ProbeState(
        mode=ProbeMode.PROBING,
        probe_pct=_config.PROBE_BASELINE_PCT,
        sweet_spot_pct=None,
        consecutive_failures=0,
        capped_entry_block=None,
        paused_entry_block=None,
        cap_loop_count=0,
        lp_add_failure_count=0,
        pending_sell=None,
        last_arb_gibs=None,
        last_transition_ts=datetime.now(timezone.utc).isoformat(),
    )


class ProbeController:
    """
    Adaptive sell-sizing advisor for E2 CEREAL.

    Holds the state machine that finds, locks, and re-discovers the minimum
    sell size that triggers external arb bot responses on GIBS/WPLS.
    """

    def __init__(self, state_path: str = STATE_PATH):
        self.state_path = state_path
        loaded = load_state(state_path)
        self.state: ProbeState = loaded if loaded is not None else _fresh_state()

    def _persist(self) -> None:
        """Write current state to disk. Called on every transition."""
        self.state.last_transition_ts = datetime.now(timezone.utc).isoformat()
        save_state(self.state, self.state_path)
```

Note: the `from ..core import config as _config` line will fail because we're already inside `core`. Use a module-level relative import at the top of the file instead: `from . import config as _config`. Adjust the import location to match.

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_init.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_init.py
git commit -m "feat(probe): ProbeController init with state restore + fallback"
```

---

## Task 6: next_sell_gibs (3 cases: normal, capped at balance, pending blocks)

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (add `next_sell_gibs` method)
- Test: `scripts/Joystick/tests/unit/test_probe_next_sell.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_next_sell.py`:

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_next_sell.py -v
```

Expected: `AttributeError: 'ProbeController' object has no attribute 'next_sell_gibs'`.

- [ ] **Step 3: Implement next_sell_gibs**

Add to the `ProbeController` class in `scripts/Joystick/core/probe_controller.py`:

```python
    def next_sell_gibs(
        self,
        hub_gibs_balance: int,
        pool_reserves: tuple[int, int],
    ) -> int:
        """
        Returns the GIBS amount (wei) E2 should sell this cycle.

        Returns 0 in these cases:
          - hub_gibs_balance is zero (nothing to sell)
          - a previous sell is still within its monitoring window

        In CAPPED or PAUSED modes, returns a sell sized to PROBE_BASELINE_PCT
        (productive fallback). In PROBING/RE_PROBING modes, sized to probe_pct.
        In LOCKED mode, sized to sweet_spot_pct.

        Always capped at hub_gibs_balance.
        """
        if hub_gibs_balance <= 0:
            return 0
        if self.state.pending_sell is not None:
            # One pending sell at a time — return 0 until window resolves
            return 0

        # Determine which impact % to use this call
        if self.state.mode == ProbeMode.LOCKED:
            target_pct = self.state.sweet_spot_pct or _config.PROBE_BASELINE_PCT
        elif self.state.mode in (ProbeMode.CAPPED, ProbeMode.PAUSED):
            target_pct = _config.PROBE_BASELINE_PCT
        else:  # PROBING or RE_PROBING
            target_pct = self.state.probe_pct

        target_wei = solve_for_impact(target_pct, pool_reserves)
        if target_wei > hub_gibs_balance:
            return hub_gibs_balance
        return target_wei
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_next_sell.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_next_sell.py
git commit -m "feat(probe): next_sell_gibs sizing decision per mode"
```

---

## Task 7: record_sell + check_arb_response (with all 3 outcomes)

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (add `record_sell`, `check_arb_response`, `_get_swap_logs` helper)
- Test: `scripts/Joystick/tests/unit/test_probe_response.py`

This task pairs `record_sell` and `check_arb_response` because they form a single sell→monitor→resolve loop and are easier to test together with a mock log injector.

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_response.py`:

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_response.py -v
```

Expected: `AttributeError: 'ProbeController' object has no attribute 'record_sell'`.

- [ ] **Step 3: Implement record_sell, check_arb_response, helpers**

Add to the `ProbeController` class in `scripts/Joystick/core/probe_controller.py`:

```python
    # Addresses to ignore in arb-detection — our own infrastructure that
    # generates GIBS pool swaps. Lowercase for case-insensitive comparison.
    _SELF_ADDRESSES = {
        "0x17367877af5a8d0eb33ba5689a880f696386e24d",  # Joey wallet
        "0x7bd76a0f7e03a3ba76a621ba0988c7db0adbab14",  # JoystickHub
        "0x165c3410fc91ef562c50559f7d2289febed552d9",  # PulseX V2 Router
    }

    def record_sell(
        self,
        sell_gibs_wei: int,
        block_number: int,
        tx_hash: str,
    ) -> None:
        """
        Record that E2 has just submitted a sell. Starts the response window.

        Block number MUST come from the TX receipt, not w3.eth.block_number,
        to anchor the deadline correctly.

        Raises RuntimeError if a pending sell is already in progress (caller
        bug — should have called check_arb_response first).
        """
        if self.state.pending_sell is not None:
            raise RuntimeError("pending sell already in progress")
        # The probe_pct or sweet_spot_pct in effect when this sell was sized
        if self.state.mode == ProbeMode.LOCKED:
            impact = self.state.sweet_spot_pct or _config.PROBE_BASELINE_PCT
        elif self.state.mode in (ProbeMode.CAPPED, ProbeMode.PAUSED):
            impact = _config.PROBE_BASELINE_PCT
        else:
            impact = self.state.probe_pct
        self.state.pending_sell = PendingSell(
            sell_gibs_wei=sell_gibs_wei,
            sell_block=block_number,
            sell_tx_hash=tx_hash,
            impact_pct_at_sell=impact,
            deadline_block=block_number + _config.PROBE_RESPONSE_WINDOW_BLOCKS,
        )
        self._persist()

    def check_arb_response(self) -> ArbResponse:
        """
        Polls Swap events on GIBS/WPLS in the pending sell's window.

        Returns:
          - PENDING: still within window, no matching swap seen
          - ARB_DETECTED: a non-self GIBS-buy swap was found
          - NO_RESPONSE: window expired with no match
        """
        if self.state.pending_sell is None:
            return ArbResponse(kind=ArbResponseKind.NO_RESPONSE)

        ps = self.state.pending_sell
        current = self._current_block()

        # Window: (sell_block, deadline_block] inclusive
        from_block = ps.sell_block + 1
        to_block = min(current, ps.deadline_block)

        if to_block >= from_block:
            logs = self._get_swap_logs(from_block, to_block)
            for log in logs:
                args = log.get("args", {})
                sender = (args.get("sender") or "").lower()
                if sender in self._SELF_ADDRESSES:
                    continue
                # GIBS-buy: WPLS in, GIBS out (token0=GIBS, token1=WPLS on V2 pair)
                gibs_out = int(args.get("amount0Out", 0))
                wpls_in = int(args.get("amount1In", 0))
                if gibs_out > 0 and wpls_in > 0:
                    self._on_arb_detected(gibs_out, log["blockNumber"], log["transactionHash"], sender)
                    return ArbResponse(
                        kind=ArbResponseKind.ARB_DETECTED,
                        gibs_size_wei=gibs_out,
                        tx_hash=log["transactionHash"],
                        block=log["blockNumber"],
                        sender=sender,
                    )

        if current > ps.deadline_block:
            self._on_no_response()
            return ArbResponse(kind=ArbResponseKind.NO_RESPONSE)

        return ArbResponse(kind=ArbResponseKind.PENDING)

    def _current_block(self) -> int:
        """Return current chain head. Overridden in tests via patch."""
        from .chain import w3_read
        return w3_read.eth.block_number

    def _get_swap_logs(self, from_block: int, to_block: int) -> list:
        """
        Fetch decoded Swap events on GIBS/WPLS for the given block range.

        Returns a list of dicts with 'blockNumber', 'transactionHash', and
        'args' keys (matching web3.py event log shape). Returns [] on RPC error.
        """
        try:
            from .chain import pair_contract
            from .config import GIBS_WPLS_V2_PAIR
            pair = pair_contract(GIBS_WPLS_V2_PAIR)
            event_filter = pair.events.Swap.create_filter(
                fromBlock=from_block, toBlock=to_block
            )
            return [
                {
                    "blockNumber": e["blockNumber"],
                    "transactionHash": e["transactionHash"].hex() if hasattr(e["transactionHash"], "hex") else e["transactionHash"],
                    "args": dict(e["args"]),
                }
                for e in event_filter.get_all_entries()
            ]
        except Exception:
            return []

    def _on_arb_detected(self, gibs_size: int, block: int, tx_hash: str, sender: str) -> None:
        """State transition: arb response received."""
        self.state.last_arb_gibs = gibs_size
        if self.state.mode in (ProbeMode.PROBING, ProbeMode.RE_PROBING):
            # Lock at the current probe_pct
            self.state.sweet_spot_pct = self.state.probe_pct
            self.state.mode = ProbeMode.LOCKED
            self.state.consecutive_failures = 0
        elif self.state.mode == ProbeMode.LOCKED:
            self.state.consecutive_failures = 0
        # CAPPED / PAUSED arb_detected is treated like PROBING — promote to LOCKED
        elif self.state.mode in (ProbeMode.CAPPED, ProbeMode.PAUSED):
            self.state.sweet_spot_pct = _config.PROBE_BASELINE_PCT
            self.state.mode = ProbeMode.LOCKED
            self.state.consecutive_failures = 0
            self.state.capped_entry_block = None
            self.state.paused_entry_block = None
        self.state.pending_sell = None
        self._persist()

    def _on_no_response(self) -> None:
        """State transition: window expired with no arb response."""
        self.state.pending_sell = None
        if self.state.mode in (ProbeMode.PROBING, ProbeMode.RE_PROBING):
            self.state.probe_pct += _config.PROBE_STEP_PCT
            if self.state.probe_pct > _config.PROBE_MAX_IMPACT_PCT:
                self._enter_capped()
        elif self.state.mode == ProbeMode.LOCKED:
            self.state.consecutive_failures += 1
            if self.state.consecutive_failures >= _config.PROBE_FAILURE_THRESHOLD:
                self._enter_re_probing()
        # CAPPED / PAUSED no_response — no state change, fallback continues
        self._persist()

    def _enter_capped(self) -> None:
        """Enter CAPPED state, increment cap_loop_count, possibly trigger PAUSED."""
        self.state.mode = ProbeMode.CAPPED
        self.state.capped_entry_block = self._current_block()
        self.state.cap_loop_count += 1
        if self.state.cap_loop_count >= _config.PROBE_CAP_LOOP_PAUSE_THRESHOLD:
            self.state.mode = ProbeMode.PAUSED
            self.state.paused_entry_block = self._current_block()

    def _enter_re_probing(self) -> None:
        """Transition LOCKED → RE_PROBING starting at sweet_spot - 1."""
        prev_sweet = self.state.sweet_spot_pct or _config.PROBE_BASELINE_PCT
        self.state.probe_pct = max(_config.PROBE_BASELINE_PCT, prev_sweet - 1.0)
        self.state.sweet_spot_pct = None
        self.state.consecutive_failures = 0
        self.state.mode = ProbeMode.RE_PROBING
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_response.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_response.py
git commit -m "feat(probe): record_sell + check_arb_response with state transitions"
```

---

## Task 8: PROBING mode escalation full walk

**Files:**
- Test: `scripts/Joystick/tests/unit/test_probe_state_probing.py`

This test verifies the full escalation walk from baseline to CAPPED, exercising the state machine via repeated record_sell + check_arb_response cycles. No new implementation code — uses what Task 7 built.

- [ ] **Step 1: Write the test**

Create `scripts/Joystick/tests/unit/test_probe_state_probing.py`:

```python
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
    pc.record_sell(8 * 10**18, current_block_after_deadline - 6, f"0x{current_block_after_deadline:x}")
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
    result = pc.next_sell_gibs(1000 * 10**18, (R_gibs, R_wpls))
    # Baseline of 0.3% on this pool ≈ 7.5 GIBS
    assert 7.0 < result / 1e18 < 8.0
```

- [ ] **Step 2: Run test, verify it passes**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_state_probing.py -v
```

Expected: 3 tests pass. (No implementation change needed — Task 7 already built the state transitions.)

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/unit/test_probe_state_probing.py
git commit -m "test(probe): PROBING escalation walk and CAPPED entry"
```

---

## Task 9: CAPPED auto-reset after 3 blocks

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (add `_check_capped_reset` called from `next_sell_gibs`)
- Test: `scripts/Joystick/tests/unit/test_probe_state_capped.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_state_capped.py`:

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_state_capped.py -v
```

Expected: `test_capped_resets_after_3_blocks` fails — `pc.state.mode == ProbeMode.CAPPED` (not PROBING).

- [ ] **Step 3: Implement auto-reset check**

Replace the existing `next_sell_gibs` method in `scripts/Joystick/core/probe_controller.py` (added in Task 6) with this expanded version that calls the timer check before sizing:

```python
    def next_sell_gibs(
        self,
        hub_gibs_balance: int,
        pool_reserves: tuple[int, int],
    ) -> int:
        """
        Returns the GIBS amount (wei) E2 should sell this cycle.

        Returns 0 in these cases:
          - hub_gibs_balance is zero (nothing to sell)
          - a previous sell is still within its monitoring window

        In CAPPED or PAUSED modes, returns a sell sized to PROBE_BASELINE_PCT
        (productive fallback). In PROBING/RE_PROBING modes, sized to probe_pct.
        In LOCKED mode, sized to sweet_spot_pct.

        Always capped at hub_gibs_balance. Auto-resets CAPPED/PAUSED if their
        timers have elapsed before the sizing decision.
        """
        if hub_gibs_balance <= 0:
            return 0
        if self.state.pending_sell is not None:
            return 0

        # Check timed auto-resets BEFORE sizing — may transition CAPPED/PAUSED → PROBING
        self._check_timed_resets()

        # Determine which impact % to use this call
        if self.state.mode == ProbeMode.LOCKED:
            target_pct = self.state.sweet_spot_pct or _config.PROBE_BASELINE_PCT
        elif self.state.mode in (ProbeMode.CAPPED, ProbeMode.PAUSED):
            target_pct = _config.PROBE_BASELINE_PCT
        else:  # PROBING or RE_PROBING
            target_pct = self.state.probe_pct

        target_wei = solve_for_impact(target_pct, pool_reserves)
        if target_wei > hub_gibs_balance:
            return hub_gibs_balance
        return target_wei
```

Then add the helper method to the class (also new in this task):

```python
    def _check_timed_resets(self) -> None:
        """Check CAPPED and PAUSED auto-reset timers, transition if expired."""
        current = self._current_block()
        if (self.state.mode == ProbeMode.CAPPED
                and self.state.capped_entry_block is not None
                and current >= self.state.capped_entry_block + _config.PROBE_CAPPED_AUTO_RESET_BLOCKS):
            self.state.mode = ProbeMode.PROBING
            self.state.probe_pct = _config.PROBE_BASELINE_PCT
            self.state.capped_entry_block = None
            self._persist()
        elif (self.state.mode == ProbeMode.PAUSED
                and self.state.paused_entry_block is not None
                and current >= self.state.paused_entry_block + _config.PROBE_CAP_LOOP_PAUSE_BLOCKS):
            self.state.mode = ProbeMode.PROBING
            self.state.probe_pct = _config.PROBE_BASELINE_PCT
            self.state.paused_entry_block = None
            self.state.cap_loop_count = 0
            self._persist()
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_state_capped.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_state_capped.py
git commit -m "feat(probe): CAPPED auto-reset after 3 blocks via _check_timed_resets"
```

---

## Task 10: LOCKED → RE_PROBING after K=2 failures

**Files:**
- Test: `scripts/Joystick/tests/unit/test_probe_state_locked.py`

The state transitions are already implemented in Task 7's `_on_no_response`. This task adds the test that exercises them and verifies the K=2 failure threshold.

- [ ] **Step 1: Write the test**

Create `scripts/Joystick/tests/unit/test_probe_state_locked.py`:

```python
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


def _no_response_cycle(pc, sell_block, current_block):
    pc.record_sell(8 * 10**18, sell_block, f"0x{sell_block:x}")
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=current_block):
        pc.check_arb_response()


def test_locked_failure_increments_counter(pc):
    _no_response_cycle(pc, 100, 106)
    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.consecutive_failures == 1


def test_locked_to_reprobing_after_two_failures(pc):
    _no_response_cycle(pc, 100, 106)
    _no_response_cycle(pc, 110, 116)
    assert pc.state.mode == ProbeMode.RE_PROBING
    assert pc.state.sweet_spot_pct is None
    assert pc.state.probe_pct == pytest.approx(3.0)  # 4.0 - 1.0
    assert pc.state.consecutive_failures == 0


def test_locked_arb_resets_failure_counter(pc):
    """A successful arb during LOCKED resets failures back to 0."""
    _no_response_cycle(pc, 100, 106)
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
    _no_response_cycle(pc, 200, 206)
    _no_response_cycle(pc, 210, 216)
    assert pc.state.mode == ProbeMode.RE_PROBING
    assert pc.state.probe_pct == pytest.approx(config.PROBE_BASELINE_PCT)
```

- [ ] **Step 2: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_state_locked.py -v
```

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/unit/test_probe_state_locked.py
git commit -m "test(probe): LOCKED failure counting and RE_PROBING entry"
```

---

## Task 11: RE_PROBING successful re-lock at lower sweet spot

**Files:**
- Test: `scripts/Joystick/tests/unit/test_probe_state_reprobing.py`

- [ ] **Step 1: Write the test**

Create `scripts/Joystick/tests/unit/test_probe_state_reprobing.py`:

```python
"""Test RE_PROBING → LOCKED with the new (lower) sweet spot."""
from unittest.mock import patch

import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
)


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
    pc.record_sell(50 * 10**18, 100, "0xdead")
    fake_swap = {
        "blockNumber": 102,
        "transactionHash": "0xbeef",
        "args": {
            "sender": "0xc078c8da" + "0" * 32,
            "amount0In": 0,
            "amount1In": 1500 * 10**18,
            "amount0Out": 35 * 10**18,
            "amount1Out": 0,
        },
    }
    with patch.object(pc, "_get_swap_logs", return_value=[fake_swap]), \
         patch.object(pc, "_current_block", return_value=103):
        pc.check_arb_response()

    assert pc.state.mode == ProbeMode.LOCKED
    assert pc.state.sweet_spot_pct == pytest.approx(3.0)
    assert pc.state.last_arb_gibs == 35 * 10**18


def test_reprobing_no_response_escalates(pc):
    """RE_PROBING + no_response → probe_pct + 1."""
    pc.record_sell(50 * 10**18, 100, "0xdead")
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=106):
        pc.check_arb_response()
    assert pc.state.mode == ProbeMode.RE_PROBING
    assert pc.state.probe_pct == pytest.approx(4.0)  # 3.0 + 1.0


def test_reprobing_can_hit_cap(pc):
    """RE_PROBING escalation can also reach CAPPED."""
    pc.state.probe_pct = 9.5  # one step away from cap (10.0)
    pc.record_sell(50 * 10**18, 100, "0xdead")
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=106):
        pc.check_arb_response()
    assert pc.state.mode == ProbeMode.CAPPED
```

- [ ] **Step 2: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_state_reprobing.py -v
```

Expected: 3 tests pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/unit/test_probe_state_reprobing.py
git commit -m "test(probe): RE_PROBING re-lock at lower sweet spot"
```

---

## Task 12: PAUSED mode (cap_loop_count → PAUSED → auto-reset)

**Files:**
- Test: `scripts/Joystick/tests/unit/test_probe_state_paused.py`

- [ ] **Step 1: Write the test**

Create `scripts/Joystick/tests/unit/test_probe_state_paused.py`:

```python
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


def test_paused_entered_after_10_cap_loops(pc):
    """cap_loop_count reaching threshold triggers PAUSED."""
    # Force cap_loop_count to 9 by simulating 9 prior CAPPED entries
    pc.state.cap_loop_count = 9
    pc.state.mode = ProbeMode.PROBING
    pc.state.probe_pct = config.PROBE_MAX_IMPACT_PCT  # one step from cap

    # One more no_response should push us to CAPPED → which triggers PAUSED
    pc.record_sell(8 * 10**18, 100, "0xdead")
    with patch.object(pc, "_get_swap_logs", return_value=[]), \
         patch.object(pc, "_current_block", return_value=106):
        pc.check_arb_response()

    assert pc.state.mode == ProbeMode.PAUSED
    assert pc.state.paused_entry_block is not None


def test_paused_returns_baseline_size(pc):
    """In PAUSED, sell size is baseline."""
    pc.state.mode = ProbeMode.PAUSED
    pc.state.paused_entry_block = 500
    pc.state.cap_loop_count = 10
    R = (5000 * 10**18, 210_000 * 10**18)
    with patch.object(pc, "_current_block", return_value=510):
        result = pc.next_sell_gibs(1000 * 10**18, R)
    assert 7.0 < result / 1e18 < 8.0  # baseline


def test_paused_resets_after_30_blocks(pc):
    """At paused_entry + 30, auto-reset to PROBING with cap_loop_count cleared."""
    pc.state.mode = ProbeMode.PAUSED
    pc.state.paused_entry_block = 500
    pc.state.cap_loop_count = 10
    R = (5000 * 10**18, 210_000 * 10**18)
    with patch.object(pc, "_current_block", return_value=530):
        pc.next_sell_gibs(1000 * 10**18, R)
    assert pc.state.mode == ProbeMode.PROBING
    assert pc.state.cap_loop_count == 0
    assert pc.state.paused_entry_block is None


def test_paused_does_not_reset_before_30_blocks(pc):
    pc.state.mode = ProbeMode.PAUSED
    pc.state.paused_entry_block = 500
    pc.state.cap_loop_count = 10
    R = (5000 * 10**18, 210_000 * 10**18)
    with patch.object(pc, "_current_block", return_value=525):
        pc.next_sell_gibs(1000 * 10**18, R)
    assert pc.state.mode == ProbeMode.PAUSED
```

- [ ] **Step 2: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_state_paused.py -v
```

Expected: 4 tests pass. (No new implementation needed — Task 7's `_enter_capped` already handles the PAUSED transition, and Task 9's `_check_timed_resets` handles the 30-block reset.)

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/unit/test_probe_state_paused.py
git commit -m "test(probe): PAUSED entry, fallback, and auto-reset"
```

---

## Task 13: lp_add_target lifecycle

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (add `lp_add_target` and `clear_lp_add_target` methods)
- Test: `scripts/Joystick/tests/unit/test_probe_lp_add.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_lp_add.py`:

```python
"""Test lp_add_target lifecycle."""
from unittest.mock import patch

import pytest
from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
)


@pytest.fixture
def pc(tmp_path):
    return ProbeController(state_path=str(tmp_path / "probe.json"))


def test_lp_add_target_none_initially(pc):
    assert pc.lp_add_target() is None


def test_lp_add_target_set_after_arb(pc):
    """After an arb is detected, lp_add_target returns its size."""
    pc.record_sell(8 * 10**18, 100, "0xdead")
    fake_swap = {
        "blockNumber": 102,
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
         patch.object(pc, "_current_block", return_value=103):
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


def test_record_lp_add_failure_increments(pc):
    """record_lp_add_failure increments and clears after limit."""
    pc.state.last_arb_gibs = 47 * 10**18
    pc.record_lp_add_failure()
    assert pc.state.lp_add_failure_count == 1
    assert pc.state.last_arb_gibs == 47 * 10**18  # not yet cleared

    pc.record_lp_add_failure()
    assert pc.state.lp_add_failure_count == 2
    pc.record_lp_add_failure()
    # After 3 failures, target is force-cleared
    assert pc.state.lp_add_failure_count == 0
    assert pc.state.last_arb_gibs is None
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_lp_add.py -v
```

Expected: `AttributeError: 'ProbeController' object has no attribute 'lp_add_target'`.

- [ ] **Step 3: Implement the lp_add_target methods**

Add to the `ProbeController` class:

```python
    def lp_add_target(self) -> Optional[int]:
        """
        Return the GIBS amount (wei) to LP-add this cycle, or None.

        After a successful arb, last_arb_gibs is set to the arb's buy size.
        E2 calls lp_add_target() after the response check; if non-None,
        E2 executes a Hub LP-only TX sized to match. On success, E2 calls
        clear_lp_add_target(). On failure, record_lp_add_failure().
        """
        return self.state.last_arb_gibs

    def clear_lp_add_target(self) -> None:
        """Mark the LP-add as successfully completed."""
        self.state.last_arb_gibs = None
        self.state.lp_add_failure_count = 0
        self._persist()

    def record_lp_add_failure(self) -> None:
        """
        Increment the LP-add failure counter. After PROBE_LP_ADD_RETRY_LIMIT
        consecutive failures, force-clear the target to prevent poisoned state
        from blocking all future probes.
        """
        self.state.lp_add_failure_count += 1
        if self.state.lp_add_failure_count >= _config.PROBE_LP_ADD_RETRY_LIMIT:
            self.state.last_arb_gibs = None
            self.state.lp_add_failure_count = 0
        self._persist()
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_lp_add.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_lp_add.py
git commit -m "feat(probe): lp_add_target lifecycle with retry/clear semantics"
```

---

## Task 14: status() snapshot + stats tracking

**Files:**
- Modify: `scripts/Joystick/core/probe_controller.py` (add `status` method, stats counters in `ProbeState`)
- Test: `scripts/Joystick/tests/unit/test_probe_status.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_status.py`:

```python
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
    pc.record_sell(8 * 10**18, 100, "0xdead")
    fake_swap = {
        "blockNumber": 102,
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
         patch.object(pc, "_current_block", return_value=103):
        pc.check_arb_response()

    assert pc.status()["stats"]["arbs_detected_total"] == 1


def test_status_includes_human_readable_arb_size(pc):
    """last_arb_gibs in status is float GIBS, not wei."""
    pc.state.last_arb_gibs = 47_500_000_000_000_000_000
    s = pc.status()
    assert s["last_arb_gibs"] == pytest.approx(47.5)
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_status.py -v
```

Expected: `AttributeError: 'ProbeController' object has no attribute 'status'`.

- [ ] **Step 3: Implement stats counters and status()**

Replace the existing `ProbeState` dataclass (defined in Task 2) with this expanded version that includes stats fields. Note these are dataclass field DEFAULTS (no constructor changes for callers that don't pass them):

```python
@dataclass
class ProbeState:
    mode: ProbeMode
    probe_pct: float
    sweet_spot_pct: Optional[float]
    consecutive_failures: int
    capped_entry_block: Optional[int]
    paused_entry_block: Optional[int]
    cap_loop_count: int
    lp_add_failure_count: int
    pending_sell: Optional[PendingSell]
    last_arb_gibs: Optional[int]
    last_transition_ts: str
    # Stats counters (NEW in Task 14, added with default=0 so existing call sites
    # that don't pass them still work):
    sells_total: int = 0
    arbs_detected_total: int = 0
    cap_entries_total: int = 0
    pause_entries_total: int = 0
```

Update `_state_to_dict` (defined in Task 4) so the stats fields are included in the persisted dict. Append these lines to the end of `_state_to_dict` before the `return d`:

```python
    d["sells_total"] = state.sells_total
    d["arbs_detected_total"] = state.arbs_detected_total
    d["cap_entries_total"] = state.cap_entries_total
    d["pause_entries_total"] = state.pause_entries_total
```

Update `_state_from_dict` (also Task 4) to read stats fields with defaults of 0 for forward-compat with older state files. Add these as keyword args at the end of the `ProbeState(...)` constructor call:

```python
        sells_total=int(d.get("sells_total", 0)),
        arbs_detected_total=int(d.get("arbs_detected_total", 0)),
        cap_entries_total=int(d.get("cap_entries_total", 0)),
        pause_entries_total=int(d.get("pause_entries_total", 0)),
```

`_fresh_state` (Task 5) does not need changes — the dataclass defaults handle it.

Increment counters in the appropriate places:

```python
    # In record_sell, after creating PendingSell:
    self.state.sells_total += 1

    # In _on_arb_detected, at the start:
    self.state.arbs_detected_total += 1

    # In _enter_capped, at the start:
    self.state.cap_entries_total += 1
    # And inside the if-block that promotes to PAUSED:
    self.state.pause_entries_total += 1
```

Add the `status` method:

```python
    def status(self) -> dict:
        """Human-readable state snapshot for logs and dashboard routes."""
        last_arb_gibs_human = None
        if self.state.last_arb_gibs is not None:
            last_arb_gibs_human = self.state.last_arb_gibs / 1e18
        return {
            "mode": self.state.mode.value,
            "sweet_spot_pct": self.state.sweet_spot_pct,
            "probe_pct": self.state.probe_pct,
            "consecutive_failures": self.state.consecutive_failures,
            "pending_sell": (
                {
                    "sell_block": self.state.pending_sell.sell_block,
                    "deadline_block": self.state.pending_sell.deadline_block,
                    "tx_hash": self.state.pending_sell.sell_tx_hash,
                }
                if self.state.pending_sell else None
            ),
            "last_arb_gibs": last_arb_gibs_human,
            "cap_loop_count": self.state.cap_loop_count,
            "lp_add_failure_count": self.state.lp_add_failure_count,
            "last_transition_ts": self.state.last_transition_ts,
            "stats": {
                "sells_total": self.state.sells_total,
                "arbs_detected_total": self.state.arbs_detected_total,
                "cap_entries_total": self.state.cap_entries_total,
                "pause_entries_total": self.state.pause_entries_total,
            },
        }
```

- [ ] **Step 4: Run test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_status.py -v
```

Expected: 4 tests pass.

Also verify the existing tests still pass after adding stats fields:

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/ -v
```

Expected: ALL unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/core/probe_controller.py scripts/Joystick/tests/unit/test_probe_status.py
git commit -m "feat(probe): status() snapshot + stats counters"
```

---

## Task 15: Wire ProbeController into dss.py _execute_harvest

**Files:**
- Modify: `scripts/Joystick/engines/dss.py` (~50 line diff in `_execute_harvest` and `__init__`)
- Test: `scripts/Joystick/tests/unit/test_probe_dss_integration.py`

This task wires the controller into E2's harvest flow. Per the spec, the controller is a constructor parameter so tests can inject mocks.

- [ ] **Step 1: Write the failing test**

Create `scripts/Joystick/tests/unit/test_probe_dss_integration.py`:

```python
"""Test that DSSEngine correctly delegates to the ProbeController."""
from unittest.mock import MagicMock

import pytest


def test_dss_accepts_probe_controller_arg():
    """DSSEngine.__init__ should accept an optional probe_controller parameter."""
    from scripts.Joystick.engines.dss import DSSEngine
    from scripts.Joystick.core.probe_controller import ProbeController

    fake_pc = MagicMock(spec=ProbeController)
    engine = DSSEngine(probe_controller=fake_pc)
    assert engine.probe is fake_pc


def test_dss_creates_default_probe_if_not_passed():
    """If no probe_controller is passed, DSSEngine creates a default one."""
    from scripts.Joystick.engines.dss import DSSEngine
    from scripts.Joystick.core.probe_controller import ProbeController

    engine = DSSEngine()
    assert isinstance(engine.probe, ProbeController)
```

- [ ] **Step 2: Run test, verify it fails**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_dss_integration.py -v
```

Expected: `TypeError: DSSEngine.__init__() got an unexpected keyword argument 'probe_controller'`.

- [ ] **Step 3: Modify DSSEngine.__init__**

Find `__init__` in `scripts/Joystick/engines/dss.py`. Change its signature to accept an optional probe_controller, defaulting to a fresh instance:

```python
def __init__(self, probe_controller=None):
    super().__init__()
    # ... existing init code ...

    # Probe controller — adaptive sell sizing for GIBS/WPLS.
    # If not injected, create the default singleton.
    from ..core.probe_controller import ProbeController
    self.probe = probe_controller or ProbeController()
```

- [ ] **Step 4: Run constructor test, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_dss_integration.py::test_dss_accepts_probe_controller_arg -v
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/test_probe_dss_integration.py::test_dss_creates_default_probe_if_not_passed -v
```

Expected: both pass.

- [ ] **Step 5: Wire the controller calls into _execute_harvest**

Find `_execute_harvest` in `scripts/Joystick/engines/dss.py`. Near the top of the function, after the existing setup but BEFORE the existing simulate-and-build path, add:

```python
        # ── Probe controller integration ────────────────────────────
        # 1. Check if a previous sell got an arb response
        arb_response = self.probe.check_arb_response()
        if arb_response.kind.value == "PENDING":
            log.info("E2: probe pending — deferring this cycle")
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes="probe pending",
            )

        # 2. If we owe an LP-add from a recent successful arb, do it now
        lp_target = self.probe.lp_add_target()
        if lp_target is not None:
            try:
                lp_result = self._execute_lp_only_add(lp_target)
                if lp_result.success:
                    self.probe.clear_lp_add_target()
                else:
                    self.probe.record_lp_add_failure()
                    log.warning("E2: lp_add_target failed: %s", lp_result.notes)
            except Exception as exc:
                self.probe.record_lp_add_failure()
                log.error("E2: lp_add_target exception: %s", exc)
```

Then locate the existing sell-sizing logic (where `mint_count` and the sell amount are computed). Replace the static sizing with a call to the controller. Look for code like `mint_count = HARVEST_MINT_COUNT` followed by sell sizing — replace the sell GIBS calculation with:

```python
        # 3. Ask the controller for the sell size this cycle
        pool_reserves = self._read_gibs_wpls_reserves()  # see helper below
        hub_gibs = safe(erc20(GIBS_LAU), "balanceOf", JOYSTICK_HUB) or 0
        sell_gibs_wei = self.probe.next_sell_gibs(hub_gibs, pool_reserves)
        if sell_gibs_wei == 0:
            log.info("E2: probe controller returned 0 — skipping sell")
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes="probe returned 0",
            )

        # Convert sell_gibs_wei to mint_count needed (round up):
        mint_count = (sell_gibs_wei + 10**18 - 1) // 10**18
```

Find where the sell TX is submitted and the receipt is obtained. After the receipt is confirmed, add:

```python
        # 4. Record the sell with the controller
        self.probe.record_sell(
            sell_gibs_wei=sell_gibs_wei,
            block_number=receipt["blockNumber"],
            tx_hash=tx_hash_hex,
        )
```

You'll also need a helper to read pool reserves and a helper for LP-only add. Add these as private methods on `DSSEngine`:

```python
    def _read_gibs_wpls_reserves(self) -> tuple[int, int]:
        """Returns (R_gibs_wei, R_wpls_wei) at current block."""
        from ..core.config import GIBS_LAU, GIBS_WPLS_V2_PAIR
        from ..core.chain import pair_contract, safe
        pair = pair_contract(GIBS_WPLS_V2_PAIR)
        reserves = safe(pair, "getReserves")
        token0 = safe(pair, "token0")
        if not reserves or not token0:
            return (0, 0)
        r0, r1 = int(reserves[0]), int(reserves[1])
        if token0.lower() == GIBS_LAU.lower():
            return (r0, r1)
        return (r1, r0)

    def _execute_lp_only_add(self, gibs_wei: int) -> EngineResult:
        """Submit a Hub mintLPAndSell with lp_bps=10000 (LP only, no sell)."""
        # Compute proportional WPLS needed for the LP side from current reserves
        gibs_r, wpls_r = self._read_gibs_wpls_reserves()
        if gibs_r == 0 or wpls_r == 0:
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes="lp_only_add: failed to read reserves",
            )
        wpls_needed = int((gibs_wei * wpls_r // gibs_r) * 105 // 100)  # 5% cushion
        mint_count = (gibs_wei + 10**18 - 1) // 10**18

        try:
            hub = self._get_hub_submit()
        except Exception as exc:
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes=f"lp_only_add: hub init failed: {exc}",
            )

        log.info(
            "E2: lp_only_add — mintLPAndSell(%d, lp_bps=10000, burn_bps=0) value=%.2f PLS",
            mint_count, wpls_needed / 1e18,
        )
        try:
            r = send_tx(
                hub.functions.mintLPAndSell(
                    mint_count, 10000, 0,  # lp_bps=10000 (all LP), burn_bps=0
                    1,  # lp_dex = V2
                    0, [], 0,  # no sell
                ),
                f"lpOnlyAdd({mint_count})",
                dry_run=False, value=wpls_needed,
                skip_simulate=True, fixed_gas=750_000, gas_tier="fast",
            )
            if r:
                return EngineResult(
                    success=True, profit_wei=0,
                    gas_wei=r["gasUsed"] * r.get("effectiveGasPrice", 0),
                    tx_hashes=[r["transactionHash"].hex()],
                    notes=f"LP-only add: {mint_count} GIBS",
                )
        except Exception as exc:
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes=f"lp_only_add: tx failed: {exc}",
            )
        return EngineResult(
            success=False, profit_wei=0, gas_wei=0,
            tx_hashes=[], notes="lp_only_add: send_tx returned None",
        )
```

- [ ] **Step 6: Run all unit tests, verify pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/Joystick/engines/dss.py scripts/Joystick/tests/unit/test_probe_dss_integration.py
git commit -m "feat(probe): wire ProbeController into E2 _execute_harvest"
```

---

## Task 16: bot.py — instantiate ProbeController singleton

**Files:**
- Modify: `scripts/Joystick/bot.py` (instantiate ProbeController, pass to DSSEngine)

- [ ] **Step 1: Locate the engine list in bot.py**

Find the `all_engines = [...]` list inside `DysnomiaBot.__init__` (around line 125 in the current version). It currently looks like:

```python
all_engines = [
    ArbEngine(),
    DSSEngine(),
    BeatEngine(with_cheon=True),
    TokenFactoryEngine(),
    LAUEngine(),
    TreasurySniperEngine(),
    SpineRunnerEngine(),
    PhreakEngine(),
]
```

- [ ] **Step 2: Instantiate the controller and pass it in**

Modify the engine list to construct the probe controller once and pass it into `DSSEngine`:

```python
from .core.probe_controller import ProbeController
self.probe_controller = ProbeController()
log.info("ProbeController loaded: mode=%s, sweet_spot_pct=%s",
         self.probe_controller.state.mode.value,
         self.probe_controller.state.sweet_spot_pct)

all_engines = [
    ArbEngine(),
    DSSEngine(probe_controller=self.probe_controller),
    BeatEngine(with_cheon=True),
    TokenFactoryEngine(),
    LAUEngine(),
    TreasurySniperEngine(),
    SpineRunnerEngine(),
    PhreakEngine(),
]
```

The `ProbeController` import should go at the top of `bot.py` with the other engine imports.

- [ ] **Step 3: Verify the bot still imports cleanly**

```bash
/opt/joystick/venv/bin/python -c "
import sys; sys.path.insert(0, '/opt/joystick/repo')
from scripts.Joystick import bot
print('bot.py imports OK')
"
```

Expected: `bot.py imports OK`. If you see an ImportError, check the import location of `ProbeController`.

- [ ] **Step 4: Verify all unit tests still pass**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/Joystick/bot.py
git commit -m "feat(probe): instantiate ProbeController singleton in bot.py"
```

---

## Task 17: Anvil integration — real sell + record_sell round-trip

**Files:**
- Create: `scripts/Joystick/tests/test_probe_integration.py` (in the existing tests/ dir, NOT tests/unit/, so it gets the Anvil fixtures)

- [ ] **Step 1: Verify Anvil is running**

```bash
curl -s -X POST -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' \
  http://127.0.0.1:8545
```

Expected: `{"jsonrpc":"2.0","id":1,"result":"0x171"}` (chain 369). If not running, start it:

```bash
anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate &
```

- [ ] **Step 2: Write the integration test**

Create `scripts/Joystick/tests/test_probe_integration.py`:

```python
"""Integration tests for ProbeController against an Anvil mainnet fork."""
import pytest

from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
)


@pytest.fixture
def pc(tmp_path):
    return ProbeController(state_path=str(tmp_path / "probe.json"))


def test_record_sell_with_real_block(pc, w3, joystick_ready):
    """record_sell with a real Anvil block number sets up PendingSell correctly."""
    current_block = w3.eth.block_number
    pc.record_sell(
        sell_gibs_wei=8 * 10**18,
        block_number=current_block,
        tx_hash="0xdead",
    )
    assert pc.state.pending_sell is not None
    assert pc.state.pending_sell.sell_block == current_block
    assert pc.state.pending_sell.deadline_block == current_block + 5


def test_get_swap_logs_returns_list(pc, joystick_ready):
    """_get_swap_logs returns an empty list (or some events) without crashing."""
    logs = pc._get_swap_logs(from_block=1, to_block=2)
    # Just verify it returns a list — no assertions on content
    assert isinstance(logs, list)


def test_check_arb_response_no_pending_returns_no_response(pc, joystick_ready):
    """No pending sell → check_arb_response returns NO_RESPONSE."""
    r = pc.check_arb_response()
    assert r.kind.value == "NO_RESPONSE"
```

- [ ] **Step 3: Run the integration tests**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/test_probe_integration.py -v
```

Expected: 3 tests pass. If they skip, Anvil isn't running.

- [ ] **Step 4: Commit**

```bash
git add scripts/Joystick/tests/test_probe_integration.py
git commit -m "test(probe): Anvil integration — record_sell + get_swap_logs basics"
```

---

## Task 18: Anvil integration — arb event detection via real Swap log

**Files:**
- Modify: `scripts/Joystick/tests/test_probe_integration.py` (append a new test)

- [ ] **Step 1: Add the test**

Append to `scripts/Joystick/tests/test_probe_integration.py`:

```python
def test_arb_detected_via_real_pair_swap(pc, w3, fund_joey, joystick_ready):
    """
    Force a real Swap event on GIBS/WPLS by submitting a tiny WPLS→GIBS trade
    from a non-Joey, non-Hub address, then verify the controller detects it.
    """
    from web3 import Web3
    from scripts.Joystick.core.config import GIBS_WPLS_V2_PAIR, WPLS, GIBS_LAU

    # Create a fresh non-self address by impersonating a random hot wallet
    test_buyer = Web3.to_checksum_address("0x000000000000000000000000000000000000abcd")
    from scripts.Joystick.tests.anvil_helpers import set_balance, impersonate
    set_balance(test_buyer, 100_000 * 10**18, "http://127.0.0.1:8545")
    impersonate(test_buyer, "http://127.0.0.1:8545")

    sell_block = w3.eth.block_number
    pc.record_sell(8 * 10**18, sell_block, "0xdead")

    # Submit a small WPLS→GIBS swap on the V2 router from test_buyer
    # (This generates a real Swap event matching ARB_DETECTED criteria.)
    from scripts.Joystick.core.config import PULSEX_V2_ROUTER
    router_abi = [
        {"name": "swapExactTokensForTokens",
         "outputs": [{"type": "uint256[]"}],
         "inputs": [
             {"type": "uint256"}, {"type": "uint256"},
             {"type": "address[]"}, {"type": "address"}, {"type": "uint256"}
         ],
         "type": "function", "stateMutability": "nonpayable"},
    ]
    router = w3.eth.contract(address=PULSEX_V2_ROUTER, abi=router_abi)

    # First wrap PLS → WPLS for the test buyer
    wpls_abi = [{"name": "deposit", "outputs": [], "inputs": [], "type": "function",
                 "stateMutability": "payable"}]
    wpls = w3.eth.contract(address=WPLS, abi=wpls_abi)
    wpls.functions.deposit().transact({"from": test_buyer, "value": 50_000 * 10**18})

    # Approve router
    erc20_abi = [{"name": "approve", "outputs": [{"type": "bool"}],
                  "inputs": [{"type": "address"}, {"type": "uint256"}],
                  "type": "function", "stateMutability": "nonpayable"}]
    wpls_token = w3.eth.contract(address=WPLS, abi=erc20_abi)
    wpls_token.functions.approve(PULSEX_V2_ROUTER, 2**256 - 1).transact({"from": test_buyer})

    # Swap WPLS for GIBS
    deadline = 2**63 - 1
    router.functions.swapExactTokensForTokens(
        50_000 * 10**18, 0, [WPLS, GIBS_LAU], test_buyer, deadline,
    ).transact({"from": test_buyer})

    # Now the controller should detect an arb response
    r = pc.check_arb_response()
    assert r.kind.value == "ARB_DETECTED"
    assert r.gibs_size_wei > 0
    assert pc.state.mode == ProbeMode.LOCKED
```

- [ ] **Step 2: Run the test**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/test_probe_integration.py::test_arb_detected_via_real_pair_swap -v
```

Expected: PASS. (If the swap fails due to liquidity issues, reduce the test buyer's swap amount.)

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/test_probe_integration.py
git commit -m "test(probe): Anvil integration — arb detection via real Swap event"
```

---

## Task 19: Anvil integration — full LP-add cycle through Hub

**Files:**
- Modify: `scripts/Joystick/tests/test_probe_integration.py` (append a new test)

- [ ] **Step 1: Add the test**

Append to `scripts/Joystick/tests/test_probe_integration.py`:

```python
def test_lp_add_cycle_through_real_hub(pc, w3, fund_joey, patch_wallet, joystick_ready, E2):
    """
    Full sequence: simulate an arb response, then call E2's _execute_lp_only_add,
    verify Joey's GIBS/WPLS LP balance increases.
    """
    from scripts.Joystick.core.config import GIBS_WPLS_V2_PAIR, JOEY_WALLET
    from scripts.Joystick.core.chain import erc20

    # Inject the controller into the engine
    E2.probe = pc

    # Pre-arb LP balance
    lp_token = erc20(GIBS_WPLS_V2_PAIR)
    lp_before = lp_token.functions.balanceOf(JOEY_WALLET).call()

    # Simulate an arb that bought 5 GIBS
    pc.state.last_arb_gibs = 5 * 10**18

    # Execute LP-only add
    result = E2._execute_lp_only_add(5 * 10**18)
    assert result.success, f"lp_only_add failed: {result.notes}"

    # Verify LP balance grew
    lp_after = lp_token.functions.balanceOf(JOEY_WALLET).call()
    assert lp_after > lp_before, f"LP balance did not increase: {lp_before} → {lp_after}"

    # Verify clear_lp_add_target was called via E2's harvest path
    # (Note: this test bypasses _execute_harvest, so we call clear manually)
    pc.clear_lp_add_target()
    assert pc.lp_add_target() is None
```

- [ ] **Step 2: Run the test**

```bash
/opt/joystick/venv/bin/python -m pytest scripts/Joystick/tests/test_probe_integration.py::test_lp_add_cycle_through_real_hub -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/test_probe_integration.py
git commit -m "test(probe): Anvil integration — full LP-add cycle through Hub"
```

---

## Task 20: Manual mainnet smoke test checklist

This task is a checklist, not code. Before turning the controller loose on mainnet, follow this progressive rollout sequence (same approach used during the ladder rescue debug earlier).

- [ ] **Step 1: Set artificially low MAX_IMPACT_PCT**

Temporarily edit `scripts/Joystick/core/config.py`:
```python
PROBE_MAX_IMPACT_PCT = 2.0   # was 10.0 — limits slippage to ~40 PLS worst case
```

Do NOT commit this change. Revert after the test.

- [ ] **Step 2: Verify bot is stopped**

```bash
pgrep -af "scripts.Joystick.bot" | grep -v pgrep || echo "stopped"
```

- [ ] **Step 3: Run a single cycle in foreground**

```bash
set -a && source /opt/joystick/.env.pulse && set +a
ENGINE_EXCLUDE="Beat,LAU" /opt/joystick/venv/bin/python -u -m scripts.Joystick.bot --once 2>&1 | tee /tmp/probe_smoke.log
```

Watch for:
- Probe state log lines (`probe INFO state: ...`)
- One sell submitted with size ≤ 2% impact
- E2 returning normally

- [ ] **Step 4: Inspect probe state and event log**

```bash
cat scripts/Joystick/data/probe_state.json
tail -20 scripts/Joystick/data/events/probe.json
```

Verify the state file has expected fields and the event log has at least a `sell` event.

- [ ] **Step 5: Run continuously for 10 minutes**

```bash
ENGINE_EXCLUDE="Beat,LAU" nohup /opt/joystick/venv/bin/python -u -m scripts.Joystick.bot > /tmp/probe_run.log 2>&1 &
echo "PID=$!"
```

Wait 10 minutes (or ~10-20 cycles), then:

```bash
grep -E "probe |E2 CEREAL|state:|arb_detected" /tmp/probe_run.log | tail -40
```

Verify state transitions occur in the expected order (PROBING → escalation OR LOCKED).

- [ ] **Step 6: Stop the bot, raise the cap to 5%**

```bash
kill <PID>
sleep 3
pgrep -af "scripts.Joystick.bot" | grep -v pgrep || echo "stopped"
```

Edit config.py: `PROBE_MAX_IMPACT_PCT = 5.0`. Run another 10 minutes via the same nohup pattern. Verify behavior.

- [ ] **Step 7: Stop, restore default, commit nothing**

```bash
kill <PID>
```

Edit config.py back to `PROBE_MAX_IMPACT_PCT = 10.0`. Verify no changes are committed:

```bash
git diff scripts/Joystick/core/config.py
```

Should show no diff (you reverted to the committed default).

- [ ] **Step 8: Document the smoke test result**

Append a brief note to `lore/joey_diary_NN.md` (next available number) with:
- Date and block range of the smoke test
- Sweet spot found (or CAPPED, or unable to find)
- Any unexpected behavior
- Final state of `probe_state.json`

This is a manual operator checklist, no commit at this step unless you write the diary entry.

---

## Self-review checklist (run before declaring complete)

- [ ] All 20 tasks committed
- [ ] `pytest scripts/Joystick/tests/unit/ -v` shows all tests passing
- [ ] `pytest scripts/Joystick/tests/test_probe_integration.py -v` passes (with Anvil running)
- [ ] No `TODO`, `FIXME`, `XXX`, or `TBD` markers in `probe_controller.py`
- [ ] `bot.py --status` (if implemented) shows probe state
- [ ] Mainnet smoke test (Task 20) completed at PROBE_MAX_IMPACT_PCT ≤ 2%
- [ ] `git log --oneline | head -25` shows the task progression cleanly

---

## Spec → task coverage map

| Spec section | Task(s) |
|---|---|
| Architecture / module location | 2, 16 |
| Public API (5 methods) | 6, 7, 13, 14 |
| State machine — 5 modes | 8, 9, 10, 11, 12 |
| Sizing math | 3 |
| Persistence (load/save/recovery) | 4, 5 |
| Per-cycle data flow | 15 |
| Observability (logging + status) | 14, 15 (logging in dss diff) |
| Error handling — RPC failures | 7 (try/except in `_get_swap_logs`) |
| Error handling — sell TX failure | 7 (`record_sell` only on receipt) |
| Error handling — LP-add failure | 13 (`record_lp_add_failure`) |
| Error handling — hostile market | 9, 12 (CAPPED + PAUSED) |
| Error handling — state corruption | 4 |
| Testing layer 1 (unit) | 1-14 |
| Testing layer 2 (Anvil) | 17, 18, 19 |
| Testing layer 3 (mainnet smoke) | 20 |

---

## Files created summary

After all 20 tasks:

**New files**:
- `scripts/Joystick/core/probe_controller.py` (~500 lines)
- `scripts/Joystick/tests/unit/__init__.py`
- `scripts/Joystick/tests/unit/conftest.py`
- `scripts/Joystick/tests/unit/test_smoke.py`
- `scripts/Joystick/tests/unit/test_probe_constants.py`
- `scripts/Joystick/tests/unit/test_probe_dataclasses.py`
- `scripts/Joystick/tests/unit/test_probe_sizing.py`
- `scripts/Joystick/tests/unit/test_probe_persistence.py`
- `scripts/Joystick/tests/unit/test_probe_init.py`
- `scripts/Joystick/tests/unit/test_probe_next_sell.py`
- `scripts/Joystick/tests/unit/test_probe_response.py`
- `scripts/Joystick/tests/unit/test_probe_state_probing.py`
- `scripts/Joystick/tests/unit/test_probe_state_capped.py`
- `scripts/Joystick/tests/unit/test_probe_state_locked.py`
- `scripts/Joystick/tests/unit/test_probe_state_reprobing.py`
- `scripts/Joystick/tests/unit/test_probe_state_paused.py`
- `scripts/Joystick/tests/unit/test_probe_lp_add.py`
- `scripts/Joystick/tests/unit/test_probe_status.py`
- `scripts/Joystick/tests/unit/test_probe_dss_integration.py`
- `scripts/Joystick/tests/test_probe_integration.py`

**Modified files**:
- `scripts/Joystick/core/config.py` (10 PROBE_* constants)
- `scripts/Joystick/engines/dss.py` (`__init__` + `_execute_harvest` wiring + 2 helpers)
- `scripts/Joystick/bot.py` (instantiate ProbeController singleton)

**Untouched** (per spec scope):
- `scripts/Joystick/engines/arb.py`
- `scripts/Joystick/oracle/ladder_oracle.py`
- `_execute_ladder` in `dss.py` (the rescue path stays independent)
- All dashboard files
- All LP fee accounting modules
