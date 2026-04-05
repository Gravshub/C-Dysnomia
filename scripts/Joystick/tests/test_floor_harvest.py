"""
test_floor_harvest.py — Anvil fork tests for FloorHarvestModule.

Deploys FloorHarvestModule to an Anvil fork of PulseChain, registers it
on the live JoystickHub (forked state), sets config, and validates all
three functions: floorConfig, quoteFloorCycle, floorAndHarvest.

Requires Anvil running:
  anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

Run:
  cd C-Dysnomia
  python -m pytest scripts/Joystick/tests/test_floor_harvest.py -v --tb=short -x
"""
import pytest
import json
import logging
from pathlib import Path

from web3 import Web3

from .anvil_helpers import (
    set_balance, impersonate, stop_impersonate,
    balance_of, transfer_via_impersonate,
)

log = logging.getLogger("joystick.test.floor_harvest")

# ── Addresses ──────────────────────────────────────────────────────────────
JOEY       = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
HUB        = "0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14"
GIBS_LAU   = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
AFFECTION  = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
WPLS       = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
GIBS_WPLS  = "0x7BCa1c997c475eac9c61417e88bed158ACA757f0"
BURN_369   = "0x0000000000000000000000000000000000000369"

REPO_ROOT  = Path(__file__).resolve().parent.parent.parent.parent
ARTIFACT   = REPO_ROOT / "build" / "FloorHarvestModule" / "combined.json"

# ── FloorHarvestModule function signatures ─────────────────────────────────
FLOOR_FUNCTIONS = [
    "floorAndHarvest(uint256,uint256,uint256,bool,uint256)",
    "quoteFloorCycle(uint256,uint256,uint256)",
    "floorConfig()",
]

# ── Hub admin ABI (minimal — just what we need for registration/config) ────
HUB_ADMIN_ABI = [
    {
        "inputs": [
            {"name": "selectors", "type": "bytes4[]"},
            {"name": "impl", "type": "address"},
        ],
        "name": "batchRegisterModule",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "keys", "type": "bytes32[]"},
            {"name": "vals", "type": "uint256[]"},
        ],
        "name": "batchSetConfig",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "address"}],
        "name": "isAuthorized",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Minimal ERC20 ABI for funding operations
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

# WPLS deposit() for wrapping PLS
WPLS_ABI = ERC20_ABI + [
    {
        "constant": False,
        "inputs": [],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
]


def fn_selector(sig: str) -> bytes:
    """Compute 4-byte function selector from signature string."""
    return Web3.keccak(text=sig)[:4]


# ── Session-scoped fixtures ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def floor_compiled():
    """Load compiled FloorHarvestModule artifact. Skip if missing."""
    if not ARTIFACT.exists():
        pytest.skip(f"Compiled artifact not found: {ARTIFACT}")
    data = json.loads(ARTIFACT.read_text())
    abi = data["abi"]
    bytecode = data["bin"]
    if not bytecode.startswith("0x"):
        bytecode = "0x" + bytecode
    return abi, bytecode


@pytest.fixture(scope="session")
def floor_module(w3, fund_joey, floor_compiled):
    """Deploy FloorHarvestModule to Anvil. Returns deployed address."""
    abi, bytecode = floor_compiled
    joey = Web3.to_checksum_address(JOEY)

    factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = factory.constructor().build_transaction({
        "from": joey,
        "nonce": w3.eth.get_transaction_count(joey),
        "gas": 5_000_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1, f"FloorHarvestModule deploy failed: {receipt}"
    addr = receipt["contractAddress"]
    log.info("FloorHarvestModule deployed at %s", addr)
    return addr


@pytest.fixture(scope="session")
def floor_registered(w3, fund_joey, floor_module):
    """Register FloorHarvestModule selectors on the live JoystickHub."""
    joey = Web3.to_checksum_address(JOEY)
    hub_cs = Web3.to_checksum_address(HUB)
    mod_cs = Web3.to_checksum_address(floor_module)

    hub = w3.eth.contract(address=hub_cs, abi=HUB_ADMIN_ABI)

    # Verify Joey is the hub owner
    owner = hub.functions.owner().call()
    assert owner.lower() == joey.lower(), f"Hub owner is {owner}, expected Joey"

    selectors = [fn_selector(sig) for sig in FLOOR_FUNCTIONS]
    tx = hub.functions.batchRegisterModule(selectors, mod_cs).build_transaction({
        "from": joey,
        "nonce": w3.eth.get_transaction_count(joey),
        "gas": 500_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1, "batchRegisterModule failed"
    log.info("FloorHarvestModule selectors registered on Hub")
    return True


@pytest.fixture(scope="session")
def floor_configured(w3, fund_joey, floor_registered):
    """Set FloorHarvestModule config keys on the live JoystickHub."""
    joey = Web3.to_checksum_address(JOEY)
    hub_cs = Web3.to_checksum_address(HUB)

    hub = w3.eth.contract(address=hub_cs, abi=HUB_ADMIN_ABI)

    keys = [
        Web3.keccak(text="floor.gibsLau"),
        Web3.keccak(text="floor.affection"),
        Web3.keccak(text="floor.gibsWplsPair"),
        Web3.keccak(text="floor.gibsIsToken0"),
        Web3.keccak(text="floor.burnAddr"),
    ]
    vals = [
        int(GIBS_LAU, 16),
        int(AFFECTION, 16),
        int(GIBS_WPLS, 16),
        1,  # GIBS is token0 (0x66... < 0xa1...)
        int(BURN_369, 16),
    ]

    tx = hub.functions.batchSetConfig(keys, vals).build_transaction({
        "from": joey,
        "nonce": w3.eth.get_transaction_count(joey),
        "gas": 500_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1, "batchSetConfig failed"
    log.info("FloorHarvestModule config keys set on Hub")
    return True


@pytest.fixture
def hub_floor(w3, floor_configured, floor_compiled):
    """Hub contract instance with FloorHarvestModule ABI attached."""
    floor_abi, _ = floor_compiled
    hub_cs = Web3.to_checksum_address(HUB)

    # Merge Hub admin ABI with FloorHarvestModule ABI
    merged = list(HUB_ADMIN_ABI)
    seen = {(e.get("type", ""), e.get("name", "")) for e in merged}
    for entry in floor_abi:
        sig = (entry.get("type", ""), entry.get("name", ""))
        if sig not in seen:
            seen.add(sig)
            merged.append(entry)

    return w3.eth.contract(address=hub_cs, abi=merged)


# ── Funding helpers ────────────────────────────────────────────────────────

def fund_hub_with_wpls(w3, amount_wei, anvil_url):
    """Fund Hub with WPLS by wrapping PLS from Joey."""
    joey = Web3.to_checksum_address(JOEY)
    hub_cs = Web3.to_checksum_address(HUB)
    wpls_cs = Web3.to_checksum_address(WPLS)

    wpls = w3.eth.contract(address=wpls_cs, abi=WPLS_ABI)

    # Joey wraps PLS → WPLS
    tx = wpls.functions.deposit().build_transaction({
        "from": joey,
        "value": amount_wei,
        "nonce": w3.eth.get_transaction_count(joey),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    w3.eth.wait_for_transaction_receipt(tx_hash)

    # Transfer WPLS to Hub
    tx = wpls.functions.transfer(hub_cs, amount_wei).build_transaction({
        "from": joey,
        "nonce": w3.eth.get_transaction_count(joey),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    w3.eth.wait_for_transaction_receipt(tx_hash)


def fund_hub_with_aff(w3, amount_wei, anvil_url):
    """Fund Hub with AFFECTION by impersonating the AFFECTION contract."""
    aff_cs = Web3.to_checksum_address(AFFECTION)
    hub_cs = Web3.to_checksum_address(HUB)

    # Check AFFECTION contract self-balance
    aff_self_bal = balance_of(w3, aff_cs, aff_cs)

    if aff_self_bal < amount_wei:
        pytest.skip(
            f"AFFECTION self-balance too low: {aff_self_bal / 1e18:.0f} AFF "
            f"(need {amount_wei / 1e18:.0f})"
        )

    impersonate(aff_cs, anvil_url)
    set_balance(aff_cs, 1000 * 10**18, anvil_url)  # gas for impersonated TX (PulseChain gas is high)

    aff_c = w3.eth.contract(address=aff_cs, abi=ERC20_ABI)
    tx = aff_c.functions.transfer(hub_cs, amount_wei).build_transaction({
        "from": aff_cs,
        "nonce": w3.eth.get_transaction_count(aff_cs),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 369,
    })
    tx_hash = w3.eth.send_transaction(tx)
    w3.eth.wait_for_transaction_receipt(tx_hash)
    stop_impersonate(aff_cs, anvil_url)


# ═══════════════════════════════════════════════════════════════════════════
#  TestFloorConfig — Verify config view returns correct values
# ═══════════════════════════════════════════════════════════════════════════

class TestFloorConfig:
    """Verify floorConfig() returns the correct configured values."""

    def test_floor_config_returns_correct_gibs_lau(self, hub_floor):
        result = hub_floor.functions.floorConfig().call()
        gibs_lau = result[0]
        assert gibs_lau.lower() == GIBS_LAU.lower()

    def test_floor_config_returns_correct_affection(self, hub_floor):
        result = hub_floor.functions.floorConfig().call()
        affection = result[1]
        assert affection.lower() == AFFECTION.lower()

    def test_floor_config_returns_correct_pair(self, hub_floor):
        result = hub_floor.functions.floorConfig().call()
        pair = result[2]
        assert pair.lower() == GIBS_WPLS.lower()

    def test_floor_config_gibs_is_token0(self, hub_floor):
        result = hub_floor.functions.floorConfig().call()
        gibs_is_token0 = result[3]
        assert gibs_is_token0 is True

    def test_floor_config_burn_addr(self, hub_floor):
        result = hub_floor.functions.floorConfig().call()
        burn_addr = result[4]
        assert burn_addr.lower() == BURN_369.lower()


# ═══════════════════════════════════════════════════════════════════════════
#  TestQuoteFloorCycle — Verify quoting logic
# ═══════════════════════════════════════════════════════════════════════════

class TestQuoteFloorCycle:
    """Verify quoteFloorCycle() view function math and edge cases."""

    def test_quote_feasible_with_enough_wpls(self, hub_floor):
        """17 GIBS at 50% LP with 2000 WPLS should be feasible."""
        result = hub_floor.functions.quoteFloorCycle(
            17,                     # primeCount
            5000,                   # lpBps (50%)
            2000 * 10**18,          # wplsAvailable
        ).call()
        feasible, wplsNeeded, wplsFromSell, netWpls, lpGibs, sellGibs = result
        assert feasible is True
        assert lpGibs == 8_500000000000000000     # 17e18 * 5000 / 10000 = 8.5e18
        assert sellGibs == 8_500000000000000000   # 17e18 - 8.5e18 = 8.5e18
        assert wplsNeeded > 0
        assert wplsFromSell > 0

    def test_quote_infeasible_zero_prime(self, hub_floor):
        """primeCount=0 should be infeasible."""
        result = hub_floor.functions.quoteFloorCycle(0, 5000, 2000 * 10**18).call()
        feasible = result[0]
        assert feasible is False

    def test_quote_infeasible_zero_lpbps(self, hub_floor):
        """lpBps=0 should be infeasible."""
        result = hub_floor.functions.quoteFloorCycle(17, 0, 2000 * 10**18).call()
        feasible = result[0]
        assert feasible is False

    def test_quote_infeasible_lpbps_over_90(self, hub_floor):
        """lpBps=9500 (>9000 cap) should be infeasible."""
        result = hub_floor.functions.quoteFloorCycle(17, 9500, 2000 * 10**18).call()
        feasible = result[0]
        assert feasible is False

    def test_quote_infeasible_insufficient_wpls(self, hub_floor):
        """wplsAvailable=1 wei should be infeasible (not enough for LP)."""
        result = hub_floor.functions.quoteFloorCycle(17, 5000, 1).call()
        feasible = result[0]
        assert feasible is False

    def test_quote_split_math(self, hub_floor):
        """20 GIBS at 3000 bps → 6 LP, 14 sell."""
        result = hub_floor.functions.quoteFloorCycle(
            20,                     # primeCount
            3000,                   # lpBps (30%)
            10000 * 10**18,         # wplsAvailable (plenty)
        ).call()
        feasible, wplsNeeded, wplsFromSell, netWpls, lpGibs, sellGibs = result
        assert feasible is True
        assert lpGibs == 6 * 10**18       # 20e18 * 3000 / 10000 = 6e18
        assert sellGibs == 14 * 10**18    # 20e18 - 6e18 = 14e18


# ═══════════════════════════════════════════════════════════════════════════
#  TestFloorAndHarvest — Integration tests for the full cycle
# ═══════════════════════════════════════════════════════════════════════════

class TestFloorAndHarvest:
    """Integration tests for floorAndHarvest execution."""

    def test_floor_and_harvest_succeeds(self, w3, hub_floor, anvil_url):
        """Full cycle: fund Hub with AFF+WPLS, execute, verify event."""
        hub_cs = Web3.to_checksum_address(HUB)
        joey = Web3.to_checksum_address(JOEY)

        # Fund Hub with AFFECTION (need at least 17 for Purchase)
        fund_hub_with_aff(w3, 50 * 10**18, anvil_url)

        # Fund Hub with WPLS (need enough for LP side)
        fund_hub_with_wpls(w3, 50_000 * 10**18, anvil_url)

        # Verify funding
        aff_bal = balance_of(w3, AFFECTION, hub_cs)
        assert aff_bal >= 17 * 10**18, f"Hub AFF too low: {aff_bal / 1e18}"
        wpls_bal = balance_of(w3, WPLS, hub_cs)
        assert wpls_bal >= 1000 * 10**18, f"Hub WPLS too low: {wpls_bal / 1e18}"

        # Execute floorAndHarvest
        tx = hub_floor.functions.floorAndHarvest(
            17,                     # primeCount
            5000,                   # lpBps (50%)
            50_000 * 10**18,        # wplsMax (high ceiling)
            True,                   # burnLp
            0,                      # minWplsOut (no minimum for test)
        ).build_transaction({
            "from": joey,
            "nonce": w3.eth.get_transaction_count(joey),
            "gas": 5_000_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1, f"floorAndHarvest TX failed: {receipt}"

        # Verify FloorCycleComplete event was emitted
        logs = hub_floor.events.FloorCycleComplete().process_receipt(receipt)
        assert len(logs) == 1, f"Expected 1 FloorCycleComplete event, got {len(logs)}"

        event = logs[0]["args"]
        assert event["primeCount"] == 17
        assert event["lpGibs"] == 8_500000000000000000       # 17e18 * 5000 / 10000 = 8.5e18
        assert event["sellGibs"] == 8_500000000000000000   # 17e18 - 8.5e18 = 8.5e18
        assert event["lpBurned"] is True
        assert event["wplsReceived"] > 0
        assert event["lpMinted"] > 0
        assert event["wplsCommitted"] > 0

        log.info(
            "FloorCycleComplete: primeCount=%d lpGibs=%d sellGibs=%d "
            "wplsCommitted=%d lpMinted=%d wplsReceived=%d",
            event["primeCount"], event["lpGibs"], event["sellGibs"],
            event["wplsCommitted"], event["lpMinted"], event["wplsReceived"],
        )

    def test_floor_and_harvest_reverts_insufficient_aff(self, w3, hub_floor, anvil_url):
        """Hub has WPLS but no AFF — should revert."""
        joey = Web3.to_checksum_address(JOEY)
        hub_cs = Web3.to_checksum_address(HUB)

        # Fund Hub with WPLS only (no AFF)
        fund_hub_with_wpls(w3, 10_000 * 10**18, anvil_url)

        # Verify Hub has no AFF
        aff_bal = balance_of(w3, AFFECTION, hub_cs)
        # If the Hub already has AFF from a previous fixture leak, skip
        if aff_bal >= 17 * 10**18:
            pytest.skip("Hub already has AFF from prior test state")

        # Attempt floorAndHarvest — should revert
        with pytest.raises(Exception):
            tx = hub_floor.functions.floorAndHarvest(
                17, 5000, 10_000 * 10**18, True, 0,
            ).build_transaction({
                "from": joey,
                "nonce": w3.eth.get_transaction_count(joey),
                "gas": 5_000_000,
                "gasPrice": w3.eth.gas_price,
                "chainId": 369,
            })
            tx_hash = w3.eth.send_transaction(tx)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            # If we get here without exception, check receipt status
            assert receipt["status"] == 0, "Expected revert but TX succeeded"

    def test_floor_and_harvest_no_burn(self, w3, hub_floor, anvil_url):
        """burnLp=False — LP tokens should remain in Hub after cycle."""
        joey = Web3.to_checksum_address(JOEY)
        hub_cs = Web3.to_checksum_address(HUB)
        pair_cs = Web3.to_checksum_address(GIBS_WPLS)

        # Fund Hub
        fund_hub_with_aff(w3, 50 * 10**18, anvil_url)
        fund_hub_with_wpls(w3, 50_000 * 10**18, anvil_url)

        # Check Hub LP balance before
        lp_before = balance_of(w3, pair_cs, hub_cs)

        # Execute with burnLp=False
        tx = hub_floor.functions.floorAndHarvest(
            17, 5000, 50_000 * 10**18, False, 0,
        ).build_transaction({
            "from": joey,
            "nonce": w3.eth.get_transaction_count(joey),
            "gas": 5_000_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 369,
        })
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1, "floorAndHarvest (no burn) failed"

        # Verify LP tokens stayed in Hub
        lp_after = balance_of(w3, pair_cs, hub_cs)
        assert lp_after > lp_before, (
            f"LP tokens did not increase in Hub: before={lp_before}, after={lp_after}"
        )

        # Verify event shows lpBurned=False
        logs = hub_floor.events.FloorCycleComplete().process_receipt(receipt)
        assert len(logs) == 1
        assert logs[0]["args"]["lpBurned"] is False

    def test_unauthorized_caller_reverts(self, w3, hub_floor, anvil_url):
        """A random (unauthorized) address should be rejected by onlyAuth."""
        rando = Web3.to_checksum_address("0x" + "de" * 20)
        set_balance(rando, 10**18, anvil_url)  # gas
        impersonate(rando, anvil_url)

        try:
            with pytest.raises(Exception):
                tx = hub_floor.functions.floorAndHarvest(
                    17, 5000, 50_000 * 10**18, True, 0,
                ).build_transaction({
                    "from": rando,
                    "nonce": w3.eth.get_transaction_count(rando),
                    "gas": 5_000_000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": 369,
                })
                tx_hash = w3.eth.send_transaction(tx)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                assert receipt["status"] == 0, "Expected revert but TX succeeded"
        finally:
            stop_impersonate(rando, anvil_url)
