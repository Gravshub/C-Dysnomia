#!/usr/bin/env python3
"""
Deploy TGSv8 (TreasurySharkV8) to PulseChain.

TGSv8 = TGSv7 + mintWM(count). Self-contained single-file deploy.
Constructor takes 8 addresses: v4, v3, mv, wpls, routerV1, routerV2, factoryV1, factoryV2.

Usage:
  python scripts/deploy_tgsv8.py --dry-run        # compile only, print size
  python scripts/deploy_tgsv8.py --update-env      # deploy + write TGSV8_ADDRESS to .env
  python scripts/deploy_tgsv8.py                   # deploy only (print address)
"""
import os
import sys
import subprocess
import argparse
import re
import json
from pathlib import Path

# ── Auto-install py-solc-x if missing ──────────────────────────────────────
try:
    from solcx import compile_standard, install_solc, get_installed_solc_versions
except ImportError:
    print("py-solc-x not found — installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "py-solc-x", "-q"])
    from solcx import compile_standard, install_solc, get_installed_solc_versions

from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

# ── Constants ───────────────────────────────────────────────────────────────
REPO_ROOT     = Path(__file__).resolve().parent.parent
CONTRACT_FILE = REPO_ROOT / "contracts" / "TGSv8.sol"
ENV_FILE      = REPO_ROOT / ".env"
ABI_OUT       = REPO_ROOT / "scripts" / "Joystick" / "data" / "abis" / "tgsv8.json"

SUBMIT_RPC = "https://rpc.pulsechain.com"
READ_RPC   = "https://rpc.pulsechainstats.com"
CHAIN_ID   = 369
SOLC_VER   = "0.8.21"
GAS_MULT   = 1.3
CONTRACT_NAME = "TreasurySharkV8"

JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# Constructor args — PulseChain mainnet addresses
CONSTRUCTOR_ARGS = {
    "v4":        "0x394c3D5990cEfC7Be36B82FDB07a7251ACe61cc7",   # V4 Personal Minter
    "v3":        "0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC",   # V3 Index Minter
    "mv":        "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",   # MV / WM token
    "wpls":      "0xA1077a294dDE1B09bB078844df40758a5D0f9a27",   # WPLS
    "routerV1":  "0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02",   # PulseX V1 Router
    "routerV2":  "0x165C3410fC91EF562C50559f7d2289fEbed552d9",   # PulseX V2 Router
    "factoryV1": "0x1715a3E4A142d8b698131108995174F37aEBA10D",   # PulseX V1 Factory
    "factoryV2": "0x29eA7545DEf87022BAdc76323F373EA1e707C523",   # PulseX V2 Factory
}

# ── Helpers ─────────────────────────────────────────────────────────────────

def ensure_solc():
    installed = get_installed_solc_versions()
    version_strs = [str(v) for v in installed]
    if SOLC_VER not in version_strs:
        print(f"  Downloading solc {SOLC_VER} (one-time ~60MB)...")
        install_solc(SOLC_VER)
        print(f"  solc {SOLC_VER} installed.")
    else:
        print(f"  solc {SOLC_VER} already cached.")


def compile_contract(source: str) -> tuple:
    """Compile TGSv8.sol → (abi, bytecode) using via-IR pipeline."""
    print(f"\n[1/6] Compiling {CONTRACT_NAME} with solc {SOLC_VER} (via-IR, optimize=200)...")
    input_json = {
        "language": "Solidity",
        "sources": {"TGSv8.sol": {"content": source}},
        "settings": {
            "viaIR": True,
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}}
        }
    }
    compiled = compile_standard(input_json, solc_version=SOLC_VER)
    contract = compiled["contracts"]["TGSv8.sol"][CONTRACT_NAME]
    abi      = contract["abi"]
    bytecode = contract["evm"]["bytecode"]["object"]
    byte_len = len(bytecode) // 2
    print(f"  Bytecode size: {byte_len:,} bytes ({byte_len/1024:.1f} KB)  ABI entries: {len(abi)}")
    if byte_len > 24576:
        print(f"  WARNING: Exceeds 24,576 byte EIP-170 limit!")
        sys.exit(1)
    else:
        print(f"  Under EIP-170 limit ({24576 - byte_len:,} bytes to spare) ✓")
    return abi, bytecode


def update_env_file(key: str, address: str):
    """Write or replace key= line in .env."""
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


def save_abi(abi: list):
    """Save ABI to Joystick data dir for agent use."""
    ABI_OUT.parent.mkdir(parents=True, exist_ok=True)
    ABI_OUT.write_text(json.dumps(abi, indent=2))
    print(f"  ABI saved to {ABI_OUT.relative_to(REPO_ROOT)}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=f"Deploy {CONTRACT_NAME} to PulseChain")
    parser.add_argument("--dry-run",    action="store_true", help="Compile only — no deploy")
    parser.add_argument("--update-env", action="store_true", help="Write TGSV8_ADDRESS to .env")
    parser.add_argument("--sol",        default=str(CONTRACT_FILE), help="Path to .sol file")
    parser.add_argument("--rpc",        default=SUBMIT_RPC, help="RPC URL for deploy TX")
    args = parser.parse_args()

    print("=" * 60)
    print(f"{CONTRACT_NAME} Deploy — Treasury Game Shark V8")
    print("=" * 60)

    # ── Step 0: Read source ─────────────────────────────────────────────
    sol_path = Path(args.sol)
    if not sol_path.exists():
        print(f"ERROR: {sol_path} not found.")
        sys.exit(1)
    source = sol_path.read_text()
    print(f"\n[0/6] Contract source: {sol_path}")

    # ── Step 1: Install solc + compile ──────────────────────────────────
    ensure_solc()
    abi, bytecode = compile_contract(source)

    # Save ABI regardless of dry-run
    save_abi(abi)

    if args.dry_run:
        fn_names = [e['name'] for e in abi if e.get('type') == 'function']
        print(f"\n[DRY-RUN] Compilation successful. No deploy.")
        print(f"  Functions ({len(fn_names)}): {fn_names}")
        has_mint_wm = 'mintWM' in fn_names
        print(f"  mintWM present: {has_mint_wm} {'✓' if has_mint_wm else '✗ MISSING!'}")
        return

    # ── Step 2: Load wallet ─────────────────────────────────────────────
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

    # ── Step 3: Connect ─────────────────────────────────────────────────
    rpc_url = args.rpc
    print(f"\n[3/6] Connecting to {rpc_url}...")
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print("ERROR: Cannot connect to RPC.")
        sys.exit(1)
    block = w3.eth.block_number
    pls_bal = w3.eth.get_balance(JOEY_WALLET)
    print(f"  Block: {block:,}   PLS balance: {pls_bal / 1e18:.2f}")

    # ── Step 4: Estimate gas + deploy ───────────────────────────────────
    print(f"\n[4/6] Estimating deploy gas...")
    factory = w3.eth.contract(abi=abi, bytecode=bytecode)

    ctor_args = [Web3.to_checksum_address(v) for v in CONSTRUCTOR_ARGS.values()]
    constructor = factory.constructor(*ctor_args)

    gas_price = w3.eth.gas_price
    gas_est   = constructor.estimate_gas({"from": JOEY_WALLET})
    gas_limit = int(gas_est * GAS_MULT)
    cost_pls  = gas_limit * gas_price / 1e18
    nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
    print(f"  Gas est: {gas_est:,}  Limit: {gas_limit:,}  Gas price: {gas_price/1e9:.2f} Gwei")
    print(f"  Max cost: {cost_pls:.4f} PLS   Nonce: {nonce}")

    print(f"\n[5/6] Deploying {CONTRACT_NAME}...")
    tx = constructor.build_transaction({
        "from":     JOEY_WALLET,
        "nonce":    nonce,
        "gas":      gas_limit,
        "gasPrice": gas_price,
        "chainId":  CHAIN_ID,
    })
    signed  = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
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

    print(f"\n  ✓ {CONTRACT_NAME} deployed at: {address}")

    # ── Step 6: Verify ──────────────────────────────────────────────────
    print(f"\n[6/6] Verifying contract state...")
    contract = w3.eth.contract(address=address, abi=abi)

    contract_owner = contract.functions.owner().call()
    is_authorized  = contract.functions.authorized(JOEY_WALLET).call()
    is_paused      = contract.functions.paused().call()
    mv_addr        = contract.functions.mv().call()
    router_v1      = contract.functions.routerV1().call()
    router_v2      = contract.functions.routerV2().call()

    print(f"  owner()           = {contract_owner}")
    print(f"  authorized(Joey)  = {is_authorized}")
    print(f"  paused()          = {is_paused}")
    print(f"  mv()              = {mv_addr}")
    print(f"  routerV1()        = {router_v1}")
    print(f"  routerV2()        = {router_v2}")

    assert contract_owner.lower() == JOEY_WALLET.lower(), "owner() mismatch!"
    assert is_authorized, "authorized(Joey) is False!"
    assert not is_paused, "paused() is True!"
    print("  All assertions passed ✓")

    # ── Step 7: Update .env ─────────────────────────────────────────────
    if args.update_env:
        print(f"\n[+] Writing TGSV8_ADDRESS to .env...")
        update_env_file("TGSV8_ADDRESS", address)

    print("\n" + "=" * 60)
    print(f"DEPLOY COMPLETE")
    print(f"  Address:  {address}")
    print(f"  TX:       0x{tx_hash.hex()}")
    print(f"  Block:    {blk:,}")
    print(f"  Constructor args:")
    for name, addr in CONSTRUCTOR_ARGS.items():
        print(f"    {name:12s} = {addr}")
    print("=" * 60)

    print("\nNext steps:")
    if not args.update_env:
        print(f"  export TGSV8_ADDRESS={address}")
    print(f"  python scripts/deploy_tgsv8.py --dry-run  # verify ABI")
    print(f"  python scripts/Joystick/bot.py --status")


if __name__ == "__main__":
    main()
