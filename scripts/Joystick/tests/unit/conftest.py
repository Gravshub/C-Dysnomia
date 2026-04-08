"""
Unit test conftest — overrides parent tests/conftest.py to disable
Anvil dependency. Tests in this directory must NOT touch the network or
import any module that triggers RPC connections at import time.
"""
import sys
import types

import pytest


def _install_wallet_stub():
    """
    Stub scripts.Joystick.core.wallet in sys.modules before any test
    imports DSSEngine. The real wallet module validates DYSNOMIA_PRIVATE_KEY
    at import time and raises if the address doesn't match JOEY_WALLET —
    unit tests can't supply a real key, so we replace the module entirely.
    """
    mod_name = "scripts.Joystick.core.wallet"
    if mod_name in sys.modules:
        return
    stub = types.ModuleType(mod_name)
    # Minimal surface: the wallet module exposes `account` (with `.address`
    # attribute) and usually `nonce_manager`. Provide both as attribute
    # dummies so code that reaches them doesn't crash on AttributeError.
    class _StubAccount:
        address = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
        def sign_transaction(self, tx):
            raise RuntimeError("wallet stub: not for real signing")
    stub.account = _StubAccount()
    sys.modules[mod_name] = stub


_install_wallet_stub()


@pytest.fixture(autouse=True)
def isolate():
    """No-op override of the parent isolate fixture (which requires Anvil)."""
    yield
