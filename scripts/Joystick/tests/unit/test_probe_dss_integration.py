"""Test that DSSEngine correctly delegates to the ProbeController.

Import note: dss.py pulls in executor → wallet at import time, and wallet
validates the DYSNOMIA_PRIVATE_KEY. We stub the wallet module before importing
dss so these constructor-only tests can run without a real key.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest


def _stub_wallet():
    """Insert a minimal wallet stub into sys.modules before dss.py is imported."""
    pkg = "scripts.Joystick.core"
    mod_name = f"{pkg}.wallet"
    if mod_name in sys.modules:
        return  # already imported (real or stubbed) — leave it alone
    stub = types.ModuleType(mod_name)
    stub.account = MagicMock()
    stub.reset_nonce = MagicMock()
    stub.next_nonce = MagicMock(return_value=0)
    stub.get_balance = MagicMock(return_value=0)
    sys.modules[mod_name] = stub


def test_dss_accepts_probe_controller_arg():
    """DSSEngine.__init__ should accept an optional probe_controller parameter."""
    _stub_wallet()
    from scripts.Joystick.engines.dss import DSSEngine
    from scripts.Joystick.core.probe_controller import ProbeController

    fake_pc = MagicMock(spec=ProbeController)
    engine = DSSEngine(probe_controller=fake_pc)
    assert engine.probe is fake_pc


def test_dss_creates_default_probe_if_not_passed():
    """If no probe_controller is passed, DSSEngine creates a default one."""
    _stub_wallet()
    from scripts.Joystick.engines.dss import DSSEngine
    from scripts.Joystick.core.probe_controller import ProbeController

    engine = DSSEngine()
    assert isinstance(engine.probe, ProbeController)
