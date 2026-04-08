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
