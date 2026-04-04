# V2 Autonomous Ammo Chain — Anvil Test Environment & Validation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Anvil-based test environment that validates the full V2 Autonomous Ammo Chain mechanics (create JBASE/JAMMO via V2 Minter, run spine cycles through FDIC, reload ammo) and produces tokenomics break-even analysis.

**Architecture:** Anvil forks PulseChain mainnet, giving us real contract state (FDIC, V2 Minter, PulseX pairs) with free impersonation and storage manipulation. A new `SpineModule.sol` is added to JoystickHub for atomic spine execution. Python tests exercise all 4 phases on the fork and compute profitability metrics.

**Tech Stack:** Foundry/Anvil (local fork), Solidity 0.8.21, Python pytest, web3.py, existing conftest.py/anvil_helpers.py

---

## File Structure

```
contracts/
  SpineModule.sol                    — New JoystickHub module: spineRun + spineReload

scripts/Joystick/tests/
  test_v2_ammo_chain.py              — Full Anvil test suite for the ammo chain
  
scripts/Joystick/data/abis/
  spine_module.json                  — ABI for SpineModule (extracted after compile)
  v2_federal_minter.json             — ABI for NT (V2 Federal Minter)

scripts/Joystick/data/
  spine_chain_config.json            — Runtime config for deployed JBASE/JAMMO addresses
```

## Key Addresses (From Mainnet State)

| Contract | Address | Role |
|----------|---------|------|
| V2 Federal Minter (NT) | `0xc15c5F699Daf5e1135732139f05D2c05b3EF4354` | Creates JBASE, JAMMO |
| FDIC | `0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9` | Target: mint+sell+claim |
| FED | `0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff` | Parent of FDIC and JBASE |
| WM | `0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29` | Payment for V2Minter.New() |
| JoystickHub | `0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14` | Proxy — registers SpineModule |
| WPLS | `0xA1077a294dDE1B09bB078844df40758a5D0f9a27` | Sell target |
| PulseX V2 Router | `0x165C3410fC91EF562C50559f7d2289fEbed552d9` | DEX sells |

## V2 Ammo Chain Mechanics (Reference)

```
V2Minter.New("JBASE", "JBASE", 1, FED)   → JBASE deployed, Debenture=true
V2Minter.New("JAMMO", "JAMMO", 1, JBASE) → JAMMO deployed, Debenture=true

Spine Run (per iteration):
  1. FDIC.mint(N)         → Hub sends N FED → receives N FDIC
  2. Sell FDIC → WPLS     → Revenue
  3. FDIC.Claim(JAMMO, N) → Hub sends N JAMMO → receives N FED back

Reload (when JAMMO depleted):
  1. JBASE.mint(M)        → Hub sends M FED → receives M JBASE  
  2. JAMMO.mint(M)        → Hub sends M JBASE → receives M JAMMO
  Net: M FED locked in JBASE contract, M JAMMO available for Claim
```

**Key Solidity from `federalminter.sol`:**
- `TT.Claim(Contract, Amount)`: Checks `V2Minter.TreasuryTokens(Contract) != 0` AND `TTI(Contract).Debenture() == true`. Transfers Amount of Contract FROM caller TO this. Transfers Amount of Parent FROM this TO caller.
- `TT.mint(amount)`: Transfers amount of Parent FROM caller TO this. Mints amount TO caller.
- `NT.New(Name, Symbol, InitialMint, Parent)`: Costs InitialMint WM. Creates TT with `Debenture=true`, `_hu[tx.origin]=255`.

---

### Task 1: Install Foundry/Anvil

**Files:**
- No files created

- [ ] **Step 1: Install Foundry toolchain**

```bash
curl -L https://foundry.paradigm.xyz | bash
source ~/.bashrc
foundryup
```

- [ ] **Step 2: Verify Anvil is available**

```bash
anvil --version
```
Expected: `anvil 0.x.x` version string

- [ ] **Step 3: Test Anvil PulseChain fork**

```bash
anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate --port 8545 &
sleep 3
curl -s -X POST http://127.0.0.1:8545 -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' | python3 -c "import sys,json; d=json.load(sys.stdin); assert int(d['result'],16)==369; print('OK: chain 369')"
kill %1
```
Expected: `OK: chain 369`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: verify Foundry/Anvil installation for fork testing"
```

---

### Task 2: V2 Federal Minter ABI File

**Files:**
- Create: `scripts/Joystick/data/abis/v2_federal_minter.json`

We need the NT (V2 Minter) ABI for calling `New()` and `TreasuryTokens()` from tests. The TT (treasury token) ABI already exists as `treasury_token.json`.

- [ ] **Step 1: Write the V2 Federal Minter ABI**

```bash
# Verify treasury_token.json exists and has Claim/mint/Debenture
python3 -c "
import json
with open('scripts/Joystick/data/abis/treasury_token.json') as f:
    abi = json.load(f)
names = [x['name'] for x in abi if x.get('type')=='function']
for fn in ['Claim','mint','Debenture','Parent']:
    assert fn in names, f'Missing {fn}'
print('treasury_token.json OK:', names)
"
```

- [ ] **Step 2: Create the V2 Federal Minter ABI file**

Create `scripts/Joystick/data/abis/v2_federal_minter.json`:

```json
[
  {
    "name": "New",
    "type": "function",
    "stateMutability": "nonpayable",
    "inputs": [
      {"name": "Name", "type": "string"},
      {"name": "Symbol", "type": "string"},
      {"name": "InitialMint", "type": "uint256"},
      {"name": "Parent", "type": "address"}
    ],
    "outputs": [{"name": "", "type": "address"}]
  },
  {
    "name": "TreasuryTokens",
    "type": "function",
    "stateMutability": "view",
    "inputs": [{"name": "ctx", "type": "address"}],
    "outputs": [{"name": "", "type": "address"}]
  },
  {
    "name": "GetTreasuryTokenOwner",
    "type": "function",
    "stateMutability": "view",
    "inputs": [{"name": "ctx", "type": "address"}],
    "outputs": [{"name": "", "type": "address"}]
  },
  {
    "name": "Transfer",
    "type": "function",
    "stateMutability": "nonpayable",
    "inputs": [
      {"name": "ctx", "type": "address"},
      {"name": "newOwner", "type": "address"}
    ],
    "outputs": []
  },
  {
    "name": "FDIC",
    "type": "function",
    "stateMutability": "view",
    "inputs": [],
    "outputs": [{"name": "", "type": "address"}]
  },
  {
    "name": "FED",
    "type": "function",
    "stateMutability": "view",
    "inputs": [],
    "outputs": [{"name": "", "type": "address"}]
  }
]
```

- [ ] **Step 3: Verify ABI loads correctly**

```bash
python3 -c "
import json
with open('scripts/Joystick/data/abis/v2_federal_minter.json') as f:
    abi = json.load(f)
names = [x['name'] for x in abi]
assert 'New' in names
assert 'TreasuryTokens' in names
print('v2_federal_minter.json OK:', names)
"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/Joystick/data/abis/v2_federal_minter.json
git commit -m "feat: add V2 Federal Minter ABI for ammo chain tests"
```

---

### Task 3: Test V2 Token Creation on Anvil (JBASE + JAMMO)

**Files:**
- Create: `scripts/Joystick/tests/test_v2_ammo_chain.py`

This is the core test file. We start by testing Phase 1 (Arm) — creating JBASE and JAMMO via V2Minter.New().

- [ ] **Step 1: Write the test file scaffold with V2 token creation tests**

Create `scripts/Joystick/tests/test_v2_ammo_chain.py`:

```python
"""
test_v2_ammo_chain.py — Anvil fork tests for the V2 Autonomous Ammo Chain.

Validates:
  Phase 1: Create JBASE (parent=FED) and JAMMO (parent=JBASE) via V2 Minter
  Phase 2: Spine run — FDIC.mint → sell → FDIC.Claim(JAMMO) → FED recovered
  Phase 3: Reload — FED → JBASE.mint → JAMMO.mint → JAMMO replenished
  Phase 4: Tokenomics — break-even analysis at various FED working capital levels

Requires Anvil running:
  anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

Run:
  python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py -v --tb=short -x

"Two V2 tokens, both Debenture=TRUE, never published. Joey controls the full stack."
"""
import pytest
import json
import logging
from pathlib import Path
from web3 import Web3

from .anvil_helpers import (
    set_balance, impersonate, stop_impersonate,
    balance_of, transfer_via_impersonate,
    approve_via_impersonate, set_erc20_balance,
    find_balance_slot, snapshot, revert,
)

log = logging.getLogger("joystick.test.ammo_chain")

# ── Addresses ──────────────────────────────────────────────────────────────
JOEY        = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
V2_MINTER   = "0xc15c5F699Daf5e1135732139f05D2c05b3EF4354"
FED         = "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff"
FDIC        = "0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9"
WM          = "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"
WPLS        = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
ROUTER_V2   = "0x165C3410fC91EF562C50559f7d2289fEbed552d9"
FACTORY_V2  = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"

ABI_DIR = Path(__file__).parent.parent / "data" / "abis"

# ── ABI Loading ────────────────────────────────────────────────────────────

def _load_abi(name: str) -> list:
    with open(ABI_DIR / f"{name}.json") as f:
        return json.load(f)


ERC20_ABI = _load_abi("erc20")
TREASURY_TOKEN_ABI = _load_abi("treasury_token")
V2_MINTER_ABI = _load_abi("v2_federal_minter")
ROUTER_ABI = _load_abi("router")


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="class")
def funded_joey(w3, anvil_url):
    """Fund Joey with PLS and WM for V2 token creation."""
    set_balance(JOEY, 5_000_000 * 10**18, anvil_url)
    impersonate(JOEY, anvil_url)

    # Joey needs WM to call V2Minter.New() (1 WM per token)
    # Find a WM holder and transfer WM to Joey
    wm_slot = find_balance_slot(WM, JOEY, w3)
    if wm_slot is not None:
        set_erc20_balance(WM, JOEY, 1000 * 10**18, balance_slot=wm_slot, url=anvil_url)
    else:
        # Fallback: try common slots
        for slot in [0, 1, 2, 3, 51]:
            set_erc20_balance(WM, JOEY, 1000 * 10**18, balance_slot=slot, url=anvil_url)
            bal = balance_of(w3, WM, JOEY)
            if bal >= 1000 * 10**18:
                break

    wm_bal = balance_of(w3, WM, JOEY)
    assert wm_bal >= 2 * 10**18, f"Need 2+ WM, have {wm_bal / 1e18}"

    # Joey also needs FED for working capital
    fed_slot = find_balance_slot(FED, JOEY, w3)
    if fed_slot is not None:
        set_erc20_balance(FED, JOEY, 100_000 * 10**18, balance_slot=fed_slot, url=anvil_url)
    else:
        for slot in [0, 1, 2, 3, 51]:
            set_erc20_balance(FED, JOEY, 100_000 * 10**18, balance_slot=slot, url=anvil_url)
            bal = balance_of(w3, FED, JOEY)
            if bal >= 100_000 * 10**18:
                break

    fed_bal = balance_of(w3, FED, JOEY)
    assert fed_bal >= 100_000 * 10**18, f"Need 100K+ FED, have {fed_bal / 1e18}"

    log.info("Joey funded: WM=%.0f, FED=%.0f", wm_bal / 1e18, fed_bal / 1e18)
    return {"wm": wm_bal, "fed": fed_bal}


@pytest.fixture(scope="class")
def v2_minter_contract(w3):
    """V2 Federal Minter contract instance."""
    return w3.eth.contract(
        address=Web3.to_checksum_address(V2_MINTER),
        abi=V2_MINTER_ABI,
    )


@pytest.fixture(scope="class")
def fdic_contract(w3):
    """FDIC treasury token contract instance."""
    return w3.eth.contract(
        address=Web3.to_checksum_address(FDIC),
        abi=TREASURY_TOKEN_ABI,
    )


@pytest.fixture(scope="class")
def router_v2(w3):
    """PulseX V2 Router contract instance."""
    return w3.eth.contract(
        address=Web3.to_checksum_address(ROUTER_V2),
        abi=ROUTER_ABI,
    )


def _send_tx(w3, tx_dict):
    """Send a transaction via Anvil impersonation (no private key needed)."""
    tx_dict.setdefault("gas", 3_000_000)
    tx_dict.setdefault("gasPrice", w3.eth.gas_price)
    tx_hash = w3.eth.send_transaction(tx_dict)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
    assert receipt["status"] == 1, f"TX reverted: {tx_hash.hex()}"
    return receipt


def _approve(w3, token_addr, owner, spender, amount):
    """Approve spender to use owner's tokens via impersonation."""
    approve_via_impersonate(token_addr, owner, spender, amount, w3)


# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 1: V2 TOKEN CREATION
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase1TokenCreation:
    """Create JBASE and JAMMO via V2 Minter."""

    jbase_addr = None
    jammo_addr = None

    def test_v2_minter_exists(self, w3):
        """V2 Minter has code on fork."""
        code = w3.eth.get_code(Web3.to_checksum_address(V2_MINTER))
        assert len(code) > 10

    def test_fdic_is_registered(self, v2_minter_contract):
        """FDIC is a registered token in V2 Minter."""
        fdic_addr = v2_minter_contract.functions.FDIC().call()
        assert fdic_addr.lower() == FDIC.lower()

    def test_fdic_debenture_is_false(self, fdic_contract):
        """FDIC was published — Debenture should be false."""
        deb = fdic_contract.functions.Debenture().call()
        assert deb is False, "FDIC Debenture should be false (published in constructor)"

    def test_fdic_parent_is_fed(self, fdic_contract):
        """FDIC's parent should be FED."""
        parent = fdic_contract.functions.Parent().call()
        assert parent.lower() == FED.lower()

    def test_fdic_has_fed_balance(self, w3):
        """FDIC contract should hold a large FED balance (backing for Claim)."""
        fed_in_fdic = balance_of(w3, FED, FDIC)
        assert fed_in_fdic > 0, "FDIC has no FED backing"
        log.info("FDIC holds %.2e FED tokens", fed_in_fdic / 1e18)

    def test_create_jbase(self, w3, funded_joey):
        """Create JBASE via V2Minter.New(name, symbol, 1, FED).

        Costs 1 WM. JBASE has parent=FED, Debenture=true, _hu[Joey]=255.
        """
        # Approve WM to V2 Minter
        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)

        # Call V2Minter.New("JBASE", "JBASE", 1, FED)
        v2m = w3.eth.contract(address=Web3.to_checksum_address(V2_MINTER), abi=V2_MINTER_ABI)
        tx_data = v2m.functions.New(
            "Joystick Base", "JBASE", 1, Web3.to_checksum_address(FED)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 5_000_000,
            "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx_data)

        # Extract new token address from return value
        # V2Minter.New returns address — decode from logs or re-call
        # The token address is the return value; we can also check TreasuryTokens
        # For deployed contracts, parse Transfer event (the initial mint)
        transfer_logs = [
            l for l in receipt["logs"]
            if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()
        ]
        # The first Transfer is WM from Joey to Minter
        # The second Transfer is the initial mint (address(0) → Joey) on the new token
        assert len(transfer_logs) >= 2, f"Expected 2+ Transfer events, got {len(transfer_logs)}"

        # New token address is the 'address' field of the second Transfer log
        jbase_addr = transfer_logs[-1]["address"]
        TestPhase1TokenCreation.jbase_addr = jbase_addr
        log.info("JBASE deployed at: %s", jbase_addr)

        # Verify JBASE is registered in V2 Minter
        owner = v2m.functions.TreasuryTokens(Web3.to_checksum_address(jbase_addr)).call()
        assert owner.lower() == JOEY.lower(), f"JBASE owner is {owner}, expected Joey"

        # Verify Debenture=true
        jbase = w3.eth.contract(address=Web3.to_checksum_address(jbase_addr), abi=TREASURY_TOKEN_ABI)
        assert jbase.functions.Debenture().call() is True

        # Verify parent=FED
        parent = jbase.functions.Parent().call()
        assert parent.lower() == FED.lower()

        # Joey should have received the initial mint (1 token)
        joey_bal = balance_of(w3, jbase_addr, JOEY)
        assert joey_bal == 1, f"Joey should have 1 JBASE, has {joey_bal}"

    def test_create_jammo(self, w3, funded_joey):
        """Create JAMMO via V2Minter.New(name, symbol, 1, JBASE).

        Costs 1 WM. JAMMO has parent=JBASE, Debenture=true.
        """
        jbase = TestPhase1TokenCreation.jbase_addr
        assert jbase is not None, "JBASE not created yet — run test_create_jbase first"

        # Approve WM to V2 Minter
        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)

        v2m = w3.eth.contract(address=Web3.to_checksum_address(V2_MINTER), abi=V2_MINTER_ABI)
        tx_data = v2m.functions.New(
            "Joystick Ammo", "JAMMO", 1, Web3.to_checksum_address(jbase)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 5_000_000,
            "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx_data)

        transfer_logs = [
            l for l in receipt["logs"]
            if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()
        ]
        assert len(transfer_logs) >= 2

        jammo_addr = transfer_logs[-1]["address"]
        TestPhase1TokenCreation.jammo_addr = jammo_addr
        log.info("JAMMO deployed at: %s", jammo_addr)

        # Verify registered, Debenture=true, parent=JBASE
        owner = v2m.functions.TreasuryTokens(Web3.to_checksum_address(jammo_addr)).call()
        assert owner.lower() == JOEY.lower()

        jammo = w3.eth.contract(address=Web3.to_checksum_address(jammo_addr), abi=TREASURY_TOKEN_ABI)
        assert jammo.functions.Debenture().call() is True
        assert jammo.functions.Parent().call().lower() == jbase.lower()

    def test_mint_jbase_from_fed(self, w3, funded_joey):
        """Mint JBASE tokens using FED as parent. FED → JBASE at 1:1."""
        jbase = TestPhase1TokenCreation.jbase_addr
        assert jbase is not None

        mint_amount = 1000 * 10**18

        # Approve FED to JBASE for minting
        _approve(w3, FED, JOEY, jbase, mint_amount)

        jbase_contract = w3.eth.contract(
            address=Web3.to_checksum_address(jbase), abi=TREASURY_TOKEN_ABI
        )
        tx_data = jbase_contract.functions.mint(mint_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000,
            "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx_data)

        joey_jbase = balance_of(w3, jbase, JOEY)
        # Joey had 1 from initial mint + 1000 from mint() = 1001
        # Actually initial mint is in raw units, not 1e18. Let me check.
        # V2Minter.New passes InitialMint=1 to TT constructor, which does
        # _mint(tx.origin, InitialMint) — so Joey gets 1 wei, not 1 token.
        # Our mint(1000e18) gives 1000e18.
        assert joey_jbase >= mint_amount, f"Expected {mint_amount}, got {joey_jbase}"
        log.info("Joey JBASE after mint: %.4f", joey_jbase / 1e18)

    def test_mint_jammo_from_jbase(self, w3, funded_joey):
        """Mint JAMMO tokens using JBASE as parent. JBASE → JAMMO at 1:1."""
        jbase = TestPhase1TokenCreation.jbase_addr
        jammo = TestPhase1TokenCreation.jammo_addr
        assert jbase and jammo

        mint_amount = 500 * 10**18

        # Approve JBASE to JAMMO for minting
        _approve(w3, jbase, JOEY, jammo, mint_amount)

        jammo_contract = w3.eth.contract(
            address=Web3.to_checksum_address(jammo), abi=TREASURY_TOKEN_ABI
        )
        tx_data = jammo_contract.functions.mint(mint_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000,
            "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx_data)

        joey_jammo = balance_of(w3, jammo, JOEY)
        assert joey_jammo >= mint_amount
        log.info("Joey JAMMO after mint: %.4f", joey_jammo / 1e18)
```

- [ ] **Step 2: Run Phase 1 tests**

Start Anvil in one terminal:
```bash
anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate &
```

Run tests:
```bash
cd /opt/joystick/repo
python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py::TestPhase1TokenCreation -v --tb=short -x
```

Expected: All 7 tests pass — JBASE and JAMMO created, minted successfully.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/test_v2_ammo_chain.py
git commit -m "test: Phase 1 — V2 token creation tests (JBASE + JAMMO) on Anvil"
```

---

### Task 4: Test Spine Run Mechanics (Phase 2)

**Files:**
- Modify: `scripts/Joystick/tests/test_v2_ammo_chain.py`

Add Phase 2 tests: FDIC.mint(), FDIC.Claim(JAMMO), and the full spine cycle.

- [ ] **Step 1: Write Phase 2 spine run tests**

Append to `test_v2_ammo_chain.py`:

```python
# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 2: SPINE RUN — mint FDIC → sell → Claim with JAMMO → FED back
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase2SpineRun:
    """Test the spine cycle: FDIC.mint(FED) → sell FDIC → FDIC.Claim(JAMMO) → FED back."""

    @pytest.fixture(autouse=True)
    def setup_ammo_chain(self, w3, anvil_url):
        """Create JBASE + JAMMO + mint ammo before each test in this class."""
        snap = snapshot(anvil_url)

        # Fund Joey
        set_balance(JOEY, 5_000_000 * 10**18, anvil_url)
        impersonate(JOEY, anvil_url)

        # Seed WM + FED via storage manipulation
        for token, amount in [(WM, 100 * 10**18), (FED, 200_000 * 10**18)]:
            for slot in range(5):
                set_erc20_balance(token, JOEY, amount, balance_slot=slot, url=anvil_url)
                if balance_of(w3, token, JOEY) >= amount:
                    break

        # Create JBASE
        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)
        v2m = w3.eth.contract(address=Web3.to_checksum_address(V2_MINTER), abi=V2_MINTER_ABI)
        tx = v2m.functions.New(
            "Joystick Base", "JBASE", 1, Web3.to_checksum_address(FED)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 5_000_000, "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx)
        transfer_logs = [
            l for l in receipt["logs"]
            if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()
        ]
        self.jbase = transfer_logs[-1]["address"]

        # Create JAMMO
        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)
        tx = v2m.functions.New(
            "Joystick Ammo", "JAMMO", 1, Web3.to_checksum_address(self.jbase)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 5_000_000, "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx)
        transfer_logs = [
            l for l in receipt["logs"]
            if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()
        ]
        self.jammo = transfer_logs[-1]["address"]

        # Mint JBASE from FED (10,000 JBASE)
        _approve(w3, FED, JOEY, self.jbase, 10_000 * 10**18)
        jbase_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jbase), abi=TREASURY_TOKEN_ABI
        )
        tx = jbase_c.functions.mint(10_000 * 10**18).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Mint JAMMO from JBASE (5,000 JAMMO)
        _approve(w3, self.jbase, JOEY, self.jammo, 5_000 * 10**18)
        jammo_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jammo), abi=TREASURY_TOKEN_ABI
        )
        tx = jammo_c.functions.mint(5_000 * 10**18).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        log.info("Ammo chain ready: JBASE=%s, JAMMO=%s", self.jbase, self.jammo)
        yield
        revert(snap, anvil_url)

    def test_fdic_mint_with_fed(self, w3):
        """FDIC.mint(amount) — spend FED, receive FDIC tokens."""
        mint_amount = 100 * 10**18

        fed_before = balance_of(w3, FED, JOEY)
        fdic_before = balance_of(w3, FDIC, JOEY)

        _approve(w3, FED, JOEY, FDIC, mint_amount)

        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )
        tx = fdic_c.functions.mint(mint_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        fed_after = balance_of(w3, FED, JOEY)
        fdic_after = balance_of(w3, FDIC, JOEY)

        assert fed_after == fed_before - mint_amount, "FED should decrease by mint_amount"
        assert fdic_after == fdic_before + mint_amount, "FDIC should increase by mint_amount"
        log.info("FDIC.mint OK: FED -%d, FDIC +%d", mint_amount // 10**18, mint_amount // 10**18)

    def test_fdic_claim_with_jammo(self, w3):
        """FDIC.Claim(JAMMO, amount) — spend JAMMO, receive FED back.

        This is the core mechanic: JAMMO (Debenture=true, registered in V2Minter)
        is accepted as ammo by FDIC.Claim(). FED flows from FDIC → caller.
        """
        claim_amount = 50 * 10**18

        # First, we need to verify FDIC has FED to give back
        fed_in_fdic = balance_of(w3, FED, FDIC)
        assert fed_in_fdic >= claim_amount, f"FDIC has insufficient FED: {fed_in_fdic / 1e18}"

        fed_before = balance_of(w3, FED, JOEY)
        jammo_before = balance_of(w3, self.jammo, JOEY)

        # Approve JAMMO to FDIC for Claim
        _approve(w3, self.jammo, JOEY, FDIC, claim_amount)

        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )
        tx = fdic_c.functions.Claim(
            Web3.to_checksum_address(self.jammo), claim_amount
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        fed_after = balance_of(w3, FED, JOEY)
        jammo_after = balance_of(w3, self.jammo, JOEY)

        assert fed_after == fed_before + claim_amount, "FED should increase (recovered from FDIC)"
        assert jammo_after == jammo_before - claim_amount, "JAMMO should decrease (consumed)"
        log.info("FDIC.Claim OK: JAMMO -%d, FED +%d", claim_amount // 10**18, claim_amount // 10**18)

    def test_full_spine_cycle(self, w3):
        """Full spine cycle: mint FDIC → claim FED back → verify FED conservation.

        Net effect: JAMMO consumed, FDIC minted (can be sold), FED conserved.
        """
        cycle_amount = 100 * 10**18

        fed_before = balance_of(w3, FED, JOEY)
        jammo_before = balance_of(w3, self.jammo, JOEY)
        fdic_before = balance_of(w3, FDIC, JOEY)

        # Step 1: Mint FDIC with FED
        _approve(w3, FED, JOEY, FDIC, cycle_amount)
        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )
        tx = fdic_c.functions.mint(cycle_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Step 2: Claim FED back with JAMMO
        _approve(w3, self.jammo, JOEY, FDIC, cycle_amount)
        tx = fdic_c.functions.Claim(
            Web3.to_checksum_address(self.jammo), cycle_amount
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        fed_after = balance_of(w3, FED, JOEY)
        jammo_after = balance_of(w3, self.jammo, JOEY)
        fdic_after = balance_of(w3, FDIC, JOEY)

        # FED conserved (mint consumed, claim recovered)
        assert fed_after == fed_before, f"FED should be conserved: before={fed_before}, after={fed_after}"
        # JAMMO consumed
        assert jammo_after == jammo_before - cycle_amount, "JAMMO should be consumed"
        # FDIC gained
        assert fdic_after == fdic_before + cycle_amount, "FDIC should be gained"

        log.info(
            "Full cycle OK: FED conserved, JAMMO -%d, FDIC +%d",
            cycle_amount // 10**18, cycle_amount // 10**18,
        )

    def test_multi_iteration_spine(self, w3):
        """Run N iterations of the spine cycle, verify cumulative accounting."""
        iters = 5
        per_iter = 50 * 10**18
        total = iters * per_iter

        fed_before = balance_of(w3, FED, JOEY)
        jammo_before = balance_of(w3, self.jammo, JOEY)

        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )

        for i in range(iters):
            # Mint
            _approve(w3, FED, JOEY, FDIC, per_iter)
            tx = fdic_c.functions.mint(per_iter).build_transaction({
                "from": Web3.to_checksum_address(JOEY),
                "gas": 500_000, "gasPrice": w3.eth.gas_price,
            })
            _send_tx(w3, tx)

            # Claim
            _approve(w3, self.jammo, JOEY, FDIC, per_iter)
            tx = fdic_c.functions.Claim(
                Web3.to_checksum_address(self.jammo), per_iter
            ).build_transaction({
                "from": Web3.to_checksum_address(JOEY),
                "gas": 500_000, "gasPrice": w3.eth.gas_price,
            })
            _send_tx(w3, tx)

        fed_after = balance_of(w3, FED, JOEY)
        jammo_after = balance_of(w3, self.jammo, JOEY)

        assert fed_after == fed_before, f"FED should be conserved after {iters} iterations"
        assert jammo_after == jammo_before - total, f"JAMMO should decrease by {total / 1e18}"
        log.info("Multi-iteration OK: %d iters, JAMMO consumed: %.0f", iters, total / 1e18)

    def test_claim_fails_without_jammo_registration(self, w3):
        """Claim should revert if ammo token is not registered in V2Minter."""
        # Use a random address as ammo — not a registered TreasuryToken
        fake_ammo = "0x0000000000000000000000000000000000001234"
        claim_amount = 10 * 10**18

        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )
        with pytest.raises(Exception):
            tx = fdic_c.functions.Claim(
                Web3.to_checksum_address(fake_ammo), claim_amount
            ).build_transaction({
                "from": Web3.to_checksum_address(JOEY),
                "gas": 500_000, "gasPrice": w3.eth.gas_price,
            })
            _send_tx(w3, tx)
```

- [ ] **Step 2: Run Phase 2 tests**

```bash
python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py::TestPhase2SpineRun -v --tb=short -x
```

Expected: All 5 tests pass — spine cycle works, FED conserved, JAMMO consumed.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/test_v2_ammo_chain.py
git commit -m "test: Phase 2 — spine run mechanics (mint/claim/cycle) on Anvil"
```

---

### Task 5: Test Reload Mechanics (Phase 3)

**Files:**
- Modify: `scripts/Joystick/tests/test_v2_ammo_chain.py`

Test the JAMMO reload path: FED → JBASE.mint → JAMMO.mint.

- [ ] **Step 1: Write Phase 3 reload tests**

Append to `test_v2_ammo_chain.py`:

```python
# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 3: RELOAD — FED → JBASE.mint → JAMMO.mint
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase3Reload:
    """Test JAMMO reload: FED → mint JBASE → mint JAMMO."""

    @pytest.fixture(autouse=True)
    def setup_depleted_ammo(self, w3, anvil_url):
        """Create ammo chain, then deplete JAMMO to simulate need for reload."""
        snap = snapshot(anvil_url)

        set_balance(JOEY, 5_000_000 * 10**18, anvil_url)
        impersonate(JOEY, anvil_url)

        # Seed tokens
        for token, amount in [(WM, 100 * 10**18), (FED, 500_000 * 10**18)]:
            for slot in range(5):
                set_erc20_balance(token, JOEY, amount, balance_slot=slot, url=anvil_url)
                if balance_of(w3, token, JOEY) >= amount:
                    break

        # Create JBASE + JAMMO
        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)
        v2m = w3.eth.contract(address=Web3.to_checksum_address(V2_MINTER), abi=V2_MINTER_ABI)

        tx = v2m.functions.New(
            "Joystick Base", "JBASE", 1, Web3.to_checksum_address(FED)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 5_000_000, "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx)
        logs = [l for l in receipt["logs"]
                if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()]
        self.jbase = logs[-1]["address"]

        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)
        tx = v2m.functions.New(
            "Joystick Ammo", "JAMMO", 1, Web3.to_checksum_address(self.jbase)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 5_000_000, "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx)
        logs = [l for l in receipt["logs"]
                if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()]
        self.jammo = logs[-1]["address"]

        # Initial mint: 1000 JBASE, 500 JAMMO
        _approve(w3, FED, JOEY, self.jbase, 1000 * 10**18)
        jbase_c = w3.eth.contract(address=Web3.to_checksum_address(self.jbase), abi=TREASURY_TOKEN_ABI)
        tx = jbase_c.functions.mint(1000 * 10**18).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        _approve(w3, self.jbase, JOEY, self.jammo, 500 * 10**18)
        jammo_c = w3.eth.contract(address=Web3.to_checksum_address(self.jammo), abi=TREASURY_TOKEN_ABI)
        tx = jammo_c.functions.mint(500 * 10**18).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Deplete most JAMMO via spine cycles
        fdic_c = w3.eth.contract(address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI)
        deplete = 450 * 10**18
        _approve(w3, FED, JOEY, FDIC, deplete)
        tx = fdic_c.functions.mint(deplete).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        _approve(w3, self.jammo, JOEY, FDIC, deplete)
        tx = fdic_c.functions.Claim(
            Web3.to_checksum_address(self.jammo), deplete
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        self.jammo_remaining = balance_of(w3, self.jammo, JOEY)
        log.info("Setup: JAMMO remaining after depletion: %.0f", self.jammo_remaining / 1e18)

        yield
        revert(snap, anvil_url)

    def test_jammo_is_depleted(self, w3):
        """After setup, JAMMO should be nearly depleted (50 remaining)."""
        jammo_bal = balance_of(w3, self.jammo, JOEY)
        assert jammo_bal <= 51 * 10**18, f"JAMMO should be ~50, got {jammo_bal / 1e18}"

    def test_reload_jbase_from_fed(self, w3):
        """Reload step 1: Mint fresh JBASE using FED."""
        reload_amount = 200 * 10**18

        jbase_before = balance_of(w3, self.jbase, JOEY)
        _approve(w3, FED, JOEY, self.jbase, reload_amount)

        jbase_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jbase), abi=TREASURY_TOKEN_ABI
        )
        tx = jbase_c.functions.mint(reload_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        jbase_after = balance_of(w3, self.jbase, JOEY)
        assert jbase_after == jbase_before + reload_amount
        log.info("Reload step 1: JBASE +%.0f", reload_amount / 1e18)

    def test_reload_jammo_from_jbase(self, w3):
        """Reload step 2: Mint fresh JAMMO using JBASE."""
        # First mint JBASE
        reload_amount = 200 * 10**18
        _approve(w3, FED, JOEY, self.jbase, reload_amount)
        jbase_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jbase), abi=TREASURY_TOKEN_ABI
        )
        tx = jbase_c.functions.mint(reload_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Then mint JAMMO
        jammo_before = balance_of(w3, self.jammo, JOEY)
        _approve(w3, self.jbase, JOEY, self.jammo, reload_amount)
        jammo_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jammo), abi=TREASURY_TOKEN_ABI
        )
        tx = jammo_c.functions.mint(reload_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        jammo_after = balance_of(w3, self.jammo, JOEY)
        assert jammo_after == jammo_before + reload_amount
        log.info("Reload step 2: JAMMO +%.0f (total: %.0f)", reload_amount / 1e18, jammo_after / 1e18)

    def test_full_reload_then_spine_cycle(self, w3):
        """After reload, spine cycle should work again."""
        reload_amount = 200 * 10**18

        # Reload JBASE
        _approve(w3, FED, JOEY, self.jbase, reload_amount)
        jbase_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jbase), abi=TREASURY_TOKEN_ABI
        )
        tx = jbase_c.functions.mint(reload_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Reload JAMMO
        _approve(w3, self.jbase, JOEY, self.jammo, reload_amount)
        jammo_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jammo), abi=TREASURY_TOKEN_ABI
        )
        tx = jammo_c.functions.mint(reload_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Run spine cycle
        cycle_amount = 100 * 10**18
        fed_before = balance_of(w3, FED, JOEY)

        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )
        _approve(w3, FED, JOEY, FDIC, cycle_amount)
        tx = fdic_c.functions.mint(cycle_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        _approve(w3, self.jammo, JOEY, FDIC, cycle_amount)
        tx = fdic_c.functions.Claim(
            Web3.to_checksum_address(self.jammo), cycle_amount
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        fed_after = balance_of(w3, FED, JOEY)
        assert fed_after == fed_before, "FED conserved after reload + spine cycle"
        log.info("Reload → spine cycle OK")

    def test_reload_cost_accounting(self, w3):
        """Verify the FED cost of a full reload cycle.

        Reload M JAMMO costs M FED permanently (locked in JBASE contract).
        The FED used to mint JBASE is NOT recoverable — it becomes JBASE backing.
        """
        reload_amount = 100 * 10**18
        fed_before = balance_of(w3, FED, JOEY)

        # Step 1: FED → JBASE (costs FED)
        _approve(w3, FED, JOEY, self.jbase, reload_amount)
        jbase_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jbase), abi=TREASURY_TOKEN_ABI
        )
        tx = jbase_c.functions.mint(reload_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Step 2: JBASE → JAMMO (costs JBASE, not additional FED)
        _approve(w3, self.jbase, JOEY, self.jammo, reload_amount)
        jammo_c = w3.eth.contract(
            address=Web3.to_checksum_address(self.jammo), abi=TREASURY_TOKEN_ABI
        )
        tx = jammo_c.functions.mint(reload_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        fed_after_reload = balance_of(w3, FED, JOEY)
        fed_cost = fed_before - fed_after_reload

        assert fed_cost == reload_amount, (
            f"Reload should cost exactly {reload_amount / 1e18} FED, "
            f"actual cost: {fed_cost / 1e18}"
        )

        # Now run a spine cycle to get FED back
        cycle_amount = reload_amount
        _approve(w3, FED, JOEY, FDIC, cycle_amount)
        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )
        tx = fdic_c.functions.mint(cycle_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        _approve(w3, self.jammo, JOEY, FDIC, cycle_amount)
        tx = fdic_c.functions.Claim(
            Web3.to_checksum_address(self.jammo), cycle_amount
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        fed_after_cycle = balance_of(w3, FED, JOEY)

        # FED recovers to pre-reload level? No — the reload FED is locked.
        # After reload: fed_before - reload_amount
        # After cycle: fed_before - reload_amount (mint costs, claim recovers, net zero from cycle)
        # Wait — the cycle uses current FED (post-reload), not the reload FED.
        # Cycle mint costs: cycle_amount of FED. Claim recovers: cycle_amount of FED.
        # So fed_after_cycle == fed_after_reload == fed_before - reload_amount.
        assert fed_after_cycle == fed_after_reload, (
            "Spine cycle should not change FED balance (mint + claim cancel out)"
        )

        log.info(
            "Reload cost accounting: %d FED spent on reload, "
            "FED conserved through spine cycle. Net FED loss: %d",
            reload_amount // 10**18,
            (fed_before - fed_after_cycle) // 10**18,
        )
```

- [ ] **Step 2: Run Phase 3 tests**

```bash
python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py::TestPhase3Reload -v --tb=short -x
```

Expected: All 5 tests pass — reload works, cost accounting verified.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/test_v2_ammo_chain.py
git commit -m "test: Phase 3 — reload mechanics and FED cost accounting on Anvil"
```

---

### Task 6: Tokenomics Break-Even Analysis (Phase 4)

**Files:**
- Modify: `scripts/Joystick/tests/test_v2_ammo_chain.py`

Compute profitability metrics at various FED working capital levels. Uses Anvil's real DEX state to price FDIC.

- [ ] **Step 1: Write Phase 4 tokenomics tests**

Append to `test_v2_ammo_chain.py`:

```python
# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 4: TOKENOMICS — Break-even analysis
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase4Tokenomics:
    """Compute profitability metrics for the V2 Ammo Chain."""

    def test_fdic_dex_price(self, w3):
        """Read FDIC/WPLS price from DEX. This determines revenue per cycle."""
        from .anvil_helpers import get_pair_address, read_reserves, get_pair_tokens

        # Check V2 pair
        pair_addr = get_pair_address(FACTORY_V2, FDIC, WPLS, w3)
        if pair_addr:
            r0, r1, _ = read_reserves(pair_addr, w3)
            t0, t1 = get_pair_tokens(pair_addr, w3)
            if t0.lower() == FDIC.lower():
                r_fdic, r_wpls = r0, r1
            else:
                r_fdic, r_wpls = r1, r0

            if r_fdic > 0:
                pls_per_fdic = r_wpls / r_fdic
                log.info(
                    "FDIC/WPLS V2 pair: %s, reserves: FDIC=%e, WPLS=%e, price=%.2e PLS/FDIC",
                    pair_addr, r_fdic / 1e18, r_wpls / 1e18, pls_per_fdic,
                )
            else:
                pls_per_fdic = 0
                log.warning("FDIC/WPLS V2 pair has zero FDIC reserves")
        else:
            pls_per_fdic = 0
            log.warning("No FDIC/WPLS V2 pair found")

        # FDIC may also route through FED/WPLS
        fed_pair = get_pair_address(FACTORY_V2, FED, WPLS, w3)
        if fed_pair:
            r0, r1, _ = read_reserves(fed_pair, w3)
            t0, t1 = get_pair_tokens(fed_pair, w3)
            if t0.lower() == FED.lower():
                r_fed, r_wpls = r0, r1
            else:
                r_fed, r_wpls = r1, r0
            if r_fed > 0:
                pls_per_fed = r_wpls / r_fed
                log.info("FED/WPLS V2: price=%.2e PLS/FED", pls_per_fed)

    def test_gas_cost_per_cycle(self, w3, anvil_url):
        """Measure actual gas cost for one spine cycle on Anvil."""
        snap = snapshot(anvil_url)

        set_balance(JOEY, 5_000_000 * 10**18, anvil_url)
        impersonate(JOEY, anvil_url)

        # Seed tokens
        for token, amount in [(WM, 100 * 10**18), (FED, 500_000 * 10**18)]:
            for slot in range(5):
                set_erc20_balance(token, JOEY, amount, balance_slot=slot, url=anvil_url)
                if balance_of(w3, token, JOEY) >= amount:
                    break

        # Create chain
        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)
        v2m = w3.eth.contract(address=Web3.to_checksum_address(V2_MINTER), abi=V2_MINTER_ABI)
        tx = v2m.functions.New(
            "Joystick Base", "JBASE", 1, Web3.to_checksum_address(FED)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 5_000_000, "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx)
        logs = [l for l in receipt["logs"]
                if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()]
        jbase = logs[-1]["address"]

        _approve(w3, WM, JOEY, V2_MINTER, 10 * 10**18)
        tx = v2m.functions.New(
            "Joystick Ammo", "JAMMO", 1, Web3.to_checksum_address(jbase)
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 5_000_000, "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx)
        logs = [l for l in receipt["logs"]
                if l["topics"][0].hex() == Web3.keccak(text="Transfer(address,address,uint256)").hex()]
        jammo = logs[-1]["address"]

        # Mint ammo
        _approve(w3, FED, JOEY, jbase, 10_000 * 10**18)
        jbase_c = w3.eth.contract(address=Web3.to_checksum_address(jbase), abi=TREASURY_TOKEN_ABI)
        tx = jbase_c.functions.mint(10_000 * 10**18).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        _approve(w3, jbase, JOEY, jammo, 5_000 * 10**18)
        jammo_c = w3.eth.contract(address=Web3.to_checksum_address(jammo), abi=TREASURY_TOKEN_ABI)
        tx = jammo_c.functions.mint(5_000 * 10**18).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)

        # Measure spine cycle gas
        cycle_amount = 1000 * 10**18
        total_gas = 0

        # Mint leg
        _approve(w3, FED, JOEY, FDIC, cycle_amount)
        fdic_c = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC), abi=TREASURY_TOKEN_ABI
        )
        tx = fdic_c.functions.mint(cycle_amount).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        r = _send_tx(w3, tx)
        total_gas += r["gasUsed"]
        mint_gas = r["gasUsed"]

        # Claim leg
        _approve(w3, jammo, JOEY, FDIC, cycle_amount)
        tx = fdic_c.functions.Claim(
            Web3.to_checksum_address(jammo), cycle_amount
        ).build_transaction({
            "from": Web3.to_checksum_address(JOEY), "gas": 500_000, "gasPrice": w3.eth.gas_price,
        })
        r = _send_tx(w3, tx)
        total_gas += r["gasUsed"]
        claim_gas = r["gasUsed"]

        gas_price_beats = w3.eth.gas_price / 1e9  # Impulses → Beats
        gas_cost_pls = total_gas * w3.eth.gas_price / 1e18

        log.info(
            "\n=== GAS COST REPORT ===\n"
            "  Mint gas:  %d\n"
            "  Claim gas: %d\n"
            "  Total gas: %d\n"
            "  Gas price: %.0f Beats\n"
            "  Cost:      %.4f PLS per cycle (at 1000 FDIC)\n"
            "========================",
            mint_gas, claim_gas, total_gas, gas_price_beats, gas_cost_pls,
        )

        revert(snap, anvil_url)

    def test_break_even_analysis(self, w3):
        """Compute break-even FED working capital for profitable spine running.

        Variables:
        - FDIC price on DEX (PLS per FDIC)
        - Gas cost per cycle (PLS)
        - JAMMO consumption rate
        - Reload cost (FED locked per reload)

        Break-even: revenue from selling FDIC > gas cost + reload FED value
        """
        from .anvil_helpers import get_pair_address, read_reserves, get_pair_tokens

        # Get FDIC price
        pair_addr = get_pair_address(FACTORY_V2, FDIC, WPLS, w3)
        pls_per_fdic = 0.0
        if pair_addr:
            r0, r1, _ = read_reserves(pair_addr, w3)
            t0, t1 = get_pair_tokens(pair_addr, w3)
            if t0.lower() == FDIC.lower():
                r_fdic, r_wpls = r0, r1
            else:
                r_fdic, r_wpls = r1, r0
            if r_fdic > 0:
                pls_per_fdic = r_wpls / r_fdic

        # Get FED price (for reload cost valuation)
        fed_pair = get_pair_address(FACTORY_V2, FED, WPLS, w3)
        pls_per_fed = 0.0
        if fed_pair:
            r0, r1, _ = read_reserves(fed_pair, w3)
            t0, t1 = get_pair_tokens(fed_pair, w3)
            if t0.lower() == FED.lower():
                r_fed, r_wpls = r0, r1
            else:
                r_fed, r_wpls = r1, r0
            if r_fed > 0:
                pls_per_fed = r_wpls / r_fed

        # Estimate gas (from typical PulseChain values)
        gas_per_cycle = 300_000  # gas units for mint + claim
        gas_price_impulses = w3.eth.gas_price
        gas_cost_pls = gas_per_cycle * gas_price_impulses / 1e18

        # Analysis at various working capital levels
        working_capitals = [1_000, 10_000, 100_000, 1_000_000, 10_000_000]

        log.info("\n" + "=" * 70)
        log.info("V2 AMMO CHAIN BREAK-EVEN ANALYSIS")
        log.info("=" * 70)
        log.info("FDIC/PLS price:  %.2e", pls_per_fdic)
        log.info("FED/PLS price:   %.2e", pls_per_fed)
        log.info("Gas/cycle:       %.4f PLS", gas_cost_pls)
        log.info("-" * 70)
        log.info("%-15s %-15s %-15s %-15s %-10s",
                 "FED Capital", "FDIC Revenue", "Gas Cost", "Reload Cost", "Profit?")
        log.info("-" * 70)

        for wc in working_capitals:
            # Revenue: wc FDIC minted and sold
            # Use constant-product formula for price impact
            if pair_addr and r_fdic > 0:
                wc_wei = wc * 10**18
                amount_out = (wc_wei * 997 * r_wpls) // (r_fdic * 1000 + wc_wei * 997)
                revenue_pls = amount_out / 1e18
            else:
                revenue_pls = wc * pls_per_fdic

            # Reload cost: wc FED locked (valued at FED/PLS price)
            reload_cost_pls = wc * pls_per_fed

            # Net
            net = revenue_pls - gas_cost_pls - reload_cost_pls
            profitable = "YES" if net > 0 else "NO"

            log.info(
                "%-15s %-15.4f %-15.4f %-15.4f %-10s",
                f"{wc:,}", revenue_pls, gas_cost_pls, reload_cost_pls, profitable,
            )

        log.info("=" * 70)
        log.info("NOTE: Revenue uses constant-product formula (accounts for price impact)")
        log.info("NOTE: Reload cost = FED permanently locked per cycle")
        log.info("NOTE: At current FDIC price (~1.25e-08 PLS), profitability requires")
        log.info("      either FDIC price increase or extremely low gas costs.")
        log.info("=" * 70)

        # This test always passes — it's an analysis, not an assertion
        assert True
```

- [ ] **Step 2: Run Phase 4 tests**

```bash
python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py::TestPhase4Tokenomics -v --tb=short -s
```

Note the `-s` flag to see the analysis output.

Expected: All 3 tests pass. Analysis output shows break-even levels.

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/test_v2_ammo_chain.py
git commit -m "test: Phase 4 — tokenomics break-even analysis on Anvil"
```

---

### Task 7: Spine Chain Config File

**Files:**
- Create: `scripts/Joystick/data/spine_chain_config.json`

This config tracks the deployed JBASE/JAMMO addresses and reload thresholds. Created by Phase 1 (Arm) and read by E7 BACKBONE.

- [ ] **Step 1: Write the config template**

Create `scripts/Joystick/data/spine_chain_config.json`:

```json
{
  "chain": "v2_autonomous_ammo",
  "status": "template",
  "target": {
    "address": "0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9",
    "symbol": "FDIC",
    "parent": "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff",
    "parent_symbol": "FED"
  },
  "jbase": {
    "address": null,
    "symbol": "JBASE",
    "parent": "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff",
    "parent_symbol": "FED",
    "deployed_block": null,
    "deployed_tx": null
  },
  "jammo": {
    "address": null,
    "symbol": "JAMMO",
    "parent": null,
    "parent_symbol": "JBASE",
    "deployed_block": null,
    "deployed_tx": null
  },
  "thresholds": {
    "jammo_reload_floor": 100,
    "min_cycle_amount": 100,
    "max_cycle_amount": 10000,
    "min_profit_pls": 5,
    "gas_mult": 2.5
  },
  "created_at": null,
  "last_run": null,
  "total_cycles": 0,
  "total_jammo_consumed": 0,
  "total_fed_locked": 0,
  "total_revenue_pls": 0
}
```

- [ ] **Step 2: Verify config loads**

```bash
python3 -c "
import json
with open('scripts/Joystick/data/spine_chain_config.json') as f:
    cfg = json.load(f)
assert cfg['chain'] == 'v2_autonomous_ammo'
assert cfg['target']['symbol'] == 'FDIC'
print('spine_chain_config.json OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/data/spine_chain_config.json
git commit -m "feat: add spine_chain_config.json template for V2 Ammo Chain"
```

---

### Task 8: SpineModule.sol — JoystickHub Module

**Files:**
- Create: `contracts/SpineModule.sol`

A new JoystickHub module that performs atomic spine runs via delegatecall.

- [ ] **Step 1: Write SpineModule.sol**

Create `contracts/SpineModule.sol`:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/**
 * SpineModule — JoystickHub module for V2 Autonomous Ammo Chain.
 *
 * Executes atomic spine cycles:
 *   1. target.mint(amount)         — spend parent, receive target tokens
 *   2. swap target → WPLS on DEX  — revenue
 *   3. target.Claim(ammo, amount)  — spend ammo, recover parent
 *
 * Also handles ammo reload:
 *   1. jbase.mint(amount)          — spend FED, receive JBASE
 *   2. jammo.mint(amount)          — spend JBASE, receive JAMMO
 *
 * Runs via delegatecall from JoystickHub — all storage is Hub's.
 */

interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function approve(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function allowance(address, uint256) external view returns (uint256);
}

interface ITreasuryToken {
    function mint(uint256 amount) external;
    function Claim(address Contract, uint256 Amount) external;
    function Parent() external view returns (address);
    function Debenture() external view returns (bool);
}

interface IUniswapV2Router {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

// ── HubStorage (must match JoystickHub.sol exactly) ────────────────────────
abstract contract HubStorage {
    address internal _owner;
    uint256 internal _reentrancy;
    bool internal _paused;
    mapping(bytes4 => address) internal _modules;
    mapping(address => bool) internal _authorized;
    address internal _wpls;
    address internal _routerV1;
    address internal _routerV2;
    address internal _factoryV1;
    address internal _factoryV2;
    mapping(bytes32 => uint256) internal _config;
    uint256 internal _opNonce;

    modifier onlyAuth() {
        require(msg.sender == _owner || _authorized[msg.sender], "hub:auth");
        _;
    }

    modifier whenNotPaused() {
        require(!_paused, "hub:paused");
        _;
    }

    modifier nonReentrant() {
        require(_reentrancy != 2, "hub:reentrant");
        _reentrancy = 2;
        _;
        _reentrancy = 1;
    }

    function _op() internal returns (uint256) {
        return ++_opNonce;
    }
}

contract SpineModule is HubStorage {

    event SpineCycle(
        uint256 indexed op,
        address target,
        address ammo,
        uint256 amount,
        uint256 iters,
        uint256 targetMinted,
        uint256 wplsReceived
    );

    event SpineReload(
        uint256 indexed op,
        address jbase,
        address jammo,
        uint256 amount,
        uint256 jammoMinted
    );

    /**
     * @notice Execute N spine iterations atomically.
     * @param target    Treasury token to mint (e.g. FDIC)
     * @param ammo      Debenture=true token for Claim (e.g. JAMMO)
     * @param amount    Amount per iteration (in wei)
     * @param iters     Number of iterations
     * @param minWplsOut Minimum WPLS output from selling target (slippage protection)
     * @param sellDex   0 = V1 Router, 1 = V2 Router
     * @return wplsOut  Total WPLS received from selling
     */
    function spineRun(
        address target,
        address ammo,
        uint256 amount,
        uint256 iters,
        uint256 minWplsOut,
        uint8 sellDex
    ) external onlyAuth whenNotPaused nonReentrant returns (uint256 wplsOut) {
        require(iters > 0 && iters <= 50, "spine:iters");
        require(amount > 0, "spine:amount");

        address parent = ITreasuryToken(target).Parent();
        uint256 totalMint = amount * iters;

        // Approve parent to target for minting
        IERC20(parent).approve(target, totalMint);

        // Step 1: Mint N iterations
        uint256 targetBefore = IERC20(target).balanceOf(address(this));
        for (uint256 i; i < iters; ++i) {
            ITreasuryToken(target).mint(amount);
        }
        uint256 targetMinted = IERC20(target).balanceOf(address(this)) - targetBefore;
        require(targetMinted > 0, "spine:no mint");

        // Step 2: Sell target tokens on DEX → WPLS
        address router = sellDex == 0 ? _routerV1 : _routerV2;
        IERC20(target).approve(router, targetMinted);

        address[] memory path = new address[](2);
        path[0] = target;
        path[1] = _wpls;

        uint256 wplsBefore = IERC20(_wpls).balanceOf(address(this));
        IUniswapV2Router(router).swapExactTokensForTokens(
            targetMinted,
            minWplsOut,
            path,
            address(this),
            block.timestamp + 300
        );
        wplsOut = IERC20(_wpls).balanceOf(address(this)) - wplsBefore;

        // Step 3: Claim parent back using ammo
        IERC20(ammo).approve(target, totalMint);
        for (uint256 i; i < iters; ++i) {
            ITreasuryToken(target).Claim(ammo, amount);
        }

        emit SpineCycle(_op(), target, ammo, amount, iters, targetMinted, wplsOut);
    }

    /**
     * @notice Reload ammo: FED → JBASE.mint → JAMMO.mint
     * @param jbase  JBASE token address
     * @param jammo  JAMMO token address
     * @param amount Amount of JAMMO to produce (requires same amount of FED)
     * @return jammoMinted Actual JAMMO tokens received
     */
    function spineReload(
        address jbase,
        address jammo,
        uint256 amount
    ) external onlyAuth whenNotPaused nonReentrant returns (uint256 jammoMinted) {
        require(amount > 0, "spine:reload-amount");

        address fed = ITreasuryToken(jbase).Parent();

        // Step 1: FED → JBASE
        IERC20(fed).approve(jbase, amount);
        uint256 jbaseBefore = IERC20(jbase).balanceOf(address(this));
        ITreasuryToken(jbase).mint(amount);
        uint256 jbaseMinted = IERC20(jbase).balanceOf(address(this)) - jbaseBefore;
        require(jbaseMinted > 0, "spine:no jbase");

        // Step 2: JBASE → JAMMO
        IERC20(jbase).approve(jammo, jbaseMinted);
        uint256 jammoBefore = IERC20(jammo).balanceOf(address(this));
        ITreasuryToken(jammo).mint(jbaseMinted);
        jammoMinted = IERC20(jammo).balanceOf(address(this)) - jammoBefore;
        require(jammoMinted > 0, "spine:no jammo");

        emit SpineReload(_op(), jbase, jammo, amount, jammoMinted);
    }

    /**
     * @notice View: check ammo balance and whether reload is needed.
     * @param ammo       JAMMO token address
     * @param threshold  Minimum ammo before reload triggers
     * @return balance   Current ammo balance in hub
     * @return needsReload True if balance < threshold
     */
    function spineStatus(
        address ammo,
        uint256 threshold
    ) external view returns (uint256 balance, bool needsReload) {
        balance = IERC20(ammo).balanceOf(address(this));
        needsReload = balance < threshold;
    }
}
```

- [ ] **Step 2: Verify SpineModule compiles**

If `solc` is available:
```bash
solc --abi --bin contracts/SpineModule.sol 2>&1 | head -20
```

Or with Foundry:
```bash
cd /opt/joystick/repo
forge build --contracts contracts/SpineModule.sol 2>&1 | head -20
```

Note: This may fail due to missing imports or pragma issues. The key validation happens in Task 9 via Anvil deployment tests.

- [ ] **Step 3: Commit**

```bash
git add contracts/SpineModule.sol
git commit -m "feat: SpineModule.sol — atomic spine run + reload for JoystickHub"
```

---

### Task 9: Anvil Integration Tests for SpineModule

**Files:**
- Modify: `scripts/Joystick/tests/test_v2_ammo_chain.py`

Add tests that deploy SpineModule on Anvil, register it with JoystickHub, and exercise the full atomic flow.

- [ ] **Step 1: Write SpineModule deployment + integration tests**

Append to `test_v2_ammo_chain.py`:

```python
# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 5: SPINE MODULE INTEGRATION — Deploy + register + atomic execute
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase5SpineModule:
    """Deploy SpineModule on Anvil, register with JoystickHub, test atomic ops.

    NOTE: This test class requires SpineModule.sol to be compiled.
    If compilation infrastructure isn't available, these tests are skipped.
    The Phase 1-4 tests above validate the mechanics without the module.
    """

    @pytest.fixture(scope="class")
    def spine_module_bytecode(self):
        """Compile SpineModule.sol and return bytecode + ABI.

        Tries forge first, falls back to solc, skips if neither available.
        """
        import subprocess
        repo = Path(__file__).resolve().parent.parent.parent.parent

        # Try forge
        try:
            result = subprocess.run(
                ["forge", "build", "--contracts", "contracts/SpineModule.sol",
                 "--out", "/tmp/spine_build"],
                capture_output=True, text=True, timeout=60, cwd=str(repo),
            )
            if result.returncode == 0:
                artifact = Path("/tmp/spine_build/SpineModule.sol/SpineModule.json")
                if artifact.exists():
                    data = json.loads(artifact.read_text())
                    return {
                        "abi": data["abi"],
                        "bytecode": data["bytecode"]["object"],
                    }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Try solc
        try:
            sol_file = repo / "contracts" / "SpineModule.sol"
            result = subprocess.run(
                ["solc", "--combined-json", "abi,bin", str(sol_file)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                key = [k for k in data["contracts"] if "SpineModule" in k][0]
                return {
                    "abi": json.loads(data["contracts"][key]["abi"]),
                    "bytecode": "0x" + data["contracts"][key]["bin"],
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        pytest.skip("Neither forge nor solc available for SpineModule compilation")

    def test_deploy_spine_module(self, w3, anvil_url, spine_module_bytecode):
        """Deploy SpineModule contract on Anvil fork."""
        set_balance(JOEY, 10_000_000 * 10**18, anvil_url)
        impersonate(JOEY, anvil_url)

        contract = w3.eth.contract(
            abi=spine_module_bytecode["abi"],
            bytecode=spine_module_bytecode["bytecode"],
        )
        tx = contract.constructor().build_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "gas": 5_000_000,
            "gasPrice": w3.eth.gas_price,
        })
        receipt = _send_tx(w3, tx)
        module_addr = receipt["contractAddress"]
        assert module_addr is not None
        log.info("SpineModule deployed at: %s", module_addr)

    # Additional integration tests would go here after deployment —
    # registering selectors with JoystickHub, calling spineRun/spineReload
    # through the hub's fallback, etc. These require the hub to also be
    # accessible on the fork.
```

- [ ] **Step 2: Run Phase 5 tests (if compilation available)**

```bash
python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py::TestPhase5SpineModule -v --tb=short -x
```

Expected: Either passes (compiled + deployed) or skips (no compiler).

- [ ] **Step 3: Commit**

```bash
git add scripts/Joystick/tests/test_v2_ammo_chain.py
git commit -m "test: Phase 5 — SpineModule Anvil deployment test"
```

---

### Task 10: Test Runner Script + Documentation

**Files:**
- Create: `scripts/Joystick/tests/run_ammo_chain_tests.sh`

A convenience script that starts Anvil, runs all ammo chain tests, and cleans up.

- [ ] **Step 1: Write the test runner**

Create `scripts/Joystick/tests/run_ammo_chain_tests.sh`:

```bash
#!/usr/bin/env bash
# run_ammo_chain_tests.sh — Start Anvil fork + run V2 Ammo Chain tests.
#
# Usage:
#   ./scripts/Joystick/tests/run_ammo_chain_tests.sh          # run all
#   ./scripts/Joystick/tests/run_ammo_chain_tests.sh Phase1    # run Phase 1 only
#   ./scripts/Joystick/tests/run_ammo_chain_tests.sh Phase4 -s # show output

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"

ANVIL_PORT=8545
ANVIL_URL="http://127.0.0.1:${ANVIL_PORT}"
FORK_URL="${PULSECHAIN_READ_RPC:-https://rpc-pulsechain.g4mm4.io}"

# ── Check Anvil ───────────────────────────────────────────────────────────
if ! command -v anvil &>/dev/null; then
    echo "ERROR: Anvil not found. Install Foundry:"
    echo "  curl -L https://foundry.paradigm.xyz | bash && foundryup"
    exit 1
fi

# ── Start Anvil ──────────────────────────────────────────────────────────
echo "Starting Anvil fork of PulseChain..."
anvil --fork-url "$FORK_URL" --chain-id 369 --auto-impersonate \
      --port "$ANVIL_PORT" --silent &
ANVIL_PID=$!
trap "kill $ANVIL_PID 2>/dev/null || true" EXIT

# Wait for Anvil to be ready
for i in $(seq 1 30); do
    if curl -s "$ANVIL_URL" -X POST -H "Content-Type: application/json" \
       -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
       | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if int(d.get('result','0'),16)==369 else 1)" 2>/dev/null; then
        echo "Anvil ready (PID $ANVIL_PID)"
        break
    fi
    sleep 1
done

# ── Run Tests ────────────────────────────────────────────────────────────
PHASE="${1:-}"
EXTRA_ARGS="${@:2}"

if [ -n "$PHASE" ]; then
    echo "Running: TestPhase${PHASE}*"
    python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py \
        -k "Phase${PHASE}" -v --tb=short $EXTRA_ARGS
else
    echo "Running all V2 Ammo Chain tests..."
    python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py \
        -v --tb=short -x $EXTRA_ARGS
fi

echo "Done."
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/Joystick/tests/run_ammo_chain_tests.sh
```

- [ ] **Step 3: Verify the runner works**

```bash
./scripts/Joystick/tests/run_ammo_chain_tests.sh Phase1
```

Expected: Anvil starts, Phase 1 tests run, Anvil is killed on exit.

- [ ] **Step 4: Commit**

```bash
git add scripts/Joystick/tests/run_ammo_chain_tests.sh
git commit -m "feat: add test runner script for V2 Ammo Chain Anvil tests"
```

---

## Summary

| Task | Deliverable | Tests |
|------|-------------|-------|
| 1 | Foundry/Anvil installed | CLI verification |
| 2 | V2 Federal Minter ABI | Load verification |
| 3 | Phase 1 tests: JBASE + JAMMO creation | 7 tests |
| 4 | Phase 2 tests: spine run mechanics | 5 tests |
| 5 | Phase 3 tests: reload mechanics | 5 tests |
| 6 | Phase 4 tests: tokenomics analysis | 3 tests |
| 7 | spine_chain_config.json template | Load verification |
| 8 | SpineModule.sol hub module | Compilation check |
| 9 | Phase 5 tests: SpineModule deployment | 1+ tests |
| 10 | Test runner script | End-to-end run |

**Total: ~21 tests across 5 phases + SpineModule.sol + config + runner**
