#!/usr/bin/env python3
"""
Deploy TGSv5 (TreasuryGameSharkv5) to PulseChain.

TGSv5 is a self-contained WM batch-minter contract. It has no external imports
and calls WM.RHO() up to 100 times per tx, minting 1 WM per call to tx.origin.

Usage:
  python scripts/tx_deploy_tgsv5.py --dry-run      # compile only, no deploy
  python scripts/tx_deploy_tgsv5.py --update-env   # deploy + write TGSV5_ADDRESS to .env
  python scripts/tx_deploy_tgsv5.py                # deploy only (print address)
"""
import os
import sys
import subprocess
import argparse
import re
from pathlib import Path

# ── Auto-install py-solc-x if missing ──────────────────────────────────────
try:
    from solcx import compile_source, install_solc, get_installed_solc_versions
except ImportError:
    print("py-solc-x not found — installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "py-solc-x", "-q"])
    from solcx import compile_source, install_solc, get_installed_solc_versions

from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

# ── Constants ───────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
CONTRACT    = REPO_ROOT / "contracts" / "TGSv5.sol"
ENV_FILE    = REPO_ROOT / ".env"

SUBMIT_RPC  = "https://rpc.pulsechain.com"
READ_RPC    = "https://rpc.pulsechainstats.com"
CHAIN_ID    = 369
SOLC_VER    = "0.8.21"
GAS_MULT    = 1.3

JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# ABI for post-deploy verification
TGSV5_ABI = [
    {"inputs": [], "name": "owner",
     "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "authorized",
     "outputs": [{"type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "paused",
     "outputs": [{"type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "wmBalance",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "WM_CONTRACT",
     "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "MAX_MINT_COUNT",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# ── Helpers ─────────────────────────────────────────────────────────────────

def ensure_solc():
    """Install solc 0.8.21 if not already cached in ~/.solcx/."""
    installed = get_installed_solc_versions()
    version_strs = [str(v) for v in installed]
    if SOLC_VER not in version_strs:
        print(f"  Downloading solc {SOLC_VER} (one-time ~60MB)...")
        install_solc(SOLC_VER)
        print(f"  solc {SOLC_VER} installed.")
    else:
        print(f"  solc {SOLC_VER} already cached.")


def compile_contract(source: str) -> tuple[list, str]:
    """Compile TGSv5.sol → (abi, bytecode)."""
    print(f"\n[1/6] Compiling TGSv5.sol with solc {SOLC_VER} (optimize=200)...")
    compiled = compile_source(
        source,
        output_values=["abi", "bin"],
        solc_version=SOLC_VER,
        optimize=True,
        optimize_runs=200,
    )
    # compile_source keys are like '<stdin>:TGSv5'
    contract_key = next(k for k in compiled if k.endswith(":TGSv5"))
    abi      = compiled[contract_key]["abi"]
    bytecode = compiled[contract_key]["bin"]
    print(f"  Bytecode size: {len(bytecode) // 2:,} bytes  ABI entries: {len(abi)}")
    return abi, bytecode


def update_env_file(address: str):
    """Write or replace TGSV5_ADDRESS= line in .env."""
    key = "TGSV5_ADDRESS"
    line = f"{key}={address}\n"
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
        if re.search(rf"^{key}=", content, re.MULTILINE):
            content = re.sub(rf"^{key}=.*$", line.rstrip(), content, flags=re.MULTILINE)
            ENV_FILE.write_text(content)
            print(f"  Updated existing {key} in .env")
        else:
            with open(ENV_FILE, "a") as f:
                f.write(line)
            print(f"  Appended {key} to .env")
    else:
        ENV_FILE.write_text(line)
        print(f"  Created .env with {key}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Deploy TGSv5 to PulseChain")
    parser.add_argument("--dry-run",    action="store_true", help="Compile only — no deploy")
    parser.add_argument("--update-env", action="store_true", help="Write TGSV5_ADDRESS to .env after deploy")
    args = parser.parse_args()

    print("=" * 60)
    print("TGSv5 Deploy — TreasuryGameSharkv5 / WM Batch Minter")
    print("=" * 60)

    # ── Step 1: Read source ──────────────────────────────────────────────────
    if not CONTRACT.exists():
        print(f"ERROR: {CONTRACT} not found.")
        sys.exit(1)
    source = CONTRACT.read_text()
    print(f"\n[0/6] Contract source: {CONTRACT}")

    # ── Step 2: Install solc + compile ──────────────────────────────────────
    ensure_solc()
    abi, bytecode = compile_contract(source)

    if args.dry_run:
        print("\n[DRY-RUN] Compilation successful. No deploy. Exiting.")
        print(f"  ABI functions: {[e['name'] for e in abi if e['type']=='function']}")
        return

    # ── Step 3: Load wallet ──────────────────────────────────────────────────
    print("\n[2/6] Loading wallet...")
    load_dotenv(ENV_FILE)
    pkey = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
    if not pkey:
        print("ERROR: DYSNOMIA_PRIVATE_KEY not set. Run: source .env")
        sys.exit(1)
    account = Account.from_key(pkey)
    if account.address.lower() != JOEY_WALLET.lower():
        print(f"ERROR: Key resolves to {account.address}, expected {JOEY_WALLET}")
        sys.exit(1)
    print(f"  Wallet: {account.address} ✓")

    # ── Step 4: Connect ──────────────────────────────────────────────────────
    print(f"\n[3/6] Connecting to {SUBMIT_RPC}...")
    w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print("ERROR: Cannot connect to RPC.")
        sys.exit(1)
    block = w3.eth.block_number
    pls_bal = w3.eth.get_balance(JOEY_WALLET)
    print(f"  Block: {block:,}   PLS balance: {pls_bal / 1e18:.2f}")

    # ── Step 5: Estimate gas + deploy ───────────────────────────────────────
    print(f"\n[4/6] Estimating deploy gas...")
    factory  = w3.eth.contract(abi=abi, bytecode=bytecode)
    constructor = factory.constructor()
    gas_price = w3.eth.gas_price
    gas_est   = constructor.estimate_gas({"from": JOEY_WALLET})
    gas_limit = int(gas_est * GAS_MULT)
    cost_pls  = gas_limit * gas_price / 1e18
    nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
    print(f"  Gas est: {gas_est:,}  Limit: {gas_limit:,}  Gas price: {gas_price/1e9:.2f} Gwei")
    print(f"  Max cost: {cost_pls:.4f} PLS   Nonce: {nonce}")

    print(f"\n[5/6] Deploying TGSv5...")
    tx = constructor.build_transaction({
        "from":     JOEY_WALLET,
        "nonce":    nonce,
        "gas":      gas_limit,
        "gasPrice": gas_price,
        "chainId":  CHAIN_ID,
    })
    signed   = account.sign_transaction(tx)
    tx_hash  = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: 0x{tx_hash.hex()}")
    print("  Waiting for confirmation (up to 5 min)...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    status  = receipt["status"]
    used    = receipt["gasUsed"]
    blk     = receipt["blockNumber"]
    address = receipt["contractAddress"]

    print(f"  Block: {blk:,}  Status: {status}  Gas used: {used:,}  Cost: {used * gas_price / 1e18:.4f} PLS")

    if status != 1:
        print("ERROR: Deploy transaction FAILED (status=0).")
        sys.exit(1)

    print(f"\n  ✓ TGSv5 deployed at: {address}")

    # ── Step 6: Verify ───────────────────────────────────────────────────────
    print(f"\n[6/6] Verifying contract state...")
    tgsv5 = w3.eth.contract(address=address, abi=TGSV5_ABI)

    contract_owner = tgsv5.functions.owner().call()
    is_authorized  = tgsv5.functions.authorized(JOEY_WALLET).call()
    is_paused      = tgsv5.functions.paused().call()
    wm_contract    = tgsv5.functions.WM_CONTRACT().call()
    max_count      = tgsv5.functions.MAX_MINT_COUNT().call()

    print(f"  owner()              = {contract_owner}")
    print(f"  authorized(Joey)     = {is_authorized}")
    print(f"  paused()             = {is_paused}")
    print(f"  WM_CONTRACT          = {wm_contract}")
    print(f"  MAX_MINT_COUNT       = {max_count}")

    assert contract_owner.lower() == JOEY_WALLET.lower(), "owner() mismatch!"
    assert is_authorized, "authorized(Joey) is False!"
    assert not is_paused, "paused() is True — unexpected!"
    assert max_count == 100, f"MAX_MINT_COUNT={max_count}, expected 100"
    print("  All assertions passed ✓")

    # ── Step 7: Update .env ──────────────────────────────────────────────────
    if args.update_env:
        print(f"\n[+] Writing TGSV5_ADDRESS to .env...")
        update_env_file(address)
        print(f"  TGSV5_ADDRESS={address}")

    print("\n" + "=" * 60)
    print(f"DEPLOY COMPLETE")
    print(f"  Address:  {address}")
    print(f"  TX:       0x{tx_hash.hex()}")
    print(f"  Block:    {blk:,}")
    print("=" * 60)

    print("\nNext steps:")
    if not args.update_env:
        print(f"  export TGSV5_ADDRESS={address}")
    print(f"  python agent/wm_minter.py --price-check")
    print(f"  python scripts/Joystick/bot.py --status")


if __name__ == "__main__":
    main()
