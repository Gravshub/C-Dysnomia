# FloorHarvestModule — Deploy, Wire, Test

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy FloorHarvestModule to JoystickHub, wire selectors + config, verify with Anvil fork tests and live quoteFloorCycle.

**Architecture:** FloorHarvestModule is a JoystickHub delegatecall module. It atomically primes GIBS (Generate x N), purchases via AFF, splits into LP (direct pair.mint) and sell (direct pair.swap) in one TX. Deployed separately, registered via `hub.batchRegisterModule()`, configured via `hub.batchSetConfig()`.

**Tech Stack:** Solidity 0.8.21 (via solcx), web3.py 7.x, Anvil (foundry fork), pytest, PulseChain (369)

**Corrections from prompt:**
- GIBS/WPLS V2 pair: `0x7BCa1c997c475eac9c61417e88bed158ACA757f0` (not `...6593` from prompt comment)
- Gas multiplier: 2.5x (not 1.3x from prompt)
- Compile via `solcx` Python (solc not on PATH)
- Address saved to `config.py` + `data/contracts.json` (no root `contracts.json`)

---

### Task 1: Compile FloorHarvestModule

**Files:**
- Read: `contracts/FloorHarvestModule.sol`
- Create: `scripts/compile_floor_harvest.py`
- Output: `build/FloorHarvestModule/combined.json`

- [ ] **Step 1: Write compile script**

```python
#!/usr/bin/env python3
"""Compile FloorHarvestModule.sol via solcx."""
import json
import os
import solcx

solcx.set_solc_version("0.8.21")

SOL_PATH = os.path.join(os.path.dirname(__file__), "..", "contracts", "FloorHarvestModule.sol")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build", "FloorHarvestModule")

with open(SOL_PATH, "r") as f:
    source = f.read()

compiled = solcx.compile_source(
    source,
    output_values=["abi", "bin"],
    optimize=True,
    optimize_runs=200,
    solc_version="0.8.21",
)

# Extract FloorHarvestModule (key format: "<source>:FloorHarvestModule")
key = None
for k in compiled:
    if k.endswith(":FloorHarvestModule"):
        key = k
        break

if not key:
    raise RuntimeError(f"FloorHarvestModule not found in compiled output. Keys: {list(compiled.keys())}")

abi = compiled[key]["abi"]
bytecode = compiled[key]["bin"]

os.makedirs(OUT_DIR, exist_ok=True)
out_path = os.path.join(OUT_DIR, "combined.json")
with open(out_path, "w") as f:
    json.dump({"abi": abi, "bin": bytecode}, f, indent=2)

print(f"Compiled FloorHarvestModule → {out_path}")
print(f"  ABI: {len(abi)} entries")
print(f"  Bytecode: {len(bytecode)} chars")
```

- [ ] **Step 2: Run compile script**

Run: `cd /opt/joystick/repo && python3 scripts/compile_floor_harvest.py`
Expected: `Compiled FloorHarvestModule → build/FloorHarvestModule/combined.json` with ABI entries and bytecode length printed.

- [ ] **Step 3: Verify output**

Run: `python3 -c "import json; d=json.load(open('build/FloorHarvestModule/combined.json')); print('ABI entries:', len(d['abi'])); print('Bytecode len:', len(d['bin'])); print('Functions:', [e['name'] for e in d['abi'] if e.get('type')=='function'])"`
Expected: 3 functions: `floorAndHarvest`, `quoteFloorCycle`, `floorConfig`, plus the `FloorCycleComplete` event.

---

### Task 2: Write Anvil Fork Tests

**Files:**
- Create: `scripts/Joystick/tests/test_floor_harvest.py`
- Read: `scripts/Joystick/tests/conftest.py` (fixtures: `w3`, `anvil_url`, `fund_joey`, `joystick_ready`, `isolate`)
- Read: `scripts/Joystick/tests/anvil_helpers.py` (helpers: `set_balance`, `impersonate`, `snapshot`, `revert`, `set_erc20_balance`, `balance_of`, etc.)

Tests deploy FloorHarvestModule to Anvil fork, register on the live JoystickHub (forked state), set config, and validate all three functions.

- [ ] **Step 1: Write test file**

```python
"""
test_floor_harvest.py — Anvil fork tests for FloorHarvestModule.

Deploys the module on forked PulseChain, registers on JoystickHub,
sets config, and validates floorConfig/quoteFloorCycle/floorAndHarvest.

Requires Anvil running:
  anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

Run:
  cd /opt/joystick/repo
  python -m pytest scripts/Joystick/tests/test_floor_harvest.py -v --tb=short -x
"""
import pytest
import json
import os
import logging

from web3 import Web3

from .anvil_helpers import (
    set_balance, impersonate, stop_impersonate,
    snapshot, revert, balance_of, set_erc20_balance,
    find_balance_slot,
)

log = logging.getLogger("joystick.test.floor")

# ── Addresses ─────────────────────────────────────────────────────────────
JOEY       = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
HUB        = "0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14"
GIBS_LAU   = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
AFFECTION  = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
WPLS       = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
GIBS_WPLS  = "0x7BCa1c997c475eac9c61417e88bed158ACA757f0"
BURN_369   = "0x0000000000000000000000000000000000000369"

BUILD_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "build", "FloorHarvestModule", "combined.json"
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def floor_compiled():
    """Load compiled FloorHarvestModule ABI + bytecode."""
    if not os.path.exists(BUILD_PATH):
        pytest.skip(f"Compiled artifact not found: {BUILD_PATH}. Run scripts/compile_floor_harvest.py first.")
    with open(BUILD_PATH) as f:
        data = json.load(f)
    assert "abi" in data and "bin" in data, "Invalid compiled output"
    return data


@pytest.fixture(scope="session")
def floor_module(w3, anvil_url, fund_joey, floor_compiled):
    """Deploy FloorHarvestModule to Anvil fork. Returns contract address."""
    abi = floor_compiled["abi"]
    bytecode = floor_compiled["bin"]

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = contract.constructor().transact({"from": JOEY})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.status == 1, "FloorHarvestModule deploy failed"
    log.info("FloorHarvestModule deployed at %s", receipt.contractAddress)
    return receipt.contractAddress


@pytest.fixture(scope="session")
def floor_registered(w3, anvil_url, floor_module, fund_joey):
    """Register FloorHarvestModule selectors on JoystickHub."""
    selectors = [
        w3.keccak(text="floorAndHarvest(uint256,uint256,uint256,bool,uint256)")[:4],
        w3.keccak(text="quoteFloorCycle(uint256,uint256,uint256)")[:4],
        w3.keccak(text="floorConfig()")[:4],
    ]

    HUB_ABI = [{
        "name": "batchRegisterModule",
        "type": "function",
        "inputs": [
            {"name": "selectors", "type": "bytes4[]"},
            {"name": "impl", "type": "address"}
        ],
        "outputs": [],
    }]
    hub = w3.eth.contract(address=w3.to_checksum_address(HUB), abi=HUB_ABI)

    # Hub owner is Joey on mainnet fork
    impersonate(JOEY, anvil_url)
    tx_hash = hub.functions.batchRegisterModule(selectors, floor_module).transact({"from": JOEY})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.status == 1, "batchRegisterModule failed"
    log.info("FloorHarvestModule registered: 3 selectors → %s", floor_module)
    return floor_module


@pytest.fixture(scope="session")
def floor_configured(w3, anvil_url, floor_registered):
    """Set config keys for FloorHarvestModule on JoystickHub."""
    keys = [
        w3.keccak(text="floor.gibsLau"),
        w3.keccak(text="floor.affection"),
        w3.keccak(text="floor.gibsWplsPair"),
        w3.keccak(text="floor.gibsIsToken0"),
        w3.keccak(text="floor.burnAddr"),
    ]
    vals = [
        int(GIBS_LAU, 16),
        int(AFFECTION, 16),
        int(GIBS_WPLS, 16),
        1,  # GIBS is token0 (0x66... < 0xa1...)
        int(BURN_369, 16),
    ]

    CFG_ABI = [{
        "name": "batchSetConfig",
        "type": "function",
        "inputs": [
            {"name": "keys", "type": "bytes32[]"},
            {"name": "vals", "type": "uint256[]"}
        ],
        "outputs": [],
    }]
    hub = w3.eth.contract(address=w3.to_checksum_address(HUB), abi=CFG_ABI)

    impersonate(JOEY, anvil_url)
    tx_hash = hub.functions.batchSetConfig(keys, vals).transact({"from": JOEY})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.status == 1, "batchSetConfig failed"
    log.info("FloorHarvestModule config set: 5 keys")
    return True


@pytest.fixture
def hub_floor(w3, floor_configured, floor_compiled):
    """Return Hub contract with FloorHarvestModule ABI attached."""
    return w3.eth.contract(
        address=w3.to_checksum_address(HUB),
        abi=floor_compiled["abi"],
    )


# ── Tests ─────────────────────────────────────────────────────────────────

class TestFloorConfig:
    """Verify floorConfig() returns correct addresses after setup."""

    def test_floor_config_returns_correct_gibs_lau(self, hub_floor):
        cfg = hub_floor.functions.floorConfig().call()
        assert cfg[0].lower() == GIBS_LAU.lower(), f"gibsLau mismatch: {cfg[0]}"

    def test_floor_config_returns_correct_affection(self, hub_floor):
        cfg = hub_floor.functions.floorConfig().call()
        assert cfg[1].lower() == AFFECTION.lower(), f"affection mismatch: {cfg[1]}"

    def test_floor_config_returns_correct_pair(self, hub_floor):
        cfg = hub_floor.functions.floorConfig().call()
        assert cfg[2].lower() == GIBS_WPLS.lower(), f"pair mismatch: {cfg[2]}"

    def test_floor_config_gibs_is_token0(self, hub_floor):
        cfg = hub_floor.functions.floorConfig().call()
        assert cfg[3] is True, f"gibsIsToken0 should be True, got {cfg[3]}"

    def test_floor_config_burn_addr(self, hub_floor):
        cfg = hub_floor.functions.floorConfig().call()
        assert cfg[4].lower() == BURN_369.lower(), f"burnAddr mismatch: {cfg[4]}"


class TestQuoteFloorCycle:
    """Verify quoteFloorCycle() view function returns sane values."""

    def test_quote_feasible_with_enough_wpls(self, hub_floor):
        """17 GIBS, 50% LP, 2000 WPLS available → should be feasible."""
        result = hub_floor.functions.quoteFloorCycle(
            17, 5000, int(2000e18)
        ).call()
        feasible, wplsNeeded, wplsFromSell, netWpls, lpGibs, sellGibs = result
        assert feasible is True, "Should be feasible with 2000 WPLS"
        assert lpGibs == 8, f"Expected 8 lpGibs (17*5000/10000), got {lpGibs}"
        assert sellGibs == 9, f"Expected 9 sellGibs (17-8), got {sellGibs}"
        assert wplsNeeded > 0, "wplsNeeded should be > 0"
        assert wplsFromSell > 0, "wplsFromSell should be > 0"

    def test_quote_infeasible_zero_prime(self, hub_floor):
        """primeCount=0 → infeasible."""
        result = hub_floor.functions.quoteFloorCycle(0, 5000, int(2000e18)).call()
        assert result[0] is False

    def test_quote_infeasible_zero_lpbps(self, hub_floor):
        """lpBps=0 → infeasible."""
        result = hub_floor.functions.quoteFloorCycle(17, 0, int(2000e18)).call()
        assert result[0] is False

    def test_quote_infeasible_lpbps_over_90(self, hub_floor):
        """lpBps=9500 (>9000) → infeasible."""
        result = hub_floor.functions.quoteFloorCycle(17, 9500, int(2000e18)).call()
        assert result[0] is False

    def test_quote_infeasible_insufficient_wpls(self, hub_floor):
        """wplsAvailable=1 wei → infeasible (not enough for LP)."""
        result = hub_floor.functions.quoteFloorCycle(17, 5000, 1).call()
        assert result[0] is False

    def test_quote_split_math(self, hub_floor):
        """Verify split: 20 GIBS at 3000 bps → 6 LP, 14 sell."""
        result = hub_floor.functions.quoteFloorCycle(20, 3000, int(5000e18)).call()
        _, _, _, _, lpGibs, sellGibs = result
        assert lpGibs == 6, f"Expected 6 lpGibs (20*3000/10000), got {lpGibs}"
        assert sellGibs == 14, f"Expected 14 sellGibs (20-6), got {sellGibs}"


class TestFloorAndHarvest:
    """
    Integration test: execute floorAndHarvest on Anvil fork.

    Requires:
    - Hub has AFFECTION (for Purchase)
    - Hub has WPLS (for LP side)
    - GIBS_LAU has self-balance capacity (Generate works)
    """

    def _fund_hub(self, w3, anvil_url):
        """
        Fund JoystickHub with AFFECTION and WPLS for the test.
        Uses impersonation to transfer from whales.
        """
        hub_cs = w3.to_checksum_address(HUB)

        # Fund Hub with WPLS: set Joey's balance high, wrap PLS, transfer
        set_balance(JOEY, 10_000_000 * 10**18, anvil_url)
        impersonate(JOEY, anvil_url)

        # Wrap 5000 PLS → WPLS
        WPLS_ABI = [{"constant": False, "inputs": [], "name": "deposit",
                      "outputs": [], "payable": True, "type": "function"},
                     {"constant": False, "inputs": [{"name": "dst", "type": "address"},
                      {"name": "wad", "type": "uint256"}], "name": "transfer",
                      "outputs": [{"name": "", "type": "bool"}], "type": "function"}]
        wpls_c = w3.eth.contract(address=w3.to_checksum_address(WPLS), abi=WPLS_ABI)
        tx = wpls_c.functions.deposit().transact({"from": JOEY, "value": 5000 * 10**18})
        w3.eth.wait_for_transaction_receipt(tx)

        # Transfer WPLS to Hub
        tx = wpls_c.functions.transfer(hub_cs, 5000 * 10**18).transact({"from": JOEY})
        w3.eth.wait_for_transaction_receipt(tx)

        # Fund Hub with AFFECTION: impersonate a whale or use the AFFECTION contract
        # AFFECTION self-balance is where minted tokens sit. Transfer from contract.
        aff_cs = w3.to_checksum_address(AFFECTION)
        aff_bal = w3.eth.call({
            "to": aff_cs,
            "data": "0x70a08231" + w3.to_bytes(hexstr=aff_cs).rjust(32, b'\x00').hex()
        })
        aff_self_balance = int(aff_bal.hex(), 16)
        log.info("AFFECTION self-balance: %d", aff_self_balance // 10**18)

        if aff_self_balance >= 100 * 10**18:
            # Impersonate AFFECTION contract to transfer to Hub
            impersonate(aff_cs, anvil_url)
            set_balance(aff_cs, 10**18, anvil_url)  # gas for impersonated TX
            ERC20_ABI = [{"constant": False, "inputs": [
                {"name": "to", "type": "address"},
                {"name": "amount", "type": "uint256"}],
                "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
                "type": "function"}]
            aff_c = w3.eth.contract(address=aff_cs, abi=ERC20_ABI)
            tx = aff_c.functions.transfer(hub_cs, 100 * 10**18).transact({"from": aff_cs})
            w3.eth.wait_for_transaction_receipt(tx)
            stop_impersonate(aff_cs, anvil_url)
        else:
            # Fallback: use set_erc20_balance if we can find the slot
            slot = find_balance_slot(aff_cs, JOEY, anvil_url)
            if slot is not None:
                set_erc20_balance(aff_cs, hub_cs, 100 * 10**18, slot, anvil_url)
            else:
                pytest.skip("Cannot fund Hub with AFFECTION — no whale balance and slot not found")

        # Verify
        hub_aff = balance_of(aff_cs, hub_cs, anvil_url)
        hub_wpls = balance_of(w3.to_checksum_address(WPLS), hub_cs, anvil_url)
        log.info("Hub funded: AFF=%d, WPLS=%d", hub_aff // 10**18, hub_wpls // 10**18)
        assert hub_aff >= 17 * 10**18, f"Hub AFF too low: {hub_aff}"
        assert hub_wpls >= 100 * 10**18, f"Hub WPLS too low: {hub_wpls}"

    def test_floor_and_harvest_succeeds(self, w3, anvil_url, hub_floor, floor_configured):
        """Full atomic cycle: prime 17 GIBS, 50% LP, 50% sell."""
        self._fund_hub(w3, anvil_url)

        # Quote first to get expected wplsNeeded
        hub_cs = w3.to_checksum_address(HUB)
        hub_wpls_before = balance_of(w3.to_checksum_address(WPLS), hub_cs, anvil_url)

        quote = hub_floor.functions.quoteFloorCycle(
            17, 5000, hub_wpls_before
        ).call()
        feasible, wplsNeeded, wplsFromSell, _, lpGibs, sellGibs = quote
        assert feasible, f"Quote says infeasible, wplsNeeded={wplsNeeded/1e18}"

        # Execute: wplsMax = 2x wplsNeeded for slippage, minWplsOut = 0 (test)
        impersonate(JOEY, anvil_url)
        tx_hash = hub_floor.functions.floorAndHarvest(
            17,                          # primeCount
            5000,                        # lpBps (50%)
            wplsNeeded * 2,              # wplsMax (generous)
            True,                        # burnLp
            0,                           # minWplsOut (no slippage floor for test)
        ).transact({"from": JOEY, "gas": 3_000_000})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt.status == 1, f"floorAndHarvest reverted. Gas used: {receipt.gasUsed}"

        # Verify event emitted
        floor_abi = hub_floor.events.FloorCycleComplete()
        logs = floor_abi.process_receipt(receipt)
        assert len(logs) == 1, f"Expected 1 FloorCycleComplete event, got {len(logs)}"
        evt = logs[0]["args"]
        assert evt["primeCount"] == 17
        assert evt["lpGibs"] == 8  # 17 * 5000 / 10000
        assert evt["sellGibs"] == 9  # 17 - 8
        assert evt["wplsReceived"] > 0, "Should have received WPLS from sell"
        assert evt["lpBurned"] is True
        log.info(
            "FloorCycleComplete: prime=%d, lpGibs=%d, sellGibs=%d, "
            "wplsCommitted=%d, lpMinted=%d, wplsReceived=%d",
            evt["primeCount"], evt["lpGibs"], evt["sellGibs"],
            evt["wplsCommitted"], evt["lpMinted"], evt["wplsReceived"],
        )

    def test_floor_and_harvest_reverts_insufficient_aff(self, w3, anvil_url, hub_floor, floor_configured):
        """Should revert if Hub has no AFFECTION."""
        # Don't fund Hub with AFF — just WPLS
        hub_cs = w3.to_checksum_address(HUB)
        set_balance(JOEY, 10_000_000 * 10**18, anvil_url)
        impersonate(JOEY, anvil_url)

        # Wrap + send WPLS to Hub
        WPLS_ABI = [{"constant": False, "inputs": [], "name": "deposit",
                      "outputs": [], "payable": True, "type": "function"},
                     {"constant": False, "inputs": [{"name": "dst", "type": "address"},
                      {"name": "wad", "type": "uint256"}], "name": "transfer",
                      "outputs": [{"name": "", "type": "bool"}], "type": "function"}]
        wpls_c = w3.eth.contract(address=w3.to_checksum_address(WPLS), abi=WPLS_ABI)
        tx = wpls_c.functions.deposit().transact({"from": JOEY, "value": 1000 * 10**18})
        w3.eth.wait_for_transaction_receipt(tx)
        tx = wpls_c.functions.transfer(hub_cs, 1000 * 10**18).transact({"from": JOEY})
        w3.eth.wait_for_transaction_receipt(tx)

        # Should revert
        with pytest.raises(Exception):
            hub_floor.functions.floorAndHarvest(
                17, 5000, int(1000e18), False, 0
            ).transact({"from": JOEY, "gas": 3_000_000})

    def test_floor_and_harvest_no_burn(self, w3, anvil_url, hub_floor, floor_configured):
        """Execute with burnLp=False — LP tokens should stay in Hub."""
        self._fund_hub(w3, anvil_url)

        hub_cs = w3.to_checksum_address(HUB)
        pair_cs = w3.to_checksum_address(GIBS_WPLS)
        lp_before = balance_of(pair_cs, hub_cs, anvil_url)

        quote = hub_floor.functions.quoteFloorCycle(
            17, 5000, balance_of(w3.to_checksum_address(WPLS), hub_cs, anvil_url)
        ).call()
        assert quote[0], "Quote infeasible"

        impersonate(JOEY, anvil_url)
        tx_hash = hub_floor.functions.floorAndHarvest(
            17, 5000, quote[1] * 2, False, 0  # burnLp=False
        ).transact({"from": JOEY, "gas": 3_000_000})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt.status == 1

        lp_after = balance_of(pair_cs, hub_cs, anvil_url)
        assert lp_after > lp_before, f"Hub LP should increase: {lp_before} → {lp_after}"

    def test_unauthorized_caller_reverts(self, w3, anvil_url, hub_floor, floor_configured):
        """Non-auth caller should be rejected."""
        rando = "0x0000000000000000000000000000000000001234"
        set_balance(rando, 10**18, anvil_url)
        impersonate(rando, anvil_url)
        with pytest.raises(Exception):
            hub_floor.functions.floorAndHarvest(
                17, 5000, int(1000e18), False, 0
            ).transact({"from": rando, "gas": 3_000_000})
        stop_impersonate(rando, anvil_url)
```

- [ ] **Step 2: Run tests to verify they fail (no compiled artifact yet — or pass if Task 1 ran first)**

Run: `cd /opt/joystick/repo && python -m pytest scripts/Joystick/tests/test_floor_harvest.py -v --tb=short -x 2>&1 | head -60`

If Task 1 completed and Anvil is running, tests should PASS. If Anvil is not running, tests skip. If compile artifact missing, tests skip.

---

### Task 3: Start Anvil and Run Tests

- [ ] **Step 1: Start Anvil fork in background**

Run: `anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate --port 8545 &`

Wait 5 seconds for Anvil to initialize.

- [ ] **Step 2: Run the full test suite**

Run: `cd /opt/joystick/repo && python -m pytest scripts/Joystick/tests/test_floor_harvest.py -v --tb=short -x`

Expected: All tests pass:
- `TestFloorConfig` — 5 pass (config verification)
- `TestQuoteFloorCycle` — 6 pass (view function edge cases)
- `TestFloorAndHarvest` — 4 pass (full integration: success, no-AFF revert, no-burn, unauth revert)

- [ ] **Step 3: Stop Anvil**

Run: `kill %1` (or `pkill anvil`)

- [ ] **Step 4: Commit test + compile script**

```bash
git add scripts/compile_floor_harvest.py scripts/Joystick/tests/test_floor_harvest.py contracts/FloorHarvestModule.sol
git commit -m "feat: FloorHarvestModule — compile script + Anvil fork tests"
```

---

### Task 4: Deploy FloorHarvestModule to Mainnet

**Files:**
- Create: `scripts/deploy_floor_harvest_module.py`

**CAUTION: This sends real transactions on PulseChain. Costs ~320 PLS total.**

- [ ] **Step 1: Write deploy + wire script**

```python
#!/usr/bin/env python3
"""
Deploy FloorHarvestModule, register on JoystickHub, set config.

Usage:
  # Dry run (simulate only):
  python3 scripts/deploy_floor_harvest_module.py --dry-run

  # Live deploy:
  python3 scripts/deploy_floor_harvest_module.py
"""
import json
import os
import sys
import argparse

from web3 import Web3

# ── Config ────────────────────────────────────────────────────────────────
RPC_SUBMIT = "https://rpc.pulsechain.com"
RPC_READ   = "https://rpc-pulsechain.g4mm4.io"
CHAIN_ID   = 369
GAS_MULT   = 2.5

JOEY       = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
HUB        = Web3.to_checksum_address("0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14")
GIBS_LAU   = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
AFFECTION  = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
GIBS_WPLS  = "0x7BCa1c997c475eac9c61417e88bed158ACA757f0"
BURN_369   = "0x0000000000000000000000000000000000000369"

BUILD_PATH = os.path.join(os.path.dirname(__file__), "..", "build", "FloorHarvestModule", "combined.json")

pk = os.environ.get("DYSNOMIA_PRIVATE_KEY")
if not pk:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set")
    sys.exit(1)


def build_and_send(w3, tx_dict, label, dry_run):
    """Build EIP-1559 TX, estimate gas, sign, send. Abort on estimate failure."""
    gas_est = w3.eth.estimate_gas(tx_dict)
    base_fee = w3.eth.get_block("latest")["baseFeePerGas"]
    max_priority = max(int(base_fee * 0.25), 1_000_000_000)  # at least 1 Gwei
    max_fee = int(base_fee * 2) + max_priority

    tx_dict.update({
        "gas": int(gas_est * GAS_MULT),
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": max_priority,
        "chainId": CHAIN_ID,
        "type": 2,
    })

    cost_pls = gas_est * max_fee / 1e18
    print(f"  {label}: gas={gas_est:,}, maxFee={max_fee/1e9:.1f} Gwei, cost≈{cost_pls:.1f} PLS")

    if dry_run:
        print(f"  [DRY RUN] Skipping send")
        return None

    signed = w3.eth.account.sign_transaction(tx_dict, pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    assert receipt.status == 1, f"{label} FAILED — receipt.status=0"
    print(f"  Confirmed in block {receipt.blockNumber}, gas used: {receipt.gasUsed:,}")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Simulate only, don't send TXs")
    args = parser.parse_args()

    w3 = Web3(Web3.HTTPProvider(RPC_SUBMIT))
    w3_read = Web3(Web3.HTTPProvider(RPC_READ))
    assert w3.is_connected(), "Cannot connect to submit RPC"

    # Load compiled artifact
    with open(BUILD_PATH) as f:
        compiled = json.load(f)
    abi = compiled["abi"]
    bytecode = compiled["bin"]
    print(f"Loaded FloorHarvestModule: {len(abi)} ABI entries, {len(bytecode)} bytecode chars")

    nonce = w3.eth.get_transaction_count(JOEY)

    # ── Step 1: Deploy ────────────────────────────────────────────────────
    print("\n=== Step 1: Deploy FloorHarvestModule ===")
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    deploy_tx = contract.constructor().build_transaction({
        "from": JOEY,
        "nonce": nonce,
    })
    receipt = build_and_send(w3, deploy_tx, "Deploy", args.dry_run)
    if args.dry_run:
        MODULE_ADDR = "0x" + "0" * 40  # placeholder
        print("  [DRY RUN] Module address: <would be deployed>")
    else:
        MODULE_ADDR = receipt.contractAddress
        print(f"  FloorHarvestModule deployed: {MODULE_ADDR}")
        nonce += 1

    # ── Step 2: Register selectors ────────────────────────────────────────
    print("\n=== Step 2: Register selectors on Hub ===")
    selectors = [
        w3.keccak(text="floorAndHarvest(uint256,uint256,uint256,bool,uint256)")[:4],
        w3.keccak(text="quoteFloorCycle(uint256,uint256,uint256)")[:4],
        w3.keccak(text="floorConfig()")[:4],
    ]
    for fn, sel in zip(
        ["floorAndHarvest", "quoteFloorCycle", "floorConfig"],
        selectors,
    ):
        print(f"  {fn} → 0x{sel.hex()}")

    HUB_REG_ABI = [{
        "name": "batchRegisterModule", "type": "function",
        "inputs": [
            {"name": "selectors", "type": "bytes4[]"},
            {"name": "impl", "type": "address"}
        ],
        "outputs": [],
    }]
    hub = w3.eth.contract(address=HUB, abi=HUB_REG_ABI)

    if not args.dry_run:
        # Simulate first
        hub_read = w3_read.eth.contract(address=HUB, abi=HUB_REG_ABI)
        hub_read.functions.batchRegisterModule(selectors, MODULE_ADDR).call({"from": JOEY})
        print("  Simulation: OK")

    reg_tx = hub.functions.batchRegisterModule(selectors, MODULE_ADDR).build_transaction({
        "from": JOEY, "nonce": nonce,
    })
    receipt = build_and_send(w3, reg_tx, "RegisterModule", args.dry_run)
    if receipt:
        nonce += 1

    # ── Step 3: Set config keys ───────────────────────────────────────────
    print("\n=== Step 3: Set config keys ===")
    keys = [
        w3.keccak(text="floor.gibsLau"),
        w3.keccak(text="floor.affection"),
        w3.keccak(text="floor.gibsWplsPair"),
        w3.keccak(text="floor.gibsIsToken0"),
        w3.keccak(text="floor.burnAddr"),
    ]
    vals = [
        int(GIBS_LAU, 16),
        int(AFFECTION, 16),
        int(GIBS_WPLS, 16),
        1,
        int(BURN_369, 16),
    ]
    for name, k, v in zip(
        ["gibsLau", "affection", "gibsWplsPair", "gibsIsToken0", "burnAddr"],
        keys, vals,
    ):
        print(f"  {name}: key=0x{k.hex()[:16]}..., val={hex(v) if v > 255 else v}")

    CFG_ABI = [{
        "name": "batchSetConfig", "type": "function",
        "inputs": [
            {"name": "keys", "type": "bytes32[]"},
            {"name": "vals", "type": "uint256[]"}
        ],
        "outputs": [],
    }]
    hub_cfg = w3.eth.contract(address=HUB, abi=CFG_ABI)
    cfg_tx = hub_cfg.functions.batchSetConfig(keys, vals).build_transaction({
        "from": JOEY, "nonce": nonce,
    })
    receipt = build_and_send(w3, cfg_tx, "SetConfig", args.dry_run)
    if receipt:
        nonce += 1

    # ── Step 4: Verify via floorConfig() ──────────────────────────────────
    if not args.dry_run:
        print("\n=== Step 4: Verify ===")
        FLOOR_CFG_ABI = [{
            "name": "floorConfig", "type": "function", "inputs": [],
            "outputs": [
                {"name": "gibsLau", "type": "address"},
                {"name": "affection", "type": "address"},
                {"name": "gibsWplsPair", "type": "address"},
                {"name": "gibsIsToken0", "type": "bool"},
                {"name": "burnAddr", "type": "address"},
            ],
        }]
        hub_verify = w3_read.eth.contract(address=HUB, abi=FLOOR_CFG_ABI)
        cfg = hub_verify.functions.floorConfig().call()
        assert cfg[0].lower() == GIBS_LAU.lower(), f"gibsLau mismatch: {cfg[0]}"
        assert cfg[2].lower() == GIBS_WPLS.lower(), f"pair mismatch: {cfg[2]}"
        assert cfg[3] is True, f"gibsIsToken0 should be True: {cfg[3]}"
        print("  floorConfig() verified OK")

        # Quote test cycle
        QUOTE_ABI = [{
            "name": "quoteFloorCycle", "type": "function",
            "inputs": [
                {"name": "primeCount", "type": "uint256"},
                {"name": "lpBps", "type": "uint256"},
                {"name": "wplsAvailable", "type": "uint256"},
            ],
            "outputs": [
                {"name": "feasible", "type": "bool"},
                {"name": "wplsNeeded", "type": "uint256"},
                {"name": "wplsFromSell", "type": "uint256"},
                {"name": "netWpls", "type": "uint256"},
                {"name": "lpGibs", "type": "uint256"},
                {"name": "sellGibs", "type": "uint256"},
            ],
        }]
        hub_quote = w3_read.eth.contract(address=HUB, abi=QUOTE_ABI)
        q = hub_quote.functions.quoteFloorCycle(17, 5000, int(2000e18)).call()
        print(f"  quoteFloorCycle(17, 50%, 2000 WPLS):")
        print(f"    feasible:     {q[0]}")
        print(f"    wplsNeeded:   {q[1]/1e18:.4f} WPLS")
        print(f"    wplsFromSell: {q[2]/1e18:.4f} WPLS")
        print(f"    netWpls:      {q[3]/1e18:.4f} WPLS")
        print(f"    lpGibs:       {q[4]}")
        print(f"    sellGibs:     {q[5]}")

    # ── Step 5: Save address ──────────────────────────────────────────────
    if not args.dry_run:
        print(f"\n=== DONE ===")
        print(f"FloorHarvestModule: {MODULE_ADDR}")
        print(f"\nAdd to config.py:")
        print(f'FLOOR_HARVEST_MODULE = Web3.to_checksum_address("{MODULE_ADDR}")')
    else:
        print("\n[DRY RUN] Complete — no transactions sent.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run deploy**

Run: `cd /opt/joystick/repo && set -a && source /opt/joystick/.env.pulse && set +a && python3 scripts/deploy_floor_harvest_module.py --dry-run`

Expected: Gas estimates printed for all 3 TXs, no transactions sent.

- [ ] **Step 3: Live deploy (user confirmation required)**

Run: `cd /opt/joystick/repo && set -a && source /opt/joystick/.env.pulse && set +a && python3 scripts/deploy_floor_harvest_module.py`

Expected: 3 TXs confirmed, floorConfig() verified, quoteFloorCycle() returns feasible=True.

- [ ] **Step 4: Save MODULE_ADDR to config.py**

Add after `HARVEST_MODULE_V3` line in `scripts/Joystick/core/config.py`:
```python
# FloorHarvestModule — atomic prime→LP→sell, no router
FLOOR_HARVEST_MODULE = Web3.to_checksum_address("<DEPLOYED_ADDRESS>")
```

- [ ] **Step 5: Commit deploy script + config update**

```bash
git add scripts/deploy_floor_harvest_module.py scripts/Joystick/core/config.py
git commit -m "feat: deploy FloorHarvestModule to JoystickHub — atomic LP+sell"
```
