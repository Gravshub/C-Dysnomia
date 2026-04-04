"""
test_v2_ammo_chain.py — Anvil fork test suite for the V2 Autonomous Ammo Chain.

Tests the full lifecycle of a V2 Federal spine: token creation, spine run
mechanics (mint + claim), ammo reload, and break-even analysis.

The "ammo chain" pattern:
  1. JBASE (parent=FED) — the spine token. Minted with FED, claims FED back.
  2. JAMMO (parent=JBASE) — the ammo token. Debenture=true → can be used in
     Claim(). JBASE.Claim(JAMMO, N) burns JAMMO, returns FED to caller.
  3. Reload loop: FED → JBASE.mint → JAMMO.mint → repeat.

This gives an infinite loop as long as Debenture remains true on both tokens.

Requires Anvil running with a PulseChain fork:
  anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

Run:
  cd /opt/joystick/repo
  python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py -v --tb=short

"You're in the Matrix, man — every token is a door."
"""

import json
import logging
import pytest

from pathlib import Path
from web3 import Web3

from .anvil_helpers import (
    set_balance,
    impersonate,
    stop_impersonate,
    snapshot,
    revert,
    approve_via_impersonate,
    set_erc20_balance,
    find_balance_slot,
    balance_of,
    get_pair_address,
    read_reserves,
    get_pair_tokens,
)

log = logging.getLogger("joystick.test.v2_ammo")

# ── Key Addresses ────────────────────────────────────────────────────────────

JOEY        = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
V2_MINTER   = "0xc15c5F699Daf5e1135732139f05D2c05b3EF4354"
FED         = "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff"
FDIC        = "0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9"
WM          = "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"
WPLS        = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
ROUTER_V2   = "0x165C3410fC91EF562C50559f7d2289fEbed552d9"
FACTORY_V2  = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"

# ERC20 Transfer event topic (keccak256 of "Transfer(address,address,uint256)"))
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Seed amounts for test setup
_WM_SEED    = 500 * 10**18      # 500 WM — enough for many NT.New() calls
_FED_SEED   = 10_000 * 10**18  # 10,000 FED — spine capital


# ── ABI Loading ───────────────────────────────────────────────────────────────

def _load_abi(name: str) -> list:
    """Load ABI from data/abis/{name}.json."""
    path = Path(__file__).parent.parent / "data" / "abis" / f"{name}.json"
    with open(path) as f:
        return json.load(f)


# ── TX Helpers ────────────────────────────────────────────────────────────────

def _send_tx(w3: Web3, tx_dict: dict) -> dict:
    """
    Send a transaction via Anvil impersonation.
    Asserts status==1 (success). Returns the receipt.
    """
    tx_hash = w3.eth.send_transaction(tx_dict)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1, (
        f"TX reverted: {tx_hash.hex()}\n"
        f"  from={tx_dict.get('from')}, to={tx_dict.get('to')}\n"
        f"  data={tx_dict.get('data', '')[:80]}..."
    )
    return receipt


_GAS_FUND = 2_000 * 10**18  # PulseChain gas is expensive (~540K Beats)


def _approve(w3: Web3, token: str, owner: str, spender: str, amount: int, anvil_url: str) -> None:
    """Approve spender to spend owner's tokens via impersonation.

    Overrides anvil_helpers.approve_via_impersonate with higher gas funding
    because PulseChain gas price * gas limit can easily exceed 10 PLS.
    """
    impersonate(owner, anvil_url)
    set_balance(owner, _GAS_FUND, anvil_url)
    tx = {
        "from": Web3.to_checksum_address(owner),
        "to": Web3.to_checksum_address(token),
        "data": (
            "0x095ea7b3"
            + spender.lower().replace("0x", "").zfill(64)
            + hex(amount)[2:].zfill(64)
        ),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
    }
    tx_hash = w3.eth.send_transaction(tx)
    w3.eth.wait_for_transaction_receipt(tx_hash)
    stop_impersonate(owner, anvil_url)


def _seed_token(w3: Web3, token: str, holder: str, amount: int, anvil_url: str) -> None:
    """
    Seed a holder with ERC20 tokens by probing storage slots 0-4.
    Falls back to find_balance_slot if probing fails.
    """
    for slot in range(5):
        snap = snapshot(anvil_url)
        try:
            set_erc20_balance(token, holder, amount, balance_slot=slot, url=anvil_url)
            actual = balance_of(w3, token, holder)
            if actual == amount:
                log.debug("Seeded %s slot=%d amount=%d", token[:10], slot, amount)
                return
        except Exception:
            pass
        revert(snap, anvil_url)

    # Last resort: brute-force find the slot
    slot = find_balance_slot(token, holder, w3)
    if slot is not None:
        set_erc20_balance(token, holder, amount, balance_slot=slot, url=anvil_url)
        log.debug("Seeded %s via find_balance_slot=%d", token[:10], slot)
    else:
        raise RuntimeError(f"Cannot find balance slot for token {token}")


def _new_token_via_minter(
    w3: Web3,
    anvil_url: str,
    name: str,
    symbol: str,
    initial_mint: int,
    parent: str,
    caller: str,
    minter_addr: str = V2_MINTER,
) -> str:
    """
    Call NT.New(name, symbol, initial_mint, parent) from caller.
    Returns the new TT contract address extracted from the last Transfer event
    in the receipt (the mint event from the new token's constructor).

    Note: web3.py cannot decode return values from send_transaction — we extract
    the deployed address from logs instead.
    """
    minter_abi = _load_abi("v2_federal_minter")
    minter = w3.eth.contract(
        address=Web3.to_checksum_address(minter_addr),
        abi=minter_abi,
    )

    # Ensure caller has WM approved to V2_MINTER
    _approve(w3, WM, caller, minter_addr, initial_mint * 10, anvil_url)

    impersonate(caller, anvil_url)
    set_balance(caller, _GAS_FUND, anvil_url)  # PulseChain gas is expensive

    tx = minter.functions.New(name, symbol, initial_mint, Web3.to_checksum_address(parent)).build_transaction({
        "from": Web3.to_checksum_address(caller),
        "gas": 3_000_000,
        "gasPrice": w3.eth.gas_price,
    })
    receipt = _send_tx(w3, tx)
    stop_impersonate(caller, anvil_url)

    # Extract new TT address: last Transfer log in receipt where from=0x0 (mint event)
    transfer_topic = _TRANSFER_TOPIC
    new_addr = None
    for log_entry in receipt["logs"]:
        topics = log_entry.get("topics", [])
        if (
            len(topics) >= 3
            and topics[0].hex() == transfer_topic.lower().replace("0x", "")
            # from == address(0) means this is a mint
            and topics[1].hex() == "0" * 64
        ):
            new_addr = log_entry["address"]

    if new_addr is None:
        # Fallback: last Transfer log of any kind — the newest contract's mint
        for log_entry in reversed(receipt["logs"]):
            topics = log_entry.get("topics", [])
            if len(topics) >= 3 and topics[0].hex() == transfer_topic.lower().replace("0x", ""):
                new_addr = log_entry["address"]
                break

    assert new_addr is not None, "Could not extract new TT address from receipt logs"
    return Web3.to_checksum_address(new_addr)


def _create_ammo_chain(w3: Web3, anvil_url: str) -> dict:
    """
    Full ammo chain setup: JBASE (parent=FED) + JAMMO (parent=JBASE).

    Steps:
      1. Seed Joey with WM and FED
      2. Create JBASE via NT.New("JBASE", "JBASE", 1, FED)
      3. Create JAMMO via NT.New("JAMMO", "JAMMO", 1, JBASE)
      4. Mint initial JBASE supply (FED → JBASE.mint)
      5. Mint initial JAMMO supply (JBASE → JAMMO.mint)

    Returns a dict with:
      jbase_addr, jammo_addr, jbase_contract, jammo_contract,
      joey_fed_start, joey_wm_start
    """
    tt_abi = _load_abi("treasury_token")
    joey = Web3.to_checksum_address(JOEY)

    # ── 1. Seed Joey ────────────────────────────────────────────────────────
    set_balance(joey, _GAS_FUND, anvil_url)
    _seed_token(w3, WM, joey, _WM_SEED, anvil_url)
    _seed_token(w3, FED, joey, _FED_SEED, anvil_url)

    log.info("Setup: WM=%d, FED=%d", balance_of(w3, WM, joey), balance_of(w3, FED, joey))

    # ── 2. Create JBASE (parent=FED) ────────────────────────────────────────
    jbase_addr = _new_token_via_minter(
        w3, anvil_url,
        name="JBASE", symbol="JBASE",
        initial_mint=1,
        parent=FED,
        caller=joey,
    )
    log.info("JBASE deployed: %s", jbase_addr)

    jbase = w3.eth.contract(address=jbase_addr, abi=tt_abi)

    # ── 3. Create JAMMO (parent=JBASE) ──────────────────────────────────────
    # JAMMO's NT.New costs 1 WM. Parent must be JBASE (a registered TreasuryToken).
    jammo_addr = _new_token_via_minter(
        w3, anvil_url,
        name="JAMMO", symbol="JAMMO",
        initial_mint=1,
        parent=jbase_addr,
        caller=joey,
    )
    log.info("JAMMO deployed: %s", jammo_addr)

    jammo = w3.eth.contract(address=jammo_addr, abi=tt_abi)

    # ── 4. Mint JBASE supply via FED ────────────────────────────────────────
    # FED → JBASE.mint(100e18)
    mint_amount = 100 * 10**18
    _approve(w3, FED, joey, jbase_addr, mint_amount * 10, anvil_url)

    impersonate(joey, anvil_url)
    set_balance(joey, _GAS_FUND, anvil_url)
    tx = jbase.functions.mint(mint_amount).build_transaction({
        "from": joey,
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
    })
    _send_tx(w3, tx)
    stop_impersonate(joey, anvil_url)

    log.info("JBASE supply minted: %d", balance_of(w3, jbase_addr, joey))

    # ── 5. Mint JAMMO supply via JBASE ───────────────────────────────────────
    # JBASE → JAMMO.mint(50e18)
    jammo_mint = 50 * 10**18
    _approve(w3, jbase_addr, joey, jammo_addr, jammo_mint * 10, anvil_url)

    impersonate(joey, anvil_url)
    set_balance(joey, _GAS_FUND, anvil_url)
    tx = jammo.functions.mint(jammo_mint).build_transaction({
        "from": joey,
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
    })
    _send_tx(w3, tx)
    stop_impersonate(joey, anvil_url)

    log.info("JAMMO supply minted: %d", balance_of(w3, jammo_addr, joey))

    return {
        "jbase_addr": jbase_addr,
        "jammo_addr": jammo_addr,
        "jbase": jbase,
        "jammo": jammo,
        "joey_fed_start": balance_of(w3, FED, joey),
        "joey_wm_start":  balance_of(w3, WM,  joey),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 1 — V2 Token Creation
#  Verify: V2Minter exists, FDIC state, JBASE + JAMMO creation mechanics
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase1TokenCreation:
    """
    Verify the V2 Federal Minter is reachable on fork and that creating
    new TT tokens (JBASE, JAMMO) produces correct on-chain state.

    JBASE + JAMMO are created once per class (scope="class") — creation is
    expensive (2 NT.New calls + 2 mint calls). Individual tests then read
    from the shared chain state.
    """

    # Class-level storage for addresses set during setup
    jbase_addr: str = None
    jammo_addr: str = None

    @pytest.fixture(scope="class", autouse=True)
    def _deploy_chain(self, w3, anvil_url):
        """Deploy JBASE + JAMMO once for the entire class. Stored on class."""
        snap = snapshot(anvil_url)

        joey = Web3.to_checksum_address(JOEY)
        set_balance(joey, _GAS_FUND, anvil_url)
        _seed_token(w3, WM, joey, _WM_SEED, anvil_url)
        _seed_token(w3, FED, joey, _FED_SEED, anvil_url)

        # Create JBASE
        jbase_addr = _new_token_via_minter(
            w3, anvil_url,
            name="JBASE", symbol="JBASE",
            initial_mint=1, parent=FED, caller=joey,
        )
        TestPhase1TokenCreation.jbase_addr = jbase_addr

        # Create JAMMO
        jammo_addr = _new_token_via_minter(
            w3, anvil_url,
            name="JAMMO", symbol="JAMMO",
            initial_mint=1, parent=jbase_addr, caller=joey,
        )
        TestPhase1TokenCreation.jammo_addr = jammo_addr

        yield

        revert(snap, anvil_url)

    # ── 1. V2 Minter exists ─────────────────────────────────────────────────

    def test_v2_minter_exists(self, w3):
        """V2 Federal Minter should have deployed code on the fork."""
        code = w3.eth.get_code(Web3.to_checksum_address(V2_MINTER))
        assert len(code) > 10, "V2_MINTER has no code on fork — check fork URL or block"
        log.info("V2_MINTER bytecode length: %d bytes", len(code))

    # ── 2. FDIC is registered ───────────────────────────────────────────────

    def test_fdic_is_registered(self, w3):
        """FDIC should be registered in V2Minter.TreasuryTokens."""
        minter_abi = _load_abi("v2_federal_minter")
        minter = w3.eth.contract(
            address=Web3.to_checksum_address(V2_MINTER),
            abi=minter_abi,
        )
        owner = minter.functions.TreasuryTokens(
            Web3.to_checksum_address(FDIC)
        ).call()
        assert owner != "0x" + "0" * 40, "FDIC not registered in V2Minter"
        log.info("FDIC registered, owner=%s", owner)

    # ── 3. FDIC Debenture is false (published) ──────────────────────────────

    def test_fdic_debenture_is_false(self, w3):
        """FDIC was published at construction — Debenture should be false."""
        tt_abi = _load_abi("treasury_token")
        fdic = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC),
            abi=tt_abi,
        )
        deb = fdic.functions.Debenture().call()
        assert deb is False, f"Expected FDIC Debenture=false, got {deb}"
        log.info("FDIC Debenture=false (published) ✓")

    # ── 4. FDIC parent is FED ───────────────────────────────────────────────

    def test_fdic_parent_is_fed(self, w3):
        """FDIC's parent token should be FED."""
        tt_abi = _load_abi("treasury_token")
        fdic = w3.eth.contract(
            address=Web3.to_checksum_address(FDIC),
            abi=tt_abi,
        )
        parent = fdic.functions.Parent().call()
        assert parent.lower() == FED.lower(), (
            f"FDIC parent mismatch: expected {FED}, got {parent}"
        )
        log.info("FDIC Parent=%s (FED) ✓", parent)

    # ── 5. FDIC holds FED backing ───────────────────────────────────────────

    def test_fdic_has_fed_balance(self, w3):
        """Check FDIC contract's FED balance (backing for Claim).

        Note: FDIC may or may not hold FED depending on fork block —
        backing can be withdrawn by owner. This test is informational.
        """
        fed_in_fdic = balance_of(w3, FED, FDIC)
        log.info("FDIC FED balance: %.4f FED", fed_in_fdic / 1e18)
        if fed_in_fdic == 0:
            log.warning("FDIC holds 0 FED — backing may have been withdrawn or fork is stale")

    # ── 6. Create JBASE ─────────────────────────────────────────────────────

    def test_create_jbase(self, w3):
        """
        NT.New('JBASE', 'JBASE', 1, FED) should:
          - Deploy a new TT contract
          - Register it in V2Minter.TreasuryTokens
          - Set Debenture=true
          - Set Parent=FED
        """
        assert TestPhase1TokenCreation.jbase_addr is not None, (
            "JBASE not deployed — _deploy_chain fixture failed"
        )
        jbase_addr = TestPhase1TokenCreation.jbase_addr
        tt_abi = _load_abi("treasury_token")
        minter_abi = _load_abi("v2_federal_minter")

        jbase = w3.eth.contract(address=jbase_addr, abi=tt_abi)
        minter = w3.eth.contract(
            address=Web3.to_checksum_address(V2_MINTER),
            abi=minter_abi,
        )

        # Debenture should be true (freshly created, not published)
        deb = jbase.functions.Debenture().call()
        assert deb is True, f"JBASE Debenture should be true, got {deb}"

        # Registered in V2Minter
        registered = minter.functions.TreasuryTokens(jbase_addr).call()
        assert registered != "0x" + "0" * 40, "JBASE not registered in V2Minter"

        # Parent is FED
        parent = jbase.functions.Parent().call()
        assert parent.lower() == FED.lower(), (
            f"JBASE parent should be FED ({FED}), got {parent}"
        )

        log.info("JBASE: addr=%s, Debenture=true, Parent=FED ✓", jbase_addr)

    # ── 7. Create JAMMO ─────────────────────────────────────────────────────

    def test_create_jammo(self, w3):
        """
        NT.New('JAMMO', 'JAMMO', 1, JBASE) should:
          - Deploy a new TT with parent=JBASE
          - Set Debenture=true
          - Be registered in V2Minter
        """
        assert TestPhase1TokenCreation.jammo_addr is not None, (
            "JAMMO not deployed — _deploy_chain fixture failed"
        )
        jammo_addr = TestPhase1TokenCreation.jammo_addr
        jbase_addr = TestPhase1TokenCreation.jbase_addr
        tt_abi = _load_abi("treasury_token")
        minter_abi = _load_abi("v2_federal_minter")

        jammo = w3.eth.contract(address=jammo_addr, abi=tt_abi)
        minter = w3.eth.contract(
            address=Web3.to_checksum_address(V2_MINTER),
            abi=minter_abi,
        )

        # Debenture should be true
        deb = jammo.functions.Debenture().call()
        assert deb is True, f"JAMMO Debenture should be true, got {deb}"

        # Registered in V2Minter
        registered = minter.functions.TreasuryTokens(jammo_addr).call()
        assert registered != "0x" + "0" * 40, "JAMMO not registered in V2Minter"

        # Parent is JBASE
        parent = jammo.functions.Parent().call()
        assert parent.lower() == jbase_addr.lower(), (
            f"JAMMO parent should be JBASE ({jbase_addr}), got {parent}"
        )

        log.info("JAMMO: addr=%s, Debenture=true, Parent=JBASE ✓", jammo_addr)


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 2 — Spine Run Mechanics
#  Verify: FDIC.mint (FED→FDIC) and FDIC.Claim (JAMMO→FED) work on fork
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def ammo_chain(w3, anvil_url):
    """
    Per-test fixture: snapshot → full ammo chain setup → yield → revert.
    Provides an isolated state with JBASE + JAMMO deployed and seeded.
    """
    snap = snapshot(anvil_url)
    set_balance(Web3.to_checksum_address(JOEY), _GAS_FUND, anvil_url)
    chain = _create_ammo_chain(w3, anvil_url)
    yield chain
    revert(snap, anvil_url)


class TestPhase2SpineRun:
    """
    Verify spine run mechanics on the deployed JBASE/JAMMO ammo chain.

    Each test is fully isolated via the `ammo_chain` fixture (snapshot+revert).

    Spine mechanic:
      1. FDIC.mint(N)  — pay N FED, receive N FDIC
      2. FDIC.Claim(JAMMO, N) — pay N JAMMO (Debenture=true), receive N FED

    In this test suite we use JBASE as the spine token (parent=FED) and
    JAMMO as the ammo (parent=JBASE, Debenture=true). The mechanics are
    identical to FDIC — JBASE holds FED, JAMMO is the spend token.
    """

    def test_fdic_mint_with_fed(self, w3, anvil_url, ammo_chain):
        """
        JBASE.mint(100e18) should consume FED and produce JBASE 1:1.
        FED balance decreases, JBASE balance increases by the mint amount.
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = ammo_chain["jbase_addr"]
        jbase = ammo_chain["jbase"]

        fed_before  = balance_of(w3, FED, joey)
        jbase_before = balance_of(w3, jbase_addr, joey)

        mint_amount = 10 * 10**18
        _approve(w3, FED, joey, jbase_addr, mint_amount * 2, anvil_url)

        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        tx = jbase.functions.mint(mint_amount).build_transaction({
            "from": joey,
            "gas": 200_000,
            "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)
        stop_impersonate(joey, anvil_url)

        fed_after   = balance_of(w3, FED, joey)
        jbase_after = balance_of(w3, jbase_addr, joey)

        assert fed_before - fed_after == mint_amount, (
            f"FED should decrease by {mint_amount}, delta={fed_before - fed_after}"
        )
        assert jbase_after - jbase_before == mint_amount, (
            f"JBASE should increase by {mint_amount}, delta={jbase_after - jbase_before}"
        )
        log.info("mint(100e18): FED -%.2f, JBASE +%.2f ✓",
                 (fed_before - fed_after) / 1e18,
                 (jbase_after - jbase_before) / 1e18)

    def test_fdic_claim_with_jammo(self, w3, anvil_url, ammo_chain):
        """
        JBASE.Claim(JAMMO, 50e18) should consume JAMMO (ammo) and release FED.
        JAMMO balance decreases, FED balance increases by the claim amount.
        Requires JAMMO Debenture=true (set at construction).
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = ammo_chain["jbase_addr"]
        jammo_addr = ammo_chain["jammo_addr"]
        jbase = ammo_chain["jbase"]

        # JBASE must hold FED to pay out — it does from the mint step in setup
        claim_amount = 30 * 10**18  # within JAMMO balance (50e18 minted in setup)

        fed_before   = balance_of(w3, FED, joey)
        jammo_before = balance_of(w3, jammo_addr, joey)

        _approve(w3, jammo_addr, joey, jbase_addr, claim_amount * 2, anvil_url)

        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        tx = jbase.functions.Claim(
            Web3.to_checksum_address(jammo_addr),
            claim_amount,
        ).build_transaction({
            "from": joey,
            "gas": 300_000,
            "gasPrice": w3.eth.gas_price,
        })
        _send_tx(w3, tx)
        stop_impersonate(joey, anvil_url)

        fed_after   = balance_of(w3, FED, joey)
        jammo_after = balance_of(w3, jammo_addr, joey)

        assert jammo_before - jammo_after == claim_amount, (
            f"JAMMO should decrease by {claim_amount}, delta={jammo_before - jammo_after}"
        )
        assert fed_after - fed_before == claim_amount, (
            f"FED should increase by {claim_amount}, delta={fed_after - fed_before}"
        )
        log.info("Claim(JAMMO, 30e18): JAMMO -%.2f, FED +%.2f ✓",
                 (jammo_before - jammo_after) / 1e18,
                 (fed_after - fed_before) / 1e18)

    def test_full_spine_cycle(self, w3, anvil_url, ammo_chain):
        """
        Full spine cycle: mint JBASE from FED, then Claim FED back with JAMMO.
        Net accounting: FED conserved (locked in JBASE), JAMMO consumed, JBASE gained.

        FED in Joey's wallet:  -mint_amount + claim_amount  (net neutral if equal)
        JBASE in Joey's wallet: +mint_amount
        JAMMO in Joey's wallet: -claim_amount
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = ammo_chain["jbase_addr"]
        jammo_addr = ammo_chain["jammo_addr"]
        jbase = ammo_chain["jbase"]

        cycle_amount = 20 * 10**18

        fed_start   = balance_of(w3, FED, joey)
        jbase_start = balance_of(w3, jbase_addr, joey)
        jammo_start = balance_of(w3, jammo_addr, joey)

        # Step 1: mint JBASE from FED
        _approve(w3, FED, joey, jbase_addr, cycle_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.mint(cycle_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        # Step 2: Claim FED back with JAMMO
        _approve(w3, jammo_addr, joey, jbase_addr, cycle_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.Claim(
            Web3.to_checksum_address(jammo_addr), cycle_amount
        ).build_transaction({
            "from": joey, "gas": 300_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        fed_end   = balance_of(w3, FED, joey)
        jbase_end = balance_of(w3, jbase_addr, joey)
        jammo_end = balance_of(w3, jammo_addr, joey)

        fed_delta   = fed_end - fed_start
        jbase_delta = jbase_end - jbase_start
        jammo_delta = jammo_end - jammo_start

        # FED is conserved (locked in JBASE then released): net ~0
        assert abs(fed_delta) < 10**15, (
            f"FED should be conserved after mint+claim, got delta={fed_delta / 1e18}"
        )
        # JBASE was gained (not spent in claim — Claim uses JAMMO as ammo)
        assert jbase_delta == cycle_amount, (
            f"JBASE should gain {cycle_amount}, delta={jbase_delta}"
        )
        # JAMMO was consumed
        assert jammo_delta == -cycle_amount, (
            f"JAMMO should decrease by {cycle_amount}, delta={jammo_delta}"
        )

        log.info(
            "Full spine cycle ✓ | FED Δ=%.4f, JBASE Δ=+%.2f, JAMMO Δ=%.2f",
            fed_delta / 1e18, jbase_delta / 1e18, jammo_delta / 1e18,
        )

    def test_multi_iteration_spine(self, w3, anvil_url, ammo_chain):
        """
        5 iterations of mint+claim. Verify cumulative accounting:
          - FED: net ~0 (locked and released each cycle)
          - JBASE: accumulates +cycle_amount per iteration
          - JAMMO: depletes -cycle_amount per iteration
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = ammo_chain["jbase_addr"]
        jammo_addr = ammo_chain["jammo_addr"]
        jbase = ammo_chain["jbase"]

        cycle_amount = 5 * 10**18
        iterations = 5

        fed_start   = balance_of(w3, FED, joey)
        jbase_start = balance_of(w3, jbase_addr, joey)
        jammo_start = balance_of(w3, jammo_addr, joey)

        assert jammo_start >= cycle_amount * iterations, (
            f"Not enough JAMMO for {iterations} iterations: have {jammo_start / 1e18}"
        )

        for i in range(iterations):
            # Mint
            _approve(w3, FED, joey, jbase_addr, cycle_amount * 2, anvil_url)
            impersonate(joey, anvil_url)
            set_balance(joey, _GAS_FUND, anvil_url)
            _send_tx(w3, jbase.functions.mint(cycle_amount).build_transaction({
                "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
            }))
            stop_impersonate(joey, anvil_url)

            # Claim
            _approve(w3, jammo_addr, joey, jbase_addr, cycle_amount * 2, anvil_url)
            impersonate(joey, anvil_url)
            set_balance(joey, _GAS_FUND, anvil_url)
            _send_tx(w3, jbase.functions.Claim(
                Web3.to_checksum_address(jammo_addr), cycle_amount
            ).build_transaction({
                "from": joey, "gas": 300_000, "gasPrice": w3.eth.gas_price,
            }))
            stop_impersonate(joey, anvil_url)

            log.debug("Iteration %d complete", i + 1)

        fed_end   = balance_of(w3, FED, joey)
        jbase_end = balance_of(w3, jbase_addr, joey)
        jammo_end = balance_of(w3, jammo_addr, joey)

        expected_jbase_gain = cycle_amount * iterations
        expected_jammo_loss = cycle_amount * iterations

        assert abs(fed_end - fed_start) < 10**15, (
            f"FED not conserved over {iterations} cycles, delta={(fed_end - fed_start) / 1e18}"
        )
        assert jbase_end - jbase_start == expected_jbase_gain, (
            f"JBASE gained {(jbase_end - jbase_start) / 1e18}, expected {expected_jbase_gain / 1e18}"
        )
        assert jammo_start - jammo_end == expected_jammo_loss, (
            f"JAMMO consumed {(jammo_start - jammo_end) / 1e18}, expected {expected_jammo_loss / 1e18}"
        )

        log.info(
            "%d iterations ✓ | JBASE +%.2f, JAMMO -%.2f, FED net %.4f",
            iterations,
            (jbase_end - jbase_start) / 1e18,
            (jammo_start - jammo_end) / 1e18,
            (fed_end - fed_start) / 1e18,
        )

    def test_claim_fails_without_registration(self, w3, anvil_url, ammo_chain):
        """
        Claim() with an unregistered contract address should revert.
        The V2Minter.TreasuryTokens check fails → FuckOff revert.
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = ammo_chain["jbase_addr"]
        jbase = ammo_chain["jbase"]

        # Use a random non-registered address as the ammo contract
        unregistered = "0x000000000000000000000000000000000000dEaD"
        claim_amount = 1 * 10**18

        _approve(w3, unregistered, joey, jbase_addr, claim_amount * 2, anvil_url)

        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        tx = jbase.functions.Claim(
            Web3.to_checksum_address(unregistered),
            claim_amount,
        ).build_transaction({
            "from": joey,
            "gas": 300_000,
            "gasPrice": w3.eth.gas_price,
        })

        # This should revert — simulate it first
        try:
            w3.eth.call(tx)
            pytest.fail("Expected revert for unregistered claim contract, but call succeeded")
        except Exception as e:
            log.info("Claim with unregistered address reverted as expected: %s", str(e)[:80])

        stop_impersonate(joey, anvil_url)


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 3 — Ammo Reload
#  Verify: JAMMO can be replenished via FED → JBASE → JAMMO reload path
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def depleted_ammo_chain(w3, anvil_url):
    """
    Like `ammo_chain` but with JAMMO nearly depleted (only 1e18 left).
    Used to test the reload path.
    """
    snap = snapshot(anvil_url)
    set_balance(Web3.to_checksum_address(JOEY), _GAS_FUND, anvil_url)
    chain = _create_ammo_chain(w3, anvil_url)

    # Deplete JAMMO: spend all but 1e18
    joey = Web3.to_checksum_address(JOEY)
    jbase_addr = chain["jbase_addr"]
    jammo_addr = chain["jammo_addr"]
    jbase = chain["jbase"]
    jammo_bal = balance_of(w3, jammo_addr, joey)
    deplete_amount = jammo_bal - 1 * 10**18  # leave 1e18

    if deplete_amount > 0:
        _approve(w3, jammo_addr, joey, jbase_addr, deplete_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.Claim(
            Web3.to_checksum_address(jammo_addr), deplete_amount
        ).build_transaction({
            "from": joey, "gas": 300_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

    log.info("JAMMO depleted to: %.4f", balance_of(w3, jammo_addr, joey) / 1e18)
    yield chain
    revert(snap, anvil_url)


class TestPhase3Reload:
    """
    Verify the JAMMO reload path: FED → JBASE.mint → JAMMO.mint → refilled.

    After the spine exhausts JAMMO ammo, the reload sequence restocks it:
      1. FED → JBASE.mint(N)    — acquire more JBASE
      2. JBASE → JAMMO.mint(N)  — convert JBASE to JAMMO ammo

    This restores the ability to Claim from JBASE again.
    """

    def test_jammo_is_depleted(self, w3, anvil_url, depleted_ammo_chain):
        """After depletion setup, JAMMO balance should be near zero."""
        joey = Web3.to_checksum_address(JOEY)
        jammo_addr = depleted_ammo_chain["jammo_addr"]
        bal = balance_of(w3, jammo_addr, joey)
        assert bal <= 2 * 10**18, (
            f"Expected JAMMO near-depleted (<= 2e18), got {bal / 1e18}"
        )
        log.info("JAMMO balance post-depletion: %.4f", bal / 1e18)

    def test_reload_jbase_from_fed(self, w3, anvil_url, depleted_ammo_chain):
        """
        FED → JBASE.mint(50e18) should produce 50 JBASE.
        Verifies the first leg of the reload path works.
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = depleted_ammo_chain["jbase_addr"]
        jbase = depleted_ammo_chain["jbase"]

        reload_amount = 50 * 10**18
        jbase_before = balance_of(w3, jbase_addr, joey)

        _approve(w3, FED, joey, jbase_addr, reload_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.mint(reload_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        jbase_after = balance_of(w3, jbase_addr, joey)
        assert jbase_after - jbase_before == reload_amount, (
            f"JBASE reload: expected +{reload_amount / 1e18}, got +{(jbase_after - jbase_before) / 1e18}"
        )
        log.info("Reload leg 1: FED → JBASE +%.2f ✓", (jbase_after - jbase_before) / 1e18)

    def test_reload_jammo_from_jbase(self, w3, anvil_url, depleted_ammo_chain):
        """
        FED → JBASE.mint → JAMMO.mint full reload path.
        After reload, JAMMO balance is replenished.
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = depleted_ammo_chain["jbase_addr"]
        jammo_addr = depleted_ammo_chain["jammo_addr"]
        jbase = depleted_ammo_chain["jbase"]
        jammo = depleted_ammo_chain["jammo"]

        reload_amount = 40 * 10**18
        jammo_before = balance_of(w3, jammo_addr, joey)

        # Step 1: FED → JBASE
        _approve(w3, FED, joey, jbase_addr, reload_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.mint(reload_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        # Step 2: JBASE → JAMMO
        _approve(w3, jbase_addr, joey, jammo_addr, reload_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jammo.functions.mint(reload_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        jammo_after = balance_of(w3, jammo_addr, joey)
        assert jammo_after - jammo_before == reload_amount, (
            f"JAMMO reload: expected +{reload_amount / 1e18}, got +{(jammo_after - jammo_before) / 1e18}"
        )
        log.info("Full reload path: FED → JBASE → JAMMO +%.2f ✓", (jammo_after - jammo_before) / 1e18)

    def test_full_reload_then_spine_cycle(self, w3, anvil_url, depleted_ammo_chain):
        """
        After depleting ammo: reload JAMMO, then run a full spine cycle.
        Confirms that the reload-spine loop is repeatable.
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = depleted_ammo_chain["jbase_addr"]
        jammo_addr = depleted_ammo_chain["jammo_addr"]
        jbase = depleted_ammo_chain["jbase"]
        jammo = depleted_ammo_chain["jammo"]

        reload_amount = 20 * 10**18

        # ── Reload ────────────────────────────────────────────────────────
        _approve(w3, FED, joey, jbase_addr, reload_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.mint(reload_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        _approve(w3, jbase_addr, joey, jammo_addr, reload_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jammo.functions.mint(reload_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        jammo_after_reload = balance_of(w3, jammo_addr, joey)
        assert jammo_after_reload >= reload_amount, "Reload failed — JAMMO not replenished"

        # ── Spine cycle ───────────────────────────────────────────────────
        cycle_amount = 10 * 10**18
        fed_before = balance_of(w3, FED, joey)

        # Mint JBASE from FED
        _approve(w3, FED, joey, jbase_addr, cycle_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.mint(cycle_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        # Claim FED with JAMMO
        _approve(w3, jammo_addr, joey, jbase_addr, cycle_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.Claim(
            Web3.to_checksum_address(jammo_addr), cycle_amount
        ).build_transaction({
            "from": joey, "gas": 300_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        fed_after = balance_of(w3, FED, joey)
        assert abs(fed_after - fed_before) < 10**15, "FED not conserved after reload+cycle"
        log.info("Reload → spine cycle ✓ | FED net=%.4f", (fed_after - fed_before) / 1e18)

    def test_reload_cost_accounting(self, w3, anvil_url, depleted_ammo_chain):
        """
        Reload cost accounting: verify that FED locked equals the reload amount.
        When Joey sends N FED → JBASE.mint(N), JBASE contract holds exactly N FED.
        """
        joey = Web3.to_checksum_address(JOEY)
        jbase_addr = depleted_ammo_chain["jbase_addr"]
        jbase = depleted_ammo_chain["jbase"]

        reload_amount = 30 * 10**18
        fed_in_jbase_before = balance_of(w3, FED, jbase_addr)

        _approve(w3, FED, joey, jbase_addr, reload_amount * 2, anvil_url)
        impersonate(joey, anvil_url)
        set_balance(joey, _GAS_FUND, anvil_url)
        _send_tx(w3, jbase.functions.mint(reload_amount).build_transaction({
            "from": joey, "gas": 200_000, "gasPrice": w3.eth.gas_price,
        }))
        stop_impersonate(joey, anvil_url)

        fed_in_jbase_after = balance_of(w3, FED, jbase_addr)
        locked = fed_in_jbase_after - fed_in_jbase_before

        assert locked == reload_amount, (
            f"FED locked in JBASE: expected {reload_amount / 1e18}, got {locked / 1e18}"
        )
        log.info(
            "Reload cost: %.2f FED locked in JBASE (1:1) ✓", locked / 1e18
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 4 — Tokenomics Analysis
#  Read-only economic analysis. These tests always pass — they output values.
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase4Tokenomics:
    """
    Economic analysis tests — always pass, output is the insight.
    No state modification, no assertions beyond basic sanity.

    These tests quantify the spine's profitability potential by reading
    DEX reserves, measuring real gas costs, and computing break-even.
    """

    def test_fdic_dex_price(self, w3, anvil_url):
        """
        Read FDIC/WPLS and FED/WPLS prices from PulseX V2.
        Reports implied FDIC price in PLS and FED price in PLS.
        """
        factory = Web3.to_checksum_address(FACTORY_V2)

        fdic_wpls_pair = get_pair_address(factory, FDIC, WPLS, w3)
        fed_wpls_pair  = get_pair_address(factory, FED, WPLS, w3)

        log.info("=== DEX Price Analysis ===")

        if fdic_wpls_pair:
            r0, r1, _ = read_reserves(fdic_wpls_pair, w3)
            t0, t1 = get_pair_tokens(fdic_wpls_pair, w3)
            r_fdic, r_wpls = (r0, r1) if t0.lower() == FDIC.lower() else (r1, r0)
            fdic_price_pls = r_wpls / r_fdic if r_fdic > 0 else 0
            log.info("FDIC/WPLS pair: %s", fdic_wpls_pair)
            log.info("  FDIC reserve: %.4f", r_fdic / 1e18)
            log.info("  WPLS reserve: %.4f", r_wpls / 1e18)
            log.info("  FDIC price:   %.6f PLS/FDIC", fdic_price_pls)
        else:
            fdic_price_pls = 0
            log.info("FDIC/WPLS pair: not found on V2")

        if fed_wpls_pair:
            r0, r1, _ = read_reserves(fed_wpls_pair, w3)
            t0, t1 = get_pair_tokens(fed_wpls_pair, w3)
            r_fed, r_wpls_fed = (r0, r1) if t0.lower() == FED.lower() else (r1, r0)
            fed_price_pls = r_wpls_fed / r_fed if r_fed > 0 else 0
            log.info("FED/WPLS pair: %s", fed_wpls_pair)
            log.info("  FED reserve:  %.4f", r_fed / 1e18)
            log.info("  WPLS reserve: %.4f", r_wpls_fed / 1e18)
            log.info("  FED price:    %.6f PLS/FED", fed_price_pls)
        else:
            fed_price_pls = 0
            log.info("FED/WPLS pair: not found on V2")

        # Sanity: prices should be non-negative
        assert fdic_price_pls >= 0
        assert fed_price_pls >= 0

        if fdic_price_pls > 0 and fed_price_pls > 0:
            ratio = fdic_price_pls / fed_price_pls
            log.info("FDIC/FED price ratio: %.4f (>1 means FDIC trades at premium to backing)", ratio)

    def test_gas_cost_per_cycle(self, w3, anvil_url):
        """
        Measure actual gas for one mint + one Claim cycle.
        Reports gas units and estimated PLS cost at current gas price.
        """
        snap = snapshot(anvil_url)
        try:
            set_balance(Web3.to_checksum_address(JOEY), _GAS_FUND, anvil_url)
            chain = _create_ammo_chain(w3, anvil_url)

            joey = Web3.to_checksum_address(JOEY)
            jbase_addr = chain["jbase_addr"]
            jammo_addr = chain["jammo_addr"]
            jbase = chain["jbase"]

            cycle_amount = 10 * 10**18
            gas_price = w3.eth.gas_price

            # ── Gas: mint ──────────────────────────────────────────────────
            _approve(w3, FED, joey, jbase_addr, cycle_amount * 2, anvil_url)
            impersonate(joey, anvil_url)
            set_balance(joey, _GAS_FUND, anvil_url)
            mint_gas = w3.eth.estimate_gas(
                jbase.functions.mint(cycle_amount).build_transaction({
                    "from": joey, "gas": 200_000, "gasPrice": gas_price,
                })
            )
            mint_receipt = _send_tx(w3, jbase.functions.mint(cycle_amount).build_transaction({
                "from": joey, "gas": 200_000, "gasPrice": gas_price,
            }))
            stop_impersonate(joey, anvil_url)

            # ── Gas: Claim ─────────────────────────────────────────────────
            _approve(w3, jammo_addr, joey, jbase_addr, cycle_amount * 2, anvil_url)
            impersonate(joey, anvil_url)
            set_balance(joey, _GAS_FUND, anvil_url)
            claim_gas = w3.eth.estimate_gas(
                jbase.functions.Claim(
                    Web3.to_checksum_address(jammo_addr), cycle_amount
                ).build_transaction({
                    "from": joey, "gas": 300_000, "gasPrice": gas_price,
                })
            )
            claim_receipt = _send_tx(w3, jbase.functions.Claim(
                Web3.to_checksum_address(jammo_addr), cycle_amount
            ).build_transaction({
                "from": joey, "gas": 300_000, "gasPrice": gas_price,
            }))
            stop_impersonate(joey, anvil_url)

            mint_gas_used  = mint_receipt["gasUsed"]
            claim_gas_used = claim_receipt["gasUsed"]
            total_gas_used = mint_gas_used + claim_gas_used
            pls_cost = (total_gas_used * gas_price) / 1e18

            log.info("=== Gas Cost Per Spine Cycle ===")
            log.info("  mint() gas used:  %d", mint_gas_used)
            log.info("  Claim() gas used: %d", claim_gas_used)
            log.info("  Total gas units:  %d", total_gas_used)
            log.info("  Gas price:        %d Beats", gas_price)
            log.info("  PLS cost/cycle:   %.6f PLS", pls_cost)
            log.info("  With 2.5x mult:   %.6f PLS", pls_cost * 2.5)

            assert total_gas_used > 0

        finally:
            revert(snap, anvil_url)

    def test_break_even_analysis(self, w3, anvil_url):
        """
        Compute spine profitability at various FED capital levels using the
        constant-product AMM formula. Reports break-even and projected yield.

        The spine extracts value when FDIC DEX price > FED locked cost per FDIC.
        """
        factory = Web3.to_checksum_address(FACTORY_V2)

        # Get current DEX prices
        fdic_wpls_pair = get_pair_address(factory, FDIC, WPLS, w3)
        fed_wpls_pair  = get_pair_address(factory, FED,  WPLS, w3)

        log.info("=== Break-Even Analysis ===")

        if not fdic_wpls_pair or not fed_wpls_pair:
            log.info("Skipping price analysis — DEX pairs not found on fork")
            # Still pass — this is an informational test
            return

        # FDIC price in WPLS
        r0, r1, _ = read_reserves(fdic_wpls_pair, w3)
        t0, _ = get_pair_tokens(fdic_wpls_pair, w3)
        r_fdic, r_wpls_fdic = (r0, r1) if t0.lower() == FDIC.lower() else (r1, r0)

        # FED price in WPLS
        r0f, r1f, _ = read_reserves(fed_wpls_pair, w3)
        t0f, _ = get_pair_tokens(fed_wpls_pair, w3)
        r_fed, r_wpls_fed = (r0f, r1f) if t0f.lower() == FED.lower() else (r1f, r0f)

        fdic_price_pls = r_wpls_fdic / r_fdic if r_fdic > 0 else 0
        fed_price_pls  = r_wpls_fed  / r_fed  if r_fed  > 0 else 0

        log.info("FDIC price: %.8f PLS", fdic_price_pls)
        log.info("FED price:  %.8f PLS", fed_price_pls)

        # Constant-product formula: amountOut = (amountIn * 997 * reserveOut) / (reserveIn * 1000 + amountIn * 997)
        def cp_out(amount_in: int, reserve_in: int, reserve_out: int) -> int:
            num = amount_in * 997 * reserve_out
            den = reserve_in * 1000 + amount_in * 997
            return num // den if den > 0 else 0

        # For various FED capital levels, compute: buy N FDIC via mint, sell FDIC on DEX
        # FED spent = N (1:1 mint)
        # FDIC received = N
        # WPLS out = cp_out(N, r_fdic, r_wpls_fdic)
        # Net = WPLS_out - (N * fed_price_pls * 1e18)
        log.info("\n  FED Capital | FDIC Minted | WPLS Out | FED Value In | Net (WPLS)")
        log.info("  " + "-" * 65)

        for fed_amount_eth in [100, 1_000, 10_000, 100_000]:
            fed_amount_wei = int(fed_amount_eth * 1e18)
            # Simulate selling N FDIC on DEX
            fdic_out = fed_amount_wei  # 1:1 mint
            wpls_out = cp_out(fdic_out, r_fdic, r_wpls_fdic)
            fed_val_wpls = int(fed_amount_wei * fed_price_pls)  # approximate cost in WPLS
            net_wpls = wpls_out - fed_val_wpls
            net_pls  = net_wpls / 1e18

            log.info(
                "  %10.0f FED | %11.2f | %8.2f | %12.2f | %+.2f PLS",
                fed_amount_eth,
                fdic_out / 1e18,
                wpls_out / 1e18,
                fed_val_wpls / 1e18,
                net_pls,
            )

        # Price impact at 1,000 FED
        test_amount = int(1_000 * 1e18)
        wpls_for_1k = cp_out(test_amount, r_fdic, r_wpls_fdic)
        theoretical = test_amount * fdic_price_pls
        impact_pct = (1 - wpls_for_1k / theoretical) * 100 if theoretical > 0 else 0
        log.info("\n  Price impact @ 1K FED: %.2f%%", impact_pct)

        # Profitability condition: FDIC_sell_price > FED_buy_price
        if fdic_price_pls > 0 and fed_price_pls > 0:
            premium_pct = ((fdic_price_pls - fed_price_pls) / fed_price_pls) * 100
            log.info("  FDIC premium over FED: %+.2f%%", premium_pct)
            log.info("  Profitable: %s", "YES" if premium_pct > 0 else "NO (FDIC at discount to FED)")

        assert fdic_price_pls >= 0
        assert fed_price_pls >= 0
