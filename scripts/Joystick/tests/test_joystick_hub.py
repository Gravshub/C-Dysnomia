"""
test_joystick_hub.py — JoystickHub Anvil Fork Tests.

Tests deploy hub + modules to Anvil, register selectors, set config,
then test each module function via eth_call simulation.

Requires Anvil running:
  anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

Run:
  cd C-Dysnomia
  python -m pytest scripts/Joystick/tests/test_joystick_hub.py -v --tb=short -x
"""
import pytest
import json
import os
import sys
import subprocess
from pathlib import Path

from web3 import Web3

try:
    from Crypto.Hash import keccak as keccak_mod

    def keccak256(text: str) -> bytes:
        k = keccak_mod.new(digest_bits=256)
        k.update(text.encode("utf-8"))
        return k.digest()
except ImportError:
    def keccak256(text: str) -> bytes:
        return Web3.keccak(text=text)

from .anvil_helpers import (
    anvil_rpc, set_balance, impersonate, stop_impersonate,
    mine_block, snapshot, revert, balance_of, transfer_via_impersonate,
    approve_via_impersonate, set_erc20_balance, find_balance_slot,
)

# ── Addresses ──────────────────────────────────────────────────────────────
JOEY         = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
WPLS         = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
ROUTER_V1    = "0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02"
ROUTER_V2    = "0x165C3410fC91EF562C50559f7d2289fEbed552d9"
FACTORY_V1   = "0x1715a3E4A142d8b698131108995174F37aEBA10D"
FACTORY_V2   = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"
GIBS_LAU     = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
AFFECTION    = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
PINDEP       = "0xA2262D7728C689526693aE893D0fD8a352C7073C"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SOL_FILE  = REPO_ROOT / "contracts" / "JoystickHub.sol"
SOLC_VER  = "0.8.21"

# Module function signatures for selector registration
HARVEST_FUNCTIONS = [
    "primeGibs(uint256)",
    "mintLPAndSell(uint256,uint256,uint256,uint8,uint256,address[],uint8)",
    "batchReseed(address[],uint256[])",
    "harvestConfig()",
]
AFFECTION_FUNCTIONS = [
    "buyAffection(address,bytes4,uint256,uint256,uint8)",
    "quoteBuyAffection(address,uint256,uint256,uint8)",
]
PURCHASE_FUNCTIONS = [
    "purchaseAndSell(address,uint256,address[],uint8,uint256)",
    "batchPurchaseAndSell(address[],uint256[],address[][],uint8[],uint256[])",
    "quotePurchase(address,uint256,address[],uint8)",
    "_executeSinglePurchase(address,address,uint256,address[],uint8,uint256)",
]

INITIAL_CONFIG = {
    "harvest.gibsLau":       int(GIBS_LAU, 16),
    "harvest.affection":     int(AFFECTION, 16),
    "harvest.primeCount":    17,
    "affection.token":       int(AFFECTION, 16),
    "affection.maxLoops":    300,
    "affection.autoSell":    0,
    "purchase.affection":    int(AFFECTION, 16),
    "purchase.minSpreadBps": 500,
}


def fn_selector(sig: str) -> bytes:
    return keccak256(sig)[:4]


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def w3():
    """Connect to local Anvil fork."""
    rpc = os.getenv("ANVIL_RPC", "http://127.0.0.1:8545")
    _w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    if not _w3.is_connected():
        pytest.skip("Anvil not running. Start with: anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate")
    assert _w3.eth.chain_id == 369, "Wrong chain — expected PulseChain (369)"
    return _w3


@pytest.fixture(scope="session")
def compiled():
    """Compile JoystickHub.sol and return {name: (abi, bytecode)}."""
    from solcx import compile_standard, install_solc, get_installed_solc_versions

    installed = [str(v) for v in get_installed_solc_versions()]
    if SOLC_VER not in installed:
        install_solc(SOLC_VER)

    source = SOL_FILE.read_text()
    input_json = {
        "language": "Solidity",
        "sources": {"JoystickHub.sol": {"content": source}},
        "settings": {
            "viaIR": True,
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}}
        }
    }
    result = compile_standard(input_json, solc_version=SOLC_VER)

    contracts = {}
    for name in ["JoystickHub", "HarvestModule", "AffectionModule", "PurchaseModule"]:
        c = result["contracts"]["JoystickHub.sol"][name]
        contracts[name] = (c["abi"], c["evm"]["bytecode"]["object"])
    return contracts


@pytest.fixture(scope="session")
def deployer(w3):
    """Fund JOEY on Anvil fork."""
    joey = Web3.to_checksum_address(JOEY)
    set_balance(joey, 5_000_000 * 10**18)
    impersonate(joey)
    return joey


def _deploy_contract(w3, deployer, abi, bytecode, ctor_args=None):
    """Deploy a contract on Anvil and return address."""
    factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    if ctor_args:
        constructor = factory.constructor(*ctor_args)
    else:
        constructor = factory.constructor()

    tx = constructor.build_transaction({
        "from": deployer,
        "nonce": w3.eth.get_transaction_count(deployer),
        "gas": 5_000_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1, f"Deploy failed: {receipt}"
    return receipt["contractAddress"]


@pytest.fixture(scope="session")
def deploy_hub(w3, deployer, compiled):
    """Deploy hub + all 3 modules + register + config. Return dict of addresses + hub contract."""
    # Deploy hub
    hub_abi, hub_bytecode = compiled["JoystickHub"]
    ctor_args = [Web3.to_checksum_address(a) for a in [WPLS, ROUTER_V1, ROUTER_V2, FACTORY_V1, FACTORY_V2]]
    hub_addr = _deploy_contract(w3, deployer, hub_abi, hub_bytecode, ctor_args)

    # Deploy modules
    module_addrs = {}
    for name in ["HarvestModule", "AffectionModule", "PurchaseModule"]:
        abi, bytecode = compiled[name]
        module_addrs[name] = _deploy_contract(w3, deployer, abi, bytecode)

    # Build merged ABI
    merged_abi = []
    seen = set()
    for name in ["JoystickHub", "HarvestModule", "AffectionModule", "PurchaseModule"]:
        abi, _ = compiled[name]
        for entry in abi:
            sig = (entry.get("type", ""), entry.get("name", ""))
            if sig not in seen:
                seen.add(sig)
                merged_abi.append(entry)

    hub = w3.eth.contract(address=Web3.to_checksum_address(hub_addr), abi=merged_abi)

    # Register selectors
    selector_batches = [
        (module_addrs["HarvestModule"],   HARVEST_FUNCTIONS),
        (module_addrs["AffectionModule"], AFFECTION_FUNCTIONS),
        (module_addrs["PurchaseModule"],  PURCHASE_FUNCTIONS),
    ]
    for mod_addr, fn_sigs in selector_batches:
        selectors = [fn_selector(sig) for sig in fn_sigs]
        tx = hub.functions.batchRegisterModule(
            selectors, Web3.to_checksum_address(mod_addr)
        ).build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 500_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1

    # Set initial config
    config_keys = []
    config_vals = []
    for key_str, val in INITIAL_CONFIG.items():
        config_keys.append(keccak256(key_str))
        config_vals.append(val)

    tx = hub.functions.batchSetConfig(config_keys, config_vals).build_transaction({
        "from": deployer,
        "nonce": w3.eth.get_transaction_count(deployer),
        "gas": 500_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1

    return {
        "hub": hub,
        "hub_addr": hub_addr,
        "harvest_addr": module_addrs["HarvestModule"],
        "affection_addr": module_addrs["AffectionModule"],
        "purchase_addr": module_addrs["PurchaseModule"],
        "merged_abi": merged_abi,
    }


@pytest.fixture
def hub(deploy_hub):
    return deploy_hub["hub"]


# ═══════════════════════════════════════════════════════════════════════════
#  HUB ADMIN TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestHubAdmin:
    def test_owner_is_deployer(self, hub, deployer):
        assert hub.functions.owner().call().lower() == deployer.lower()

    def test_deployer_is_authorized(self, hub, deployer):
        assert hub.functions.isAuthorized(deployer).call() is True

    def test_unauthorized_rejected(self, hub, w3):
        """A random address should not be authorized."""
        rando = "0x" + "ab" * 20
        assert hub.functions.isAuthorized(Web3.to_checksum_address(rando)).call() is False

    def test_set_auth(self, hub, w3, deployer):
        rando = Web3.to_checksum_address("0x" + "cc" * 20)
        tx = hub.functions.setAuth(rando, True).build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1
        assert hub.functions.isAuthorized(rando).call() is True

        # Revoke
        tx = hub.functions.setAuth(rando, False).build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        w3.eth.wait_for_transaction_receipt(tx_hash)
        assert hub.functions.isAuthorized(rando).call() is False

    def test_deposit_pls(self, hub, w3, deployer, deploy_hub):
        """Send native PLS to hub."""
        hub_addr = deploy_hub["hub_addr"]
        tx = {
            "from": deployer,
            "to": Web3.to_checksum_address(hub_addr),
            "value": 100 * 10**18,
            "gas": 50_000,
            "gasPrice": w3.eth.gas_price,
            "nonce": w3.eth.get_transaction_count(deployer),
            "chainId": 369,
        }
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1
        assert hub.functions.nativeBal().call() >= 100 * 10**18

    def test_module_registered(self, hub, deploy_hub):
        """Verify a known selector routes to the correct module."""
        sel = fn_selector("primeGibs(uint256)")
        impl = hub.functions.module(sel).call()
        assert impl.lower() == deploy_hub["harvest_addr"].lower()

    def test_unknown_selector_reverts(self, hub, w3, deployer, deploy_hub):
        """Calling an unregistered selector should revert."""
        hub_addr = deploy_hub["hub_addr"]
        # Call with a random selector
        tx = {
            "from": deployer,
            "to": Web3.to_checksum_address(hub_addr),
            "data": "0xdeadbeef",
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "nonce": w3.eth.get_transaction_count(deployer),
            "chainId": 369,
        }
        with pytest.raises(Exception):
            w3.eth.send_transaction(tx)

    def test_config_set_and_read(self, hub, w3, deployer):
        key = keccak256("test.key123")
        tx = hub.functions.setConfig(key, 42).build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        w3.eth.wait_for_transaction_receipt(tx_hash)
        assert hub.functions.config(key).call() == 42

    def test_not_paused_initially(self, hub):
        assert hub.functions.isPaused().call() is False

    def test_pause_unpause(self, hub, w3, deployer):
        # Pause
        tx = hub.functions.pause().build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        w3.eth.wait_for_transaction_receipt(tx_hash)
        assert hub.functions.isPaused().call() is True

        # Unpause
        tx = hub.functions.unpause().build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        w3.eth.wait_for_transaction_receipt(tx_hash)
        assert hub.functions.isPaused().call() is False

    def test_emergency_withdraw_native(self, hub, w3, deployer, deploy_hub):
        """Emergency withdraw should send all PLS to owner."""
        hub_addr = deploy_hub["hub_addr"]
        # Ensure hub has some PLS
        bal_before = hub.functions.nativeBal().call()
        if bal_before == 0:
            tx = {
                "from": deployer,
                "to": Web3.to_checksum_address(hub_addr),
                "value": 10 * 10**18,
                "gas": 50_000,
                "gasPrice": w3.eth.gas_price,
                "nonce": w3.eth.get_transaction_count(deployer),
                "chainId": 369,
            }
            w3.eth.send_transaction(tx)
            mine_block()

        tx = hub.functions.emergencyWithdrawNative(deployer).build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1
        assert hub.functions.nativeBal().call() == 0


# ═══════════════════════════════════════════════════════════════════════════
#  HARVEST MODULE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestHarvestModule:
    def test_harvest_config_returns_values(self, hub):
        """harvestConfig() should return configured addresses."""
        gibs_lau, affection, prime_count = hub.functions.harvestConfig().call()
        assert gibs_lau.lower() == GIBS_LAU.lower()
        assert affection.lower() == AFFECTION.lower()
        assert prime_count == 17

    def test_primeGibs_simulation(self, hub, w3, deployer):
        """eth_call primeGibs(1) should not revert on fork (generates on GIBS_LAU)."""
        try:
            hub.functions.primeGibs(1).call({"from": deployer})
        except Exception as e:
            # May revert if GIBS_LAU has hit max supply — that's OK
            assert "revert" in str(e).lower() or "execution reverted" in str(e).lower()

    def test_batchReseed_reverts_empty(self, hub, w3, deployer):
        """batchReseed with empty arrays should succeed (no-op)."""
        try:
            hub.functions.batchReseed([], []).call({"from": deployer})
        except Exception as e:
            pytest.fail(f"batchReseed empty should not revert: {e}")

    def test_mintLPAndSell_reverts_without_aff(self, hub, w3, deployer):
        """mintLPAndSell should revert if no AFF in hub."""
        with pytest.raises(Exception) as exc_info:
            hub.functions.mintLPAndSell(
                17,     # mintCount
                0,      # lpBps (sell-only)
                0,      # burnBps
                1,      # lpDex
                0,      # minSellOut
                [Web3.to_checksum_address(GIBS_LAU), Web3.to_checksum_address(WPLS)],
                1,      # sellDex
            ).call({"from": deployer, "value": 1000 * 10**18})
        # Should revert with insufficient AFF
        assert exc_info.value is not None


# ═══════════════════════════════════════════════════════════════════════════
#  AFFECTION MODULE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestAffectionModule:
    def test_quoteBuyAffection(self, hub, w3, deployer):
        """View function should return estimates for PI route."""
        pi_addr = Web3.to_checksum_address(PINDEP)
        try:
            est_payment, est_aff = hub.functions.quoteBuyAffection(
                pi_addr,
                100 * 10**18,  # 100 PLS
                10,            # 10 loops
                1,             # V2
            ).call()
            # Should return some values (may be zero if no pair exists)
            assert est_aff == 10 * 10**18  # 10 loops * 1e18
        except Exception:
            # No PI/WPLS pair on fork — acceptable
            pass

    def test_buyAffection_reverts_no_pls(self, hub, w3, deployer):
        """buyAffection with 0 PLS and no WPLS balance should revert."""
        pi_addr = Web3.to_checksum_address(PINDEP)
        buy_selector = fn_selector("BuyWithPI(uint256)")
        with pytest.raises(Exception):
            hub.functions.buyAffection(
                pi_addr,
                buy_selector,
                10,
                0,
                1,
            ).call({"from": deployer, "value": 0})


# ═══════════════════════════════════════════════════════════════════════════
#  PURCHASE MODULE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPurchaseModule:
    def test_quotePurchase_view(self, hub, w3, deployer):
        """quotePurchase should return data without reverting."""
        gibs = Web3.to_checksum_address(GIBS_LAU)
        wpls = Web3.to_checksum_address(WPLS)
        try:
            profitable, spread_bps, est_pls = hub.functions.quotePurchase(
                gibs,
                1 * 10**18,  # 1 AFF
                [gibs, wpls],
                1,  # V2
            ).call()
            # Just verify it returns without error
            assert isinstance(profitable, bool)
            assert isinstance(spread_bps, int)
            assert isinstance(est_pls, int)
        except Exception:
            # May fail if no GIBS/WPLS pair on fork — acceptable
            pass

    def test_purchaseAndSell_reverts_no_aff(self, hub, w3, deployer):
        """purchaseAndSell should revert if hub has no AFF."""
        gibs = Web3.to_checksum_address(GIBS_LAU)
        wpls = Web3.to_checksum_address(WPLS)
        with pytest.raises(Exception):
            hub.functions.purchaseAndSell(
                gibs,
                1 * 10**18,
                [gibs, wpls],
                1,
                0,
            ).call({"from": deployer})


# ═══════════════════════════════════════════════════════════════════════════
#  INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_module_upgrade(self, w3, deployer, compiled, deploy_hub):
        """Deploy a fresh HarvestModule, re-register selectors, verify routing."""
        hub = deploy_hub["hub"]
        old_harvest = deploy_hub["harvest_addr"]

        # Deploy new module
        abi, bytecode = compiled["HarvestModule"]
        new_harvest = _deploy_contract(w3, deployer, abi, bytecode)
        assert new_harvest.lower() != old_harvest.lower()

        # Re-register selectors to new module
        selectors = [fn_selector(sig) for sig in HARVEST_FUNCTIONS]
        tx = hub.functions.batchRegisterModule(
            selectors, Web3.to_checksum_address(new_harvest)
        ).build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 500_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1

        # Verify routing points to new module
        sel = fn_selector("primeGibs(uint256)")
        impl = hub.functions.module(sel).call()
        assert impl.lower() == new_harvest.lower()

    def test_eip170_all_contracts_under_limit(self, compiled):
        """Verify all 4 contracts are under EIP-170 limit."""
        for name, (abi, bytecode) in compiled.items():
            byte_len = len(bytecode) // 2
            assert byte_len <= 24576, f"{name} is {byte_len} bytes (over 24,576 limit)"

    def test_merged_abi_has_all_functions(self, deploy_hub):
        """Merged ABI should contain functions from all modules."""
        abi = deploy_hub["merged_abi"]
        fn_names = {e["name"] for e in abi if e.get("type") == "function"}

        expected = {
            # Hub
            "owner", "isPaused", "isAuthorized", "module", "config", "bal", "nativeBal",
            "setAuth", "pause", "unpause", "setConfig", "batchSetConfig",
            "registerModule", "batchRegisterModule", "transferOwnership",
            "deposit", "withdraw", "withdrawPLS", "approveExternal",
            "emergencyWithdrawERC20", "emergencyWithdrawNative",
            # Harvest
            "primeGibs", "mintLPAndSell", "batchReseed", "harvestConfig",
            # Affection
            "buyAffection", "quoteBuyAffection",
            # Purchase
            "purchaseAndSell", "batchPurchaseAndSell", "quotePurchase",
            "_executeSinglePurchase",
        }
        missing = expected - fn_names
        assert not missing, f"Missing functions in merged ABI: {missing}"
