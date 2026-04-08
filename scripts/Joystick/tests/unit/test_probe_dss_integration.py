"""Test that DSSEngine correctly delegates to the ProbeController.

Import note: dss.py pulls in executor → wallet at import time, and wallet
validates the DYSNOMIA_PRIVATE_KEY. The wallet stub is installed by the
unit-test conftest.py before any test collection runs, so imports here are
safe without any per-test setup.
"""
from unittest.mock import MagicMock

import pytest

from scripts.Joystick.engines.dss import DSSEngine
from scripts.Joystick.core.probe_controller import ProbeController


def test_dss_accepts_probe_controller_arg():
    """DSSEngine.__init__ should accept an optional probe_controller parameter."""
    fake_pc = MagicMock(spec=ProbeController)
    engine = DSSEngine(probe_controller=fake_pc)
    assert engine.probe is fake_pc


def test_dss_creates_default_probe_if_not_passed():
    """If no probe_controller is passed, DSSEngine creates a default one."""
    engine = DSSEngine()
    assert isinstance(engine.probe, ProbeController)
