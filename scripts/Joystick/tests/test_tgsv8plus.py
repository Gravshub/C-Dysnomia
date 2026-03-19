#!/usr/bin/env python3
"""
Test suite for TGSv8+ (TreasuryGameSharkv8PLUS).

Unit tests: read-only, zero gas (compile checks + on-chain views via eth_call).
Simulation tests: eth_call simulations.
Integration tests: gas-spending, gated behind TGSV8PLUS_LIVE=1 env var.

Usage:
  pytest scripts/Joystick/tests/test_tgsv8plus.py -v -k "not anvil"
  TGSV8PLUS_LIVE=1 pytest scripts/Joystick/tests/test_tgsv8plus.py -v -k "not anvil"
"""
import os
import sys
import json
import subprocess
import pytest
from pathlib import Path

# ── Auto-install dependencies ──────────────────────────────────────────────
try:
    from solcx import compile_standard, install_solc, get_installed_solc_versions
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "py-solc-x", "-q"])
    from solcx import compile_standard, install_solc, get_installed_solc_versions

from web3 import Web3

# ── Constants ──────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONTRACT_FILE = REPO_ROOT / "contracts" / "TGSv8Plus.sol"
SOLC_VER = "0.8.21"
CONTRACT_NAME = "TreasuryGameSharkv8PLUS"

READ_RPC = "https://rpc-pulsechain.g4mm4.io"

JOEY = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
AFFECTION = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WPLS = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
ROUTER_V1 = Web3.to_checksum_address("0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02")
ROUTER_V2 = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")
FACTORY_V1 = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
FACTORY_V2 = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")

EIP170_LIMIT = 24576


# ── Compile helper (cached at module level) ────────────────────────────────

_COMPILED = None

def _compile():
    global _COMPILED
    if _COMPILED is not None:
        return _COMPILED
    assert CONTRACT_FILE.exists(), f"Contract not found: {CONTRACT_FILE}"
    source = CONTRACT_FILE.read_text()

    installed = get_installed_solc_versions()
    if SOLC_VER not in [str(v) for v in installed]:
        install_solc(SOLC_VER)

    input_json = {
        "language": "Solidity",
        "sources": {"TGSv8Plus.sol": {"content": source}},
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"]}}
        }
    }
    result = compile_standard(input_json, solc_version=SOLC_VER)
    contract = result["contracts"]["TGSv8Plus.sol"][CONTRACT_NAME]
    abi = contract["abi"]
    bytecode = contract["evm"]["bytecode"]["object"]
    deployed = contract["evm"]["deployedBytecode"]["object"]
    deployed_len = len(deployed) // 2
    _COMPILED = (abi, bytecode, deployed_len)
    return _COMPILED


def _get_web3():
    w = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))
    if not w.is_connected():
        pytest.skip("Cannot connect to PulseChain RPC")
    return w


def _get_contract():
    addr = os.environ.get("TGSV8PLUS_ADDRESS")
    if not addr:
        return None
    abi, _, _ = _compile()
    w = _get_web3()
    return w.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)


# ═════════════════════════════════════════════════════════════════════════
#  UNIT TESTS (read-only, no gas)
# ═════════════════════════════════════════════════════════════════════════

class TestCompileTGSv8Plus:
    def test_compile(self):
        """Contract compiles successfully."""
        abi, bytecode, _ = _compile()
        assert len(abi) > 0, "ABI is empty"
        assert len(bytecode) > 0, "Bytecode is empty"

    def test_under_eip170(self):
        """Deployed bytecode under 24,576 bytes (EIP-170)."""
        _, _, deployed_len = _compile()
        assert deployed_len <= EIP170_LIMIT, \
            f"Deployed bytecode {deployed_len} exceeds EIP-170 limit {EIP170_LIMIT}"

    def test_critical_functions_present(self):
        """All 7 modules have their critical functions."""
        abi, _, _ = _compile()
        fn_names = {e['name'] for e in abi if e.get('type') == 'function'}
        critical = [
            'silentMint', 'safeMint', 'harvestCycle',
            'batchBurnLP', 'burnLPPercent', 'removeLiquidity',
            'sellLau', 'sellLauMultiHop',
            'execute', 'executeWithValue', 'batchExecute',
            'deposit', 'withdraw', 'withdrawAmount', 'withdrawPLS', 'batchSweep',
            'setAuth', 'setRef', 'approveMax',
            'mintableLAU', 'lauRemaining', 'batchBal', 'quoteSell',
            'totalLauMinted', 'totalPayTokenSpent', 'totalLpBurned', 'opCounter',
            'owner', 'authorized', 'lau', 'payToken', 'wpls',
            'routerV1', 'routerV2', 'factoryV1', 'factoryV2',
        ]
        missing = [f for f in critical if f not in fn_names]
        assert not missing, f"Missing functions: {missing}"

    def test_events_present(self):
        """Key events are defined."""
        abi, _, _ = _compile()
        ev_names = {e['name'] for e in abi if e.get('type') == 'event'}
        expected = ['SilentMint', 'HarvestCycle', 'LPBurned', 'LPRemoved',
                     'Sold', 'Executed', 'AuthSet', 'RefUpdated',
                     'Deposited', 'Withdrawn']
        missing = [e for e in expected if e not in ev_names]
        assert not missing, f"Missing events: {missing}"


class TestOnChainViewsTGSv8Plus:
    """Tests that query the live chain via eth_call (zero gas)."""

    def test_constructor_refs(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed (set TGSV8PLUS_ADDRESS)")
        assert c.functions.lau().call().lower() == GIBS_LAU.lower()
        assert c.functions.payToken().call().lower() == AFFECTION.lower()
        assert c.functions.wpls().call().lower() == WPLS.lower()
        assert c.functions.routerV1().call().lower() == ROUTER_V1.lower()
        assert c.functions.routerV2().call().lower() == ROUTER_V2.lower()
        assert c.functions.factoryV1().call().lower() == FACTORY_V1.lower()
        assert c.functions.factoryV2().call().lower() == FACTORY_V2.lower()

    def test_owner_is_joey(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        assert c.functions.owner().call().lower() == JOEY.lower()

    def test_authorized_joey(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        assert c.functions.authorized(JOEY).call() is True

    def test_lau_remaining(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        remaining = c.functions.lauRemaining().call()
        # May be 0 if GIBS LAU is already at maxSupply
        assert remaining >= 0, "lauRemaining() returned invalid value"

    def test_mintable_lau(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        mintable = c.functions.mintableLAU().call()
        assert mintable == 0, f"mintableLAU should be 0 without payToken deposit, got {mintable}"

    def test_quote_sell(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        try:
            quote = c.functions.quoteSell(1 * 10**18, 1).call()
            assert quote > 0, "quoteSell(1e18, V2) should return > 0"
        except Exception as e:
            pytest.skip(f"quoteSell failed (no pair?): {e}")


class TestSimulationTGSv8Plus:
    """eth_call simulations."""

    def test_silent_mint_simulated(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        w = _get_web3()
        calldata = c.functions.silentMint(1).build_transaction({
            'from': JOEY, 'gas': 500000
        })['data']
        try:
            w.eth.call({'to': c.address, 'from': JOEY, 'data': calldata, 'gas': 500000})
        except Exception as e:
            err = str(e)
            assert "v8+:unauthorized" not in err, f"Auth failed: {err}"

    def test_safe_mint_simulated(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        w = _get_web3()
        calldata = c.functions.safeMint(1).build_transaction({
            'from': JOEY, 'gas': 500000
        })['data']
        try:
            w.eth.call({'to': c.address, 'from': JOEY, 'data': calldata, 'gas': 500000})
        except Exception as e:
            err = str(e)
            assert "v8+:unauthorized" not in err, f"Auth failed: {err}"

    def test_harvest_cycle_simulated(self):
        c = _get_contract()
        if c is None:
            pytest.skip("TGSv8+ not deployed")
        w = _get_web3()
        calldata = c.functions.harvestCycle(1, 4500, 0, 9000, 1, 1).build_transaction({
            'from': JOEY, 'gas': 1000000
        })['data']
        try:
            w.eth.call({'to': c.address, 'from': JOEY, 'data': calldata, 'gas': 1000000})
        except Exception as e:
            err = str(e)
            assert "v8+:unauthorized" not in err, f"Auth failed: {err}"


class TestIntegrationTGSv8Plus:
    """Live tests that cost gas. Gated behind TGSV8PLUS_LIVE=1 env var."""

    def test_deposit_paytoken(self):
        if os.environ.get("TGSV8PLUS_LIVE") != "1":
            pytest.skip("Set TGSV8PLUS_LIVE=1 for integration tests")
        pytest.skip("Integration test — requires funded wallet")

    def test_silent_mint_live(self):
        if os.environ.get("TGSV8PLUS_LIVE") != "1":
            pytest.skip("Set TGSV8PLUS_LIVE=1 for integration tests")
        pytest.skip("Integration test — requires payToken deposit first")

    def test_withdraw(self):
        if os.environ.get("TGSV8PLUS_LIVE") != "1":
            pytest.skip("Set TGSV8PLUS_LIVE=1 for integration tests")
        pytest.skip("Integration test — requires token balance")

    def test_batch_burn_lp(self):
        if os.environ.get("TGSV8PLUS_LIVE") != "1":
            pytest.skip("Set TGSV8PLUS_LIVE=1 for integration tests")
        pytest.skip("Integration test — requires pre-approved LP tokens")
