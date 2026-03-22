#!/usr/bin/env python3
"""
Deploy JoystickHub + all modules to PulseChain mainnet.

JoystickHub = modular proxy with delegatecall routing.
Deploys 4 contracts: Hub + HarvestModule + AffectionModule + PurchaseModule.
Then wires selectors + sets initial config.

Usage:
  python scripts/deploy_joystick_hub.py --dry-run        # compile only, print sizes
  python scripts/deploy_joystick_hub.py --update-env      # deploy + write to .env.pulse
  python scripts/deploy_joystick_hub.py                   # deploy only (print addresses)
  python scripts/deploy_joystick_hub.py --skip-wiring     # deploy without register/config
"""
import os
import sys
import subprocess
import argparse
import re
import json
import time
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

try:
    from Crypto.Hash import keccak as keccak_mod

    def keccak256(text: str) -> bytes:
        k = keccak_mod.new(digest_bits=256)
        k.update(text.encode("utf-8"))
        return k.digest()
except ImportError:
    # Fallback to web3 keccak
    def keccak256(text: str) -> bytes:
        return Web3.keccak(text=text)


# ── Constants ───────────────────────────────────────────────────────────────
REPO_ROOT     = Path(__file__).resolve().parent.parent
CONTRACT_FILE = REPO_ROOT / "contracts" / "JoystickHub.sol"
ENV_FILE      = REPO_ROOT / ".env.pulse"
ENV_FILE_ALT  = REPO_ROOT / ".env"
ABI_OUT       = REPO_ROOT / "scripts" / "Joystick" / "data" / "abis" / "joystick_hub.json"

SUBMIT_RPC = "https://rpc.pulsechain.com"
READ_RPC   = "https://rpc-pulsechain.g4mm4.io"
CHAIN_ID   = 369
SOLC_VER   = "0.8.21"
GAS_MULT   = 1.3

JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# Constructor args for JoystickHub
WPLS       = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
ROUTER_V1  = "0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02"
ROUTER_V2  = "0x165C3410fC91EF562C50559f7d2289fEbed552d9"
FACTORY_V1 = "0x1715a3E4A142d8b698131108995174F37aEBA10D"
FACTORY_V2 = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"

# Config addresses
GIBS_LAU   = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
AFFECTION  = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"

CONTRACTS_TO_DEPLOY = ["JoystickHub", "HarvestModule", "AffectionModule", "PurchaseModule"]

# Module selector mappings
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

# Initial config values
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


# ── Helpers ─────────────────────────────────────────────────────────────────

def fn_selector(sig: str) -> bytes:
    """Compute 4-byte function selector from signature string."""
    return keccak256(sig)[:4]


def ensure_solc():
    installed = [str(v) for v in get_installed_solc_versions()]
    if SOLC_VER not in installed:
        print(f"  Downloading solc {SOLC_VER} (one-time ~60MB)...")
        install_solc(SOLC_VER)
        print(f"  solc {SOLC_VER} installed.")
    else:
        print(f"  solc {SOLC_VER} already cached.")


def compile_contracts(source: str) -> dict:
    """Compile JoystickHub.sol → dict of {name: (abi, bytecode)}."""
    input_json = {
        "language": "Solidity",
        "sources": {"JoystickHub.sol": {"content": source}},
        "settings": {
            "viaIR": True,
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}}
        }
    }
    compiled = compile_standard(input_json, solc_version=SOLC_VER)

    results = {}
    for name in CONTRACTS_TO_DEPLOY:
        contract = compiled["contracts"]["JoystickHub.sol"][name]
        abi      = contract["abi"]
        bytecode = contract["evm"]["bytecode"]["object"]
        byte_len = len(bytecode) // 2
        print(f"  {name}: {byte_len:,} bytes ({byte_len/1024:.1f} KB)  ABI entries: {len(abi)}")
        if byte_len > 24576:
            print(f"  ERROR: {name} exceeds 24,576 byte EIP-170 limit!")
            sys.exit(1)
        results[name] = (abi, bytecode)

    return results


def build_merged_abi(contracts: dict) -> list:
    """Merge ABIs from hub + all modules into one unified ABI."""
    merged = []
    seen_sigs = set()
    for name in CONTRACTS_TO_DEPLOY:
        abi, _ = contracts[name]
        for entry in abi:
            # Deduplicate by (type, name)
            sig = (entry.get("type", ""), entry.get("name", ""))
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                merged.append(entry)
    return merged


def save_abi(abi: list):
    """Save merged ABI to Joystick data dir."""
    ABI_OUT.parent.mkdir(parents=True, exist_ok=True)
    ABI_OUT.write_text(json.dumps(abi, indent=2))
    print(f"  ABI saved to {ABI_OUT.relative_to(REPO_ROOT)}")


def update_env_file(key: str, address: str):
    """Write or replace key= line in .env.pulse (fallback to .env)."""
    target = ENV_FILE if ENV_FILE.exists() else ENV_FILE_ALT
    line = f"{key}={address}\n"
    if target.exists():
        content = target.read_text()
        if re.search(rf"^{key}=", content, re.MULTILINE):
            content = re.sub(rf"^{key}=.*$", line.rstrip(), content, flags=re.MULTILINE)
            # Atomic write
            tmp = target.with_suffix(".tmp")
            tmp.write_text(content)
            os.replace(str(tmp), str(target))
            print(f"  Updated existing {key} in {target.name}")
        else:
            with open(target, "a") as f:
                f.write(line)
            print(f"  Appended {key} to {target.name}")
    else:
        target.write_text(line)
        print(f"  Created {target.name} with {key}")


def deploy_contract(w3, account, abi, bytecode, ctor_args=None, label="Contract"):
    """Deploy a single contract. Returns (address, tx_hash, gas_used)."""
    factory = w3.eth.contract(abi=abi, bytecode=bytecode)

    if ctor_args:
        constructor = factory.constructor(*ctor_args)
    else:
        constructor = factory.constructor()

    gas_price = w3.eth.gas_price
    gas_est   = constructor.estimate_gas({"from": account.address})
    gas_limit = int(gas_est * GAS_MULT)
    nonce     = w3.eth.get_transaction_count(account.address)

    tx = constructor.build_transaction({
        "from":     account.address,
        "nonce":    nonce,
        "gas":      gas_limit,
        "gasPrice": gas_price,
        "chainId":  CHAIN_ID,
    })
    signed  = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: 0x{tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if receipt["status"] != 1:
        print(f"  ERROR: {label} deploy FAILED (status=0)")
        sys.exit(1)

    address = receipt["contractAddress"]
    gas_used = receipt["gasUsed"]
    cost_pls = gas_used * gas_price / 1e18
    print(f"  -> {address}  (gas: {gas_used:,}, cost: {cost_pls:.2f} PLS)")
    return address, tx_hash.hex(), gas_used


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Deploy JoystickHub + modules to PulseChain")
    parser.add_argument("--dry-run",      action="store_true", help="Compile only, no deploy")
    parser.add_argument("--update-env",   action="store_true", help="Write JOYSTICK_HUB_ADDRESS to .env.pulse")
    parser.add_argument("--skip-wiring",  action="store_true", help="Deploy without register/config")
    parser.add_argument("--sol",          default=str(CONTRACT_FILE), help="Path to .sol file")
    parser.add_argument("--rpc",          default=SUBMIT_RPC, help="RPC URL for deploy TX")
    args = parser.parse_args()

    print()
    print("=" * 55)
    print("  JoystickHub Deploy -- Modular Contract System")
    print("=" * 55)

    # ── Step 0: Read source ─────────────────────────────────────────────
    sol_path = Path(args.sol)
    if not sol_path.exists():
        print(f"ERROR: {sol_path} not found.")
        sys.exit(1)
    source = sol_path.read_text()

    # ── Step 1: Install solc + compile ──────────────────────────────────
    print(f"\n[1/8] Compiling JoystickHub.sol ...")
    ensure_solc()
    contracts = compile_contracts(source)

    # Build merged ABI
    merged_abi = build_merged_abi(contracts)
    save_abi(merged_abi)
    print(f"  Merged ABI: {len(merged_abi)} entries")

    if args.dry_run:
        print(f"\n[DRY-RUN] Compilation successful. No deploy.")
        for name, (abi, _) in contracts.items():
            fn_names = [e['name'] for e in abi if e.get('type') == 'function']
            print(f"  {name} functions ({len(fn_names)}): {fn_names}")
        return

    # ── Step 2: Load wallet ─────────────────────────────────────────────
    print("\n[2/8] Loading wallet...")
    for env_path in [ENV_FILE, ENV_FILE_ALT]:
        if env_path.exists():
            load_dotenv(env_path)
    pkey = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
    if not pkey:
        print("ERROR: DYSNOMIA_PRIVATE_KEY not set. Run: source .env")
        sys.exit(1)
    account = Account.from_key(pkey)
    if account.address.lower() != JOEY_WALLET.lower():
        print(f"ERROR: Key resolves to {account.address}, expected {JOEY_WALLET}")
        sys.exit(1)
    print(f"  Wallet: {account.address}")

    # Connect
    rpc_url = args.rpc
    print(f"  RPC: {rpc_url}")
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print("ERROR: Cannot connect to RPC.")
        sys.exit(1)
    block = w3.eth.block_number
    pls_bal = w3.eth.get_balance(JOEY_WALLET)
    print(f"  Block: {block:,}   PLS: {pls_bal / 1e18:,.2f}")

    total_gas = 0

    # ── Deploy Hub ──────────────────────────────────────────────────────
    print(f"\n[3/8] Deploying JoystickHub ...")
    hub_abi, hub_bytecode = contracts["JoystickHub"]
    ctor_args = [Web3.to_checksum_address(a) for a in [WPLS, ROUTER_V1, ROUTER_V2, FACTORY_V1, FACTORY_V2]]
    hub_addr, _, gas = deploy_contract(w3, account, hub_abi, hub_bytecode, ctor_args, "JoystickHub")
    total_gas += gas

    # ── Deploy Modules ──────────────────────────────────────────────────
    module_addrs = {}
    for i, name in enumerate(["HarvestModule", "AffectionModule", "PurchaseModule"], start=4):
        print(f"\n[{i}/8] Deploying {name} ...")
        abi, bytecode = contracts[name]
        addr, _, gas = deploy_contract(w3, account, abi, bytecode, label=name)
        module_addrs[name] = addr
        total_gas += gas

    if args.skip_wiring:
        print("\n[--skip-wiring] Skipping selector registration + config.")
    else:
        # ── Register selectors ──────────────────────────────────────────
        print(f"\n[7/8] Registering module selectors ...")
        hub = w3.eth.contract(address=Web3.to_checksum_address(hub_addr), abi=hub_abi)

        selector_batches = [
            (module_addrs["HarvestModule"],   HARVEST_FUNCTIONS),
            (module_addrs["AffectionModule"], AFFECTION_FUNCTIONS),
            (module_addrs["PurchaseModule"],  PURCHASE_FUNCTIONS),
        ]

        gas_price = w3.eth.gas_price
        for mod_addr, fn_sigs in selector_batches:
            selectors = [fn_selector(sig) for sig in fn_sigs]
            nonce = w3.eth.get_transaction_count(account.address)

            tx = hub.functions.batchRegisterModule(
                selectors, Web3.to_checksum_address(mod_addr)
            ).build_transaction({
                "from": account.address,
                "nonce": nonce,
                "gas": 200_000,
                "gasPrice": gas_price,
                "chainId": CHAIN_ID,
            })
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt["status"] != 1:
                print(f"  ERROR: batchRegisterModule failed for {mod_addr}")
                sys.exit(1)
            total_gas += receipt["gasUsed"]
            print(f"  Registered {len(selectors)} selectors -> {mod_addr[:10]}... (gas: {receipt['gasUsed']:,})")

        # ── Set initial config ──────────────────────────────────────────
        print(f"\n[8/8] Setting initial config ...")
        config_keys = []
        config_vals = []
        for key_str, val in INITIAL_CONFIG.items():
            config_keys.append(keccak256(key_str))
            config_vals.append(val)

        nonce = w3.eth.get_transaction_count(account.address)
        tx = hub.functions.batchSetConfig(config_keys, config_vals).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": 300_000,
            "gasPrice": gas_price,
            "chainId": CHAIN_ID,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt["status"] != 1:
            print("  ERROR: batchSetConfig failed")
            sys.exit(1)
        total_gas += receipt["gasUsed"]
        print(f"  Set {len(config_keys)} config values (gas: {receipt['gasUsed']:,})")

    # ── Update env ──────────────────────────────────────────────────────
    if args.update_env:
        print(f"\n[+] Writing JOYSTICK_HUB_ADDRESS to env ...")
        update_env_file("JOYSTICK_HUB_ADDRESS", hub_addr)

    # ── Summary ─────────────────────────────────────────────────────────
    gas_price = w3.eth.gas_price
    total_pls = total_gas * gas_price / 1e18

    print()
    print("=" * 55)
    print(f"  Hub:        {hub_addr}")
    print(f"  Harvest:    {module_addrs.get('HarvestModule', 'N/A')}")
    print(f"  Affection:  {module_addrs.get('AffectionModule', 'N/A')}")
    print(f"  Purchase:   {module_addrs.get('PurchaseModule', 'N/A')}")
    print(f"  Total gas:  {total_gas:,} ({total_pls:,.2f} PLS)")
    print("=" * 55)

    print("\nNext steps:")
    if not args.update_env:
        print(f"  export JOYSTICK_HUB_ADDRESS={hub_addr}")
    print(f"  python scripts/deploy_joystick_hub.py --dry-run  # verify ABI")
    print(f"  python scripts/Joystick/bot.py --status")


if __name__ == "__main__":
    main()
