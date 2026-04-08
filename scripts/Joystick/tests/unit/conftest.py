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

    SKIP if the parent conftest has set up integration mode (indicated by
    PULSECHAIN_LOCAL_RPC env var). In integration mode the parent conftest
    uses patch_wallet to set up proper impersonation and we must NOT stub
    the real module.

    Note: the parent conftest always sets PULSECHAIN_LOCAL_RPC (even for
    unit-only runs), so we cannot use its mere presence as the sole signal.
    Instead we speculatively try to import the real wallet. If it succeeds
    (e.g. the real Joey key is available, or a future test-harness setup has
    pre-configured the env), we leave sys.modules alone. If it fails
    (key mismatch) we install the stub so DSSEngine can be imported during
    collection without a real key.

    The stub exposes the full surface that executor.py and arb.py reach so
    that combined (unit + integration) runs fail with a meaningful error
    rather than an AttributeError on a missing attribute.
    """
    import os
    import sys
    import types
    import importlib

    mod_name = "scripts.Joystick.core.wallet"

    # If real wallet is already loaded and working, leave it alone.
    if mod_name in sys.modules:
        return

    # Speculatively try to import the real wallet module. If the env is
    # configured with a matching key (real key or future harness setup),
    # this succeeds and we're done. On failure (key mismatch / no key),
    # clean up and fall through to install the stub.
    try:
        importlib.import_module(mod_name)
        return  # real wallet loaded — nothing to do
    except Exception:
        sys.modules.pop(mod_name, None)

    stub = types.ModuleType(mod_name)
    class _StubAccount:
        address = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
        def sign_transaction(self, tx):
            raise RuntimeError("wallet stub: not for real signing")
    stub.account = _StubAccount()
    # Expose next_nonce so executor.py doesn't raise AttributeError when
    # the stub is active during combined (unit + integration) runs.
    stub.next_nonce = lambda: (_ for _ in ()).throw(
        RuntimeError("wallet stub: not for real nonce")
    )
    sys.modules[mod_name] = stub


_install_wallet_stub()


@pytest.fixture(autouse=True)
def isolate():
    """No-op override of the parent isolate fixture (which requires Anvil)."""
    yield
