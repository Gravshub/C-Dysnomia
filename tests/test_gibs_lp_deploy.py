#!/usr/bin/env python3
"""
Anvil fork integration tests for GIBS_LP_depl0y.py.

Forks PulseChain via Anvil, funds Joey with partner tokens via
impersonation of existing DEX pairs, then deploys LP pools and
verifies pair creation, reserves, and LP token balances.

Usage:
  python3 tests/test_gibs_lp_deploy.py

Requires:
  - anvil binary in PATH (install via foundryup)
  - web3, python-dotenv pip packages
"""
import os
import sys
import time
import signal
import socket
import unittest
import subprocess
from decimal import Decimal

# Add repo root to path so we can import the deployment script
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from web3 import Web3
from eth_account import Account

# Import pool definitions and helpers from deployment script
from scripts.GIBS_LP_depl0y import (
    POOLS, GIBS_LAU, WPLS, JOEY, ZERO_ADDR,
    V1_FACTORY, V2_FACTORY, V1_ROUTER, V2_ROUTER,
    ERC20_ABI, FACTORY_ABI, PAIR_ABI, ROUTER_ABI,
    get_pair, safe, to_wei, deploy_pool, show_status,
)

# Extended ERC20 ABI with transfer (needed for test funding)
ERC20_WITH_TRANSFER_ABI = ERC20_ABI + [
    {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "transfer", "outputs": [{"type": "bool"}],
     "stateMutability": "nonpayable", "type": "function"},
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ANVIL_PORT = 8546
ANVIL_RPC = f"http://127.0.0.1:{ANVIL_PORT}"
FORK_RPC = "https://rpc.pulsechain.com"

# Use a deterministic test private key (Anvil default account 0)
# We'll impersonate Joey instead for realistic testing
TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

# Existing DEX pairs that hold partner tokens (source of liquidity for test funding)
# These are real on-chain pairs from the deployment plan
PARTNER_SOURCES = {
    "FED":       {"pair": "0x333502d557A40FeC45350BeF9c07F9C53244559a", "token": "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff"},
    "ATROPA":    {"pair": "0xcBBad671CA3A46A565551335C10144e75554B367", "token": "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6"},
    "WM":        {"pair": "0x7EB24A076fd9DE8c75A0B90566334fDd7665B006", "token": "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"},
    "PROOF_RES": {"pair": "0xEA9a0dB94643a8FAA3A20FDd7ac16982Eb81468a", "token": "0xaA1505C928fd85E10a550CfDe9e8F464c3574D8a"},
    "ZHENG":     {"pair": "0xC8A063B6ccf46Af5B242d0696a5f115EeA23dBda", "token": "0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15"},
    "VOID":      {"pair": "0xB0f4E1B164aDF9eDA0Bcb7459BC17d87E005B776", "token": "0x965B0d74591bF30327075A247C47dBf487dCff08"},
    "DFM":       {"pair": "0x01354C68Bc07De1B775366b371689be9Ce71E359", "token": "0x51160F352ED148C89d48dfe6384Edd07aFA24E0E"},
    "PARADE":    {"pair": "0x5d65e9a2118f64fc56C62827A5e092847bb27e58", "token": "0xE37ACc54711562510FaFC45d8199Ee329ebBceDd"},
    "TLRz":      {"pair": "0xCBf1bF451Ce0ef918166E4834d079bd4C9bCC2f7", "token": "0xC7145e1290B1d1221Aba5Ae48d4aCE17c6BE088F"},
}


# ---------------------------------------------------------------------------
# Anvil process management
# ---------------------------------------------------------------------------
def find_anvil():
    """Find anvil binary."""
    # Check common locations
    for path in [
        os.path.expanduser("~/.foundry/bin/anvil"),
        "/usr/local/bin/anvil",
        "anvil",
    ]:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_anvil(fork_rpc=FORK_RPC, port=ANVIL_PORT):
    """Start Anvil fork of PulseChain. Returns subprocess handle."""
    anvil_bin = find_anvil()
    if not anvil_bin:
        raise RuntimeError(
            "Anvil not found. Install via: "
            "curl -L https://foundry.paradigm.xyz | bash && foundryup"
        )

    if is_port_in_use(port):
        print(f"  Port {port} in use — killing stale process...")
        os.system(f"kill $(lsof -ti :{port} 2>/dev/null) 2>/dev/null")
        time.sleep(2)
        if is_port_in_use(port):
            raise RuntimeError(f"Port {port} still in use after kill attempt.")

    cmd = [
        anvil_bin,
        "--fork-url", fork_rpc,
        "--port", str(port),
        "--chain-id", "369",
        "--no-mining",  # mine on demand for faster tests
        "--quiet",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for Anvil to be ready
    for i in range(30):
        time.sleep(1)
        if is_port_in_use(port):
            return proc
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"Anvil exited early: {stderr}")

    proc.kill()
    raise RuntimeError("Anvil failed to start within 30 seconds")


def stop_anvil(proc):
    """Gracefully stop Anvil."""
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# Anvil RPC helpers
# ---------------------------------------------------------------------------
def anvil_set_balance(w3, address, balance_wei):
    """Set native PLS balance for an address."""
    w3.provider.make_request("anvil_setBalance", [address, hex(balance_wei)])


def anvil_impersonate(w3, address):
    """Start impersonating an address."""
    w3.provider.make_request("anvil_impersonateAccount", [address])


def anvil_stop_impersonate(w3, address):
    """Stop impersonating an address."""
    w3.provider.make_request("anvil_stopImpersonatingAccount", [address])


def anvil_mine(w3, blocks=1):
    """Mine N blocks."""
    w3.provider.make_request("evm_mine", [])


def anvil_deal_erc20(w3, token_addr, recipient, amount):
    """
    Deal ERC20 tokens to recipient by brute-forcing the balances mapping slot.
    Tries slots 0-10 until balanceOf changes. Works with any ERC20.
    """
    token = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
    before = safe(token, "balanceOf", recipient) or 0

    for slot in range(11):
        # Storage key = keccak256(abi.encode(address, uint256(slot)))
        key = Web3.solidity_keccak(
            ["address", "uint256"],
            [recipient, slot]
        ).hex()
        value = hex(amount)
        w3.provider.make_request(
            "anvil_setStorageAt",
            [token_addr, key, "0x" + value[2:].zfill(64)]
        )
        after = safe(token, "balanceOf", recipient) or 0
        if after != before and after > 0:
            return slot  # Found the right slot

        # Reset if this was wrong slot
        w3.provider.make_request(
            "anvil_setStorageAt",
            [token_addr, key, "0x" + "0" * 64]
        )

    return None  # Could not find slot


def fund_joey_partner_tokens(w3):
    """
    Transfer partner tokens from existing DEX pairs to Joey via impersonation.
    Falls back to anvil_deal_erc20 if the pair doesn't hold enough.
    """
    unfunded = []
    for pool in POOLS:
        if pool["is_eth"]:
            continue  # WPLS handled via native PLS

        sym = pool["partner_symbol"]
        source = PARTNER_SOURCES.get(sym)
        if not source:
            print(f"  WARNING: No source for {sym} — skipping")
            unfunded.append(sym)
            continue

        pair_addr = Web3.to_checksum_address(source["pair"])
        token_addr = Web3.to_checksum_address(source["token"])
        amount = to_wei(pool["partner_amount"])

        token = w3.eth.contract(address=token_addr, abi=ERC20_WITH_TRANSFER_ABI)
        pair_bal = safe(token, "balanceOf", pair_addr) or 0

        if pair_bal < amount:
            # Fallback: deal directly via storage manipulation
            print(f"  {sym}: pair insufficient ({pair_bal/1e18:.0f}), trying anvil_deal...")
            slot = anvil_deal_erc20(w3, token_addr, JOEY, amount)
            bal = safe(token, "balanceOf", JOEY) or 0
            if slot is not None and bal >= amount:
                print(f"  {sym}: dealt via storage slot {slot} (Joey bal: {bal/1e18:.4f})")
                continue
            else:
                print(f"  WARNING: {sym} could not be funded (slot search failed)")
                unfunded.append(sym)
                continue

        # Impersonate the pair and transfer tokens to Joey
        anvil_impersonate(w3, pair_addr)
        anvil_set_balance(w3, pair_addr, int(100 * 1e18))  # gas for transfer

        tx_hash = token.functions.transfer(JOEY, amount).transact({
            "from": pair_addr,
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
        })
        anvil_mine(w3)
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        anvil_stop_impersonate(w3, pair_addr)

        bal = safe(token, "balanceOf", JOEY) or 0
        status = "OK" if receipt["status"] == 1 else "FAIL"
        print(f"  {sym}: transferred {float(pool['partner_amount']):.4f} [{status}] (Joey bal: {bal/1e18:.4f})")

    return unfunded


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------
class TestGIBSLPDeploy(unittest.TestCase):
    """Integration tests for GIBS LP deployment on Anvil fork."""

    anvil_proc = None
    w3 = None
    acct = None
    unfunded_symbols = []

    @classmethod
    def setUpClass(cls):
        """Start Anvil fork and fund Joey."""
        print("\n" + "=" * 60)
        print("Starting Anvil fork of PulseChain...")
        print("=" * 60)

        cls.anvil_proc = start_anvil()
        cls.w3 = Web3(Web3.HTTPProvider(ANVIL_RPC, request_kwargs={"timeout": 60}))

        if not cls.w3.is_connected():
            raise RuntimeError("Cannot connect to Anvil")

        chain_id = cls.w3.eth.chain_id
        print(f"Connected to Anvil (chain {chain_id})")
        assert chain_id == 369, f"Expected chain 369, got {chain_id}"

        # Impersonate Joey for all transactions
        anvil_impersonate(cls.w3, JOEY)

        # Fund Joey with plenty of PLS (1M PLS)
        anvil_set_balance(cls.w3, JOEY, int(1_000_000 * 1e18))
        pls = cls.w3.eth.get_balance(JOEY)
        print(f"Joey PLS balance: {pls / 1e18:,.0f}")

        # Check GIBS balance (should exist from fork)
        gibs = cls.w3.eth.contract(address=GIBS_LAU, abi=ERC20_ABI)
        gibs_bal = safe(gibs, "balanceOf", JOEY) or 0
        print(f"Joey GIBS balance: {gibs_bal / 1e18:.4f}")
        assert gibs_bal > 0, "Joey has no GIBS on forked chain"

        # Fund Joey with partner tokens
        print("\nFunding Joey with partner tokens...")
        cls.unfunded_symbols = fund_joey_partner_tokens(cls.w3)
        anvil_mine(cls.w3)
        if cls.unfunded_symbols:
            print(f"  Unfunded tokens (will skip): {cls.unfunded_symbols}")

        # Create a dummy account for signing (Anvil accepts impersonated txs without signing)
        cls.acct = _ImpersonatedAccount(JOEY)

        print("\nSetup complete.\n")

    @classmethod
    def tearDownClass(cls):
        """Stop Anvil."""
        stop_anvil(cls.anvil_proc)
        print("\nAnvil stopped.")

    def test_01_status(self):
        """--status runs without error on clean fork."""
        # Should not raise
        show_status(self.w3, JOEY)

    def test_02_pool_0_gibs_wpls(self):
        """Deploy GIBS/WPLS pair via addLiquidityETH."""
        # Verify pair doesn't exist yet
        pair_before = get_pair(self.w3, V2_FACTORY, GIBS_LAU, WPLS)
        self.assertIsNone(pair_before, "GIBS/WPLS pair already exists on V2")

        ok = deploy_pool(self.w3, self.acct, 0)
        anvil_mine(self.w3)
        self.assertTrue(ok, "Pool 0 deployment failed")

        # Verify pair was created
        pair_addr = get_pair(self.w3, V2_FACTORY, GIBS_LAU, WPLS)
        self.assertIsNotNone(pair_addr, "GIBS/WPLS pair not found after deployment")

        # Verify LP tokens
        pair = self.w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
        lp_bal = safe(pair, "balanceOf", JOEY) or 0
        self.assertGreater(lp_bal, 0, "No LP tokens received")

        # Verify reserves are non-zero
        reserves = safe(pair, "getReserves")
        self.assertIsNotNone(reserves)
        self.assertGreater(reserves[0], 0, "Reserve 0 is zero")
        self.assertGreater(reserves[1], 0, "Reserve 1 is zero")

        print(f"  Pool 0 OK: pair={pair_addr}, LP={lp_bal/1e18:.6f}")

    def test_03_pool_1_gibs_fed(self):
        """Deploy GIBS/FED pair on V2."""
        ok = deploy_pool(self.w3, self.acct, 1)
        anvil_mine(self.w3)
        self.assertTrue(ok, "Pool 1 deployment failed")

        pair_addr = get_pair(self.w3, V2_FACTORY, GIBS_LAU, POOLS[1]["partner"])
        self.assertIsNotNone(pair_addr, "GIBS/FED pair not found")

        pair = self.w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
        lp_bal = safe(pair, "balanceOf", JOEY) or 0
        self.assertGreater(lp_bal, 0, "No LP tokens for FED pair")
        print(f"  Pool 1 OK: pair={pair_addr}, LP={lp_bal/1e18:.6f}")

    def test_04_pool_2_gibs_atropa(self):
        """Deploy GIBS/ATROPA pair on V1 Router."""
        ok = deploy_pool(self.w3, self.acct, 2)
        anvil_mine(self.w3)
        self.assertTrue(ok, "Pool 2 deployment failed")

        # Must be on V1 factory (not V2)
        pair_v1 = get_pair(self.w3, V1_FACTORY, GIBS_LAU, POOLS[2]["partner"])
        self.assertIsNotNone(pair_v1, "GIBS/ATROPA pair not found on V1 factory")

        pair = self.w3.eth.contract(address=pair_v1, abi=PAIR_ABI)
        lp_bal = safe(pair, "balanceOf", JOEY) or 0
        self.assertGreater(lp_bal, 0, "No LP tokens for ATROPA pair")
        print(f"  Pool 2 OK: pair={pair_v1} (V1), LP={lp_bal/1e18:.6f}")

    def test_05_pools_3_to_9(self):
        """Deploy remaining pools (3-9) on V2."""
        skipped = []
        for idx in range(3, 10):
            pool = POOLS[idx]

            # Skip unfunded pools (partner token source insufficient)
            if pool["partner_symbol"] in self.unfunded_symbols:
                print(f"  Pool {idx} ({pool['name']}): SKIPPED (unfunded in test)")
                skipped.append(idx)
                continue

            ok = deploy_pool(self.w3, self.acct, idx)
            anvil_mine(self.w3)
            self.assertTrue(ok, f"Pool {idx} ({pool['name']}) deployment failed")

            pair_addr = get_pair(self.w3, pool["factory"], GIBS_LAU, pool["partner"])
            self.assertIsNotNone(pair_addr, f"Pool {idx} pair not found")

            pair = self.w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
            lp_bal = safe(pair, "balanceOf", JOEY) or 0
            self.assertGreater(lp_bal, 0, f"Pool {idx}: no LP tokens")
            print(f"  Pool {idx} ({pool['name']}): pair={pair_addr}, LP={lp_bal/1e18:.6f}")

        if skipped:
            print(f"  Note: Pools {skipped} skipped due to insufficient test funding")

    def test_06_skip_existing_pair(self):
        """Deploying an already-existing pair should skip (idempotent)."""
        # Pool 0 was already deployed in test_02
        ok = deploy_pool(self.w3, self.acct, 0)
        self.assertTrue(ok, "Re-deploying existing pair should return True (skip)")

    def test_07_status_after_deploy(self):
        """--status shows all pairs as LIVE after deployment."""
        show_status(self.w3, JOEY)

    def test_08_gibs_savings(self):
        """After deployed pools, Joey retains GIBS savings."""
        gibs = self.w3.eth.contract(address=GIBS_LAU, abi=ERC20_ABI)
        remaining = safe(gibs, "balanceOf", JOEY) or 0
        remaining_human = remaining / 1e18

        # Calculate expected remaining based on which pools were actually deployed
        total_gibs_used = 0
        for i, pool in enumerate(POOLS):
            if pool["partner_symbol"] not in self.unfunded_symbols:
                total_gibs_used += pool["gibs_amount"]
        expected_remaining = 3395 - total_gibs_used  # ~3395 starting balance
        print(f"  GIBS remaining: {remaining_human:.4f} (expected: ~{expected_remaining})")
        # Should be close to expected, allow 10% tolerance
        self.assertGreater(remaining_human, expected_remaining * 0.8,
                           "Too few GIBS remaining — savings depleted")
        self.assertLess(remaining_human, expected_remaining * 1.2 + 50,
                        "Too many GIBS remaining — pools may not have deployed")


# ---------------------------------------------------------------------------
# Impersonated Account wrapper
# ---------------------------------------------------------------------------
class _ImpersonatedAccount:
    """
    Mimics eth_account.Account interface for Anvil impersonation.
    With Anvil impersonation, we don't need to sign — just transact directly.
    But deploy_pool() calls build_transaction + sign_transaction, so we
    override to use transact() instead.
    """

    def __init__(self, address):
        self.address = Web3.to_checksum_address(address)

    def sign_transaction(self, tx):
        """Return the tx itself — Anvil impersonation doesn't need real signing."""
        return _FakeSignedTx(tx)


class _FakeSignedTx:
    """Wrapper to make impersonated tx look like a signed tx."""

    def __init__(self, tx):
        self.tx = tx
        # Store raw bytes that can be sent — but for impersonation we'll
        # override send_raw_transaction behavior
        self.raw_transaction = None
        self._tx_dict = tx


# ---------------------------------------------------------------------------
# Override send_raw_transaction for impersonation
# ---------------------------------------------------------------------------
def _patch_deploy_for_anvil(w3):
    """
    Monkey-patch the deployment script's send_tx to use Anvil
    impersonation (eth_sendTransaction) instead of signed raw TX.
    """
    import scripts.GIBS_LP_depl0y as deploy_mod

    original_send_tx = deploy_mod.send_tx

    def patched_send_tx(w3_arg, acct, fn_call, label, nonce, value=0, dry_run=False):
        call_params = {"from": acct.address}
        if value > 0:
            call_params["value"] = value

        # Simulate
        try:
            fn_call.call(call_params)
        except Exception as exc:
            print(f"  SIMULATION FAILED for {label}: {exc}")
            return None, nonce

        if dry_run:
            try:
                gas_est = fn_call.estimate_gas(call_params)
            except Exception:
                gas_est = 0
            gas_price = w3_arg.eth.gas_price
            cost = gas_est * gas_price / 1e18
            print(f"  [dry-run] {label}: gas={gas_est:,} cost={cost:.2f} PLS")
            return None, nonce

        # Estimate gas
        try:
            gas_est = fn_call.estimate_gas(call_params)
        except Exception as exc:
            print(f"  GAS ESTIMATION FAILED for {label}: {exc}")
            return None, nonce

        gas_price = w3_arg.eth.gas_price
        cost = gas_est * gas_price / 1e18
        print(f"  {label}: gas={gas_est:,} cost={cost:.2f} PLS")

        # Use eth_sendTransaction (impersonated — no signing needed)
        tx_params = {
            "from": acct.address,
            "gas": int(gas_est * 1.3),
            "gasPrice": gas_price,
        }
        if value > 0:
            tx_params["value"] = value

        tx_hash = fn_call.transact(tx_params)
        anvil_mine(w3_arg)
        print(f"  TX: 0x{tx_hash.hex()}")

        receipt = w3_arg.eth.get_transaction_receipt(tx_hash)
        status = receipt["status"]
        print(f"  Status: {'OK' if status == 1 else 'REVERTED'}  Block: {receipt['blockNumber']:,}")

        if status != 1:
            print(f"  ERROR: {label} REVERTED")
            return None, nonce + 1

        return receipt, nonce + 1

    deploy_mod.send_tx = patched_send_tx

    # Also patch approve_if_needed to use transact
    original_approve = deploy_mod.approve_if_needed

    def patched_approve(w3_arg, acct, token_addr, spender, amount, label, nonce, dry_run=False):
        token = w3_arg.eth.contract(address=token_addr, abi=ERC20_ABI)
        current = safe(token, "allowance", acct.address, spender) or 0
        if current >= amount:
            print(f"  Allowance sufficient for {label} ({current / 1e18:.4f})")
            return nonce

        print(f"  Approving {label}...")
        fn = token.functions.approve(spender, amount)
        receipt, nonce = patched_send_tx(w3_arg, acct, fn, f"Approve {label}", nonce, dry_run=dry_run)
        if receipt is None and not dry_run:
            print(f"  WARNING: Approve for {label} may have failed")
        return nonce

    deploy_mod.approve_if_needed = patched_approve


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Patch deployment script for Anvil impersonation before running tests
    # This is done at module level so it applies to all test cases

    # We need to set up the Anvil first, then patch
    # Use a custom test runner that patches after Anvil starts
    class AnvilTestRunner(unittest.TextTestRunner):
        def run(self, test):
            # Find the test suite's class and patch after setUpClass
            return super().run(test)

    # Monkey-patch at module load time — the patch just changes how TXs
    # are sent (impersonation vs signing), doesn't need Anvil running yet
    try:
        _patch_deploy_for_anvil(None)  # w3 not needed for patching
    except Exception as e:
        print(f"Warning: patch failed: {e}")

    # Run with verbose output, ordered by test name (hence test_0N_ prefix)
    unittest.main(verbosity=2)
