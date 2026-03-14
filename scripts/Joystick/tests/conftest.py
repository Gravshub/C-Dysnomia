"""
conftest.py — Pytest fixtures for Anvil fork testing of Joystick.

Sets up:
  1. Environment variables BEFORE any Joystick module imports
  2. Anvil process management (start/stop)
  3. Joey wallet impersonation
  4. Per-test snapshot/revert isolation
  5. Web3 instance connected to Anvil

Usage:
  # Terminal 1:
  anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

  # Terminal 2:
  cd C-Dysnomia
  python -m pytest scripts/Joystick/tests/test_anvil_full.py -v
"""
import os
import sys
import time
import logging

import pytest
import requests

# ┌──────────────────────────────────────────────────────────────────────────┐
# │  STEP 1: Set env vars BEFORE any Joystick imports                       │
# │  This must happen at conftest load time, before pytest collects tests.  │
# └──────────────────────────────────────────────────────────────────────────┘

ANVIL_URL = "http://127.0.0.1:8545"
TGSV8_ADDR = "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32"
JOEY_ADDR = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"

# Point ALL RPCs to Anvil
os.environ["PULSECHAIN_RPC"] = ANVIL_URL
os.environ["PULSECHAIN_READ_RPC"] = ANVIL_URL
os.environ["PULSECHAIN_LOCAL_RPC"] = ANVIL_URL  # highest priority in RPCPool
os.environ["TGSV8_ADDRESS"] = TGSV8_ADDR

# Anvil default account key — won't match Joey, we handle that below
_ANVIL_DEFAULT_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
os.environ["DYSNOMIA_PRIVATE_KEY"] = _ANVIL_DEFAULT_KEY

# Reduce noise in test output
os.environ["RPC_MAX_RETRIES"] = "0"
os.environ["RPC_CB_THRESHOLD"] = "100"

# Ensure the repo root is on the path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

log = logging.getLogger("joystick.test")


# ┌──────────────────────────────────────────────────────────────────────────┐
# │  Anvil connection check                                                  │
# └──────────────────────────────────────────────────────────────────────────┘

def _anvil_is_alive(url: str = ANVIL_URL, timeout: float = 2.0) -> bool:
    """Check if Anvil is running and responding."""
    try:
        r = requests.post(url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_chainId", "params": [],
        }, timeout=timeout)
        return r.status_code == 200 and "result" in r.json()
    except Exception:
        return False


# ┌──────────────────────────────────────────────────────────────────────────┐
# │  Session-scoped fixtures                                                 │
# └──────────────────────────────────────────────────────────────────────────┘

@pytest.fixture(scope="session")
def anvil_url():
    """Verify Anvil is running. Tests require an external Anvil process."""
    if not _anvil_is_alive():
        pytest.skip(
            "Anvil not running. Start it with:\n"
            "  anvil --fork-url https://rpc-pulsechain.g4mm4.io "
            "--chain-id 369 --auto-impersonate"
        )
    return ANVIL_URL


@pytest.fixture(scope="session")
def w3(anvil_url):
    """Web3 instance connected to Anvil."""
    from web3 import Web3
    w = Web3(Web3.HTTPProvider(anvil_url, request_kwargs={"timeout": 30}))
    assert w.is_connected(), "Web3 cannot connect to Anvil"
    chain_id = w.eth.chain_id
    assert chain_id == 369, f"Expected chain 369, got {chain_id}"
    return w


@pytest.fixture(scope="session")
def fund_joey(w3, anvil_url):
    """
    Fund Joey with PLS and impersonate him. Session-scoped — runs once.
    Also patches the wallet module so Joystick can send TXs as Joey.
    """
    from .anvil_helpers import set_balance, impersonate

    # Fund Joey with 2M PLS
    set_balance(JOEY_ADDR, 2_000_000 * 10**18, anvil_url)
    impersonate(JOEY_ADDR, anvil_url)

    # Fund TGSv8 with some PLS for native operations
    set_balance(TGSV8_ADDR, 10_000 * 10**18, anvil_url)

    # Verify
    bal = w3.eth.get_balance(w3.to_checksum_address(JOEY_ADDR))
    assert bal >= 1_000_000 * 10**18, f"Joey funding failed: {bal / 1e18} PLS"

    log.info("Joey funded: %.0f PLS, impersonation active", bal / 1e18)


@pytest.fixture(scope="session")
def patch_wallet(fund_joey):
    """
    Patch Joystick's wallet module to work with Anvil impersonation.

    Problem: wallet.py loads a private key and validates it matches JOEY_WALLET.
    On Anvil, we impersonate Joey so signatures don't matter, but the module
    still needs a valid account object.

    Solution: Create a mock account that has Joey's address and can sign
    (Anvil ignores signatures when impersonating).
    """
    from eth_account import Account
    from unittest.mock import MagicMock

    # Import wallet after env is set
    from scripts.Joystick.core import wallet

    # Create a fake account object
    fake_acct = Account.from_key(_ANVIL_DEFAULT_KEY)

    # Build a wrapper that has Joey's address but signs with the test key
    mock_acct = MagicMock(wraps=fake_acct)
    mock_acct.address = JOEY_ADDR
    # sign_transaction needs to work — delegate to the real account
    mock_acct.sign_transaction = fake_acct.sign_transaction

    wallet.account = mock_acct
    log.info("Wallet patched: account.address=%s", wallet.account.address)


@pytest.fixture(scope="session")
def joystick_ready(patch_wallet, w3):
    """
    Final session setup — ensures all Joystick modules are importable
    and the environment is correctly configured.
    """
    # Force-reimport chain.py to pick up Anvil RPC
    # (chain.py builds pools at import time from env vars we set above)
    from scripts.Joystick.core import config
    assert config.CHAIN_ID == 369

    block = w3.eth.block_number
    log.info("Joystick ready. Anvil block: %d", block)
    return True


# ┌──────────────────────────────────────────────────────────────────────────┐
# │  Per-test isolation                                                      │
# └──────────────────────────────────────────────────────────────────────────┘

@pytest.fixture(autouse=True)
def isolate(anvil_url, joystick_ready):
    """Snapshot before each test, revert after — full state isolation."""
    from .anvil_helpers import snapshot, revert
    snap_id = snapshot(anvil_url)
    yield snap_id
    revert(snap_id, anvil_url)


# ┌──────────────────────────────────────────────────────────────────────────┐
# │  Engine fixtures (deferred imports to avoid import-time RPC calls)       │
# └──────────────────────────────────────────────────────────────────────────┘

@pytest.fixture
def E1():
    from scripts.Joystick.engines.arb import ArbEngine
    return ArbEngine()

@pytest.fixture
def E2():
    from scripts.Joystick.engines.dss import DSSEngine
    return DSSEngine()

@pytest.fixture
def E3():
    from scripts.Joystick.engines.beat import BeatEngine
    return BeatEngine(with_cheon=True)

@pytest.fixture
def E4():
    from scripts.Joystick.engines.token_factory import TokenFactoryEngine
    return TokenFactoryEngine()

@pytest.fixture
def E5():
    from scripts.Joystick.engines.lau import LAUEngine
    return LAUEngine()

@pytest.fixture
def E6():
    from scripts.Joystick.engines.treasury_sniper import TreasurySniperEngine
    return TreasurySniperEngine()

@pytest.fixture
def E7():
    from scripts.Joystick.engines.spine_runner import SpineRunnerEngine
    return SpineRunnerEngine()

@pytest.fixture
def E8():
    from scripts.Joystick.engines.phreak import PhreakEngine
    return PhreakEngine()

@pytest.fixture
def all_engines(E1, E2, E3, E4, E5, E6, E7, E8):
    return [E1, E2, E3, E4, E5, E6, E7, E8]

@pytest.fixture
def bot():
    """Create a DysnomiaBot instance (dry_run=True for safety)."""
    from scripts.Joystick.bot import DysnomiaBot
    return DysnomiaBot(dry_run=True, interactive=False)
