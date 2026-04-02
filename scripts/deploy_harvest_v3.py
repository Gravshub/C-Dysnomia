#!/usr/bin/env python3
"""
deploy_harvest_v3.py — Deploy HarvestModuleV3 and register selectors in JoystickHub.

HarvestModuleV3 combines primeGibs + Purchase + sell into one atomic TX,
closing the sniper exploit window where a dedicated bot (0x65930aa7...)
extracts our primed GIBS via Purchase() between our two-TX pipeline.

Usage:
  python3 scripts/deploy_harvest_v3.py [--dry-run]

Prerequisites:
  - solc 0.8.21+ installed (or solcx)
  - DYSNOMIA_PRIVATE_KEY set
  - JoystickHub deployed and configured
"""
import os
import sys
import json
import time
import subprocess
import argparse

from web3 import Web3

# ── Config ─────────────────────────────────────────────────────────────

SUBMIT_RPC = os.getenv("PULSECHAIN_RPC", "https://rpc.pulsechain.com")
READ_RPC   = os.getenv("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
CHAIN_ID   = 369

JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
JOYSTICK_HUB = Web3.to_checksum_address(
    os.getenv("JOYSTICK_HUB_ADDRESS", "0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14")
)

# Function selectors for HarvestModuleV3
# primeAndSell(uint256,uint256,uint8,address[])
PRIME_AND_SELL_SIG = Web3.keccak(text="primeAndSell(uint256,uint256,uint8,address[])")[:4]
# primeGibs(uint256)
PRIME_GIBS_SIG = Web3.keccak(text="primeGibs(uint256)")[:4]

# Also register existing V2 selectors so V3 module handles them all:
# mintLPAndSell(uint256,uint256,uint256,uint8,uint256,address[],uint8)
MINT_LP_AND_SELL_SIG = Web3.keccak(
    text="mintLPAndSell(uint256,uint256,uint256,uint8,uint256,address[],uint8)"
)[:4]
# harvestPreloaded(uint256,uint256,uint8,uint256,address[],uint8)
HARVEST_PRELOADED_SIG = Web3.keccak(
    text="harvestPreloaded(uint256,uint256,uint8,uint256,address[],uint8)"
)[:4]
# batchReseed(address[],uint256[])
BATCH_RESEED_SIG = Web3.keccak(text="batchReseed(address[],uint256[])")[:4]
# harvestConfig()
HARVEST_CONFIG_SIG = Web3.keccak(text="harvestConfig()")[:4]


def compile_contract():
    """Compile HarvestModuleV3.sol and return (abi, bytecode)."""
    sol_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "contracts", "HarvestModuleV3.sol"
    )

    print(f"Compiling {sol_path}...")

    # Try solc CLI first
    try:
        result = subprocess.run(
            ["solc", "--optimize", "--optimize-runs", "200",
             "--combined-json", "abi,bin", sol_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            combined = json.loads(result.stdout)
            # Find HarvestModuleV3 in output
            for key, contract in combined["contracts"].items():
                if "HarvestModuleV3" in key:
                    abi = json.loads(contract["abi"]) if isinstance(contract["abi"], str) else contract["abi"]
                    bytecode = "0x" + contract["bin"]
                    print(f"  Compiled via solc CLI: {len(bytecode)//2 - 1} bytes")
                    return abi, bytecode
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: try py-solc-x
    try:
        from solcx import compile_standard, install_solc, get_installed_solc_versions
        if "0.8.21" not in [str(v) for v in get_installed_solc_versions()]:
            print("  Installing solc 0.8.21...")
            install_solc("0.8.21")

        with open(sol_path, "r") as f:
            source = f.read()

        compiled = compile_standard({
            "language": "Solidity",
            "sources": {"HarvestModuleV3.sol": {"content": source}},
            "settings": {
                "optimizer": {"enabled": True, "runs": 200},
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
            },
        }, solc_version="0.8.21")

        contract_data = compiled["contracts"]["HarvestModuleV3.sol"]["HarvestModuleV3"]
        abi = contract_data["abi"]
        bytecode = "0x" + contract_data["evm"]["bytecode"]["object"]
        print(f"  Compiled via solcx: {len(bytecode)//2 - 1} bytes")
        return abi, bytecode

    except ImportError:
        print("ERROR: Neither `solc` CLI nor `py-solc-x` available.")
        print("Install solc: https://docs.soliditylang.org/en/latest/installing-solidity.html")
        sys.exit(1)


def _load_env():
    """Try to load .env.pulse from known locations."""
    candidates = [
        os.path.expanduser("~/.env.pulse"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env.pulse"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "Joystick", "deploy", ".env.pulse"),
        "/opt/joystick/.env.pulse",
    ]
    for path in candidates:
        if os.path.isfile(path):
            print(f"Loading env from {path}")
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
            return True
    return False


def deploy(dry_run: bool = False):
    """Deploy HarvestModuleV3 and register selectors in Hub."""
    # Try loading .env.pulse if key not already in env
    pk = os.environ.get("DYSNOMIA_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY")
    if not pk:
        _load_env()
        pk = os.environ.get("DYSNOMIA_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY")
    if not pk and not dry_run:
        print("ERROR: No private key found. Set DYSNOMIA_PRIVATE_KEY or PRIVATE_KEY,")
        print("       or place .env.pulse in ~/.env.pulse or /opt/joystick/.env.pulse")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
    account = w3.eth.account.from_key(pk) if pk else None

    abi, bytecode = compile_contract()

    # ── Step 1: Deploy HarvestModuleV3 ──
    print(f"\n--- Step 1: Deploy HarvestModuleV3 ---")
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    deploy_tx = Contract.constructor().build_transaction({
        "from": JOEY_WALLET,
        "nonce": w3.eth.get_transaction_count(JOEY_WALLET),
        "gas": 3_000_000,
        "chainId": CHAIN_ID,
        "maxFeePerGas": int(w3.eth.get_block("latest")["baseFeePerGas"] * 1.12) + 200_000 * 10**9,
        "maxPriorityFeePerGas": 200_000 * 10**9,
        "type": 2,
    })

    if dry_run:
        print(f"  [DRY RUN] Would deploy HarvestModuleV3 ({len(bytecode)//2 - 1} bytes)")
        v3_address = "0x" + "00" * 20
    else:
        signed = account.sign_transaction(deploy_tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  Deploy TX: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        v3_address = receipt["contractAddress"]
        print(f"  HarvestModuleV3 deployed at: {v3_address}")
        print(f"  Gas used: {receipt['gasUsed']}")

    # ── Step 2: Register selectors in Hub ──
    print(f"\n--- Step 2: Register selectors in JoystickHub ---")

    # Hub ABI (just batchRegisterModule and module view)
    hub_abi = [
        {
            "inputs": [{"name": "selectors", "type": "bytes4[]"}, {"name": "impl", "type": "address"}],
            "name": "batchRegisterModule",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [{"name": "selector", "type": "bytes4"}],
            "name": "module",
            "outputs": [{"name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function",
        },
    ]
    hub = w3.eth.contract(address=JOYSTICK_HUB, abi=hub_abi)

    # Register all harvest selectors to V3 module
    selectors = [
        PRIME_AND_SELL_SIG,   # New: primeAndSell
        PRIME_GIBS_SIG,       # Compat: primeGibs
    ]

    selector_names = [
        "primeAndSell(uint256,uint256,uint8,address[])",
        "primeGibs(uint256)",
    ]

    print(f"  Registering {len(selectors)} selectors to {v3_address}:")
    for name, sel in zip(selector_names, selectors):
        print(f"    {sel.hex()} → {name}")

    if dry_run:
        print(f"  [DRY RUN] Would call hub.batchRegisterModule()")
    else:
        reg_tx = hub.functions.batchRegisterModule(
            selectors, Web3.to_checksum_address(v3_address)
        ).build_transaction({
            "from": JOEY_WALLET,
            "nonce": w3.eth.get_transaction_count(JOEY_WALLET),
            "gas": 200_000,
            "chainId": CHAIN_ID,
            "maxFeePerGas": int(w3.eth.get_block("latest")["baseFeePerGas"] * 1.12) + 200_000 * 10**9,
            "maxPriorityFeePerGas": 200_000 * 10**9,
            "type": 2,
        })
        signed = account.sign_transaction(reg_tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  Register TX: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print(f"  Registered. Gas: {receipt['gasUsed']}")

        # Verify
        read_w3 = Web3(Web3.HTTPProvider(READ_RPC))
        hub_read = read_w3.eth.contract(address=JOYSTICK_HUB, abi=hub_abi)
        for sel in selectors:
            impl = hub_read.functions.module(sel).call()
            assert impl.lower() == v3_address.lower(), f"Selector {sel.hex()} not registered!"
        print(f"  ✓ All selectors verified pointing to {v3_address}")

    print(f"\n=== DONE ===")
    print(f"HarvestModuleV3: {v3_address}")
    print(f"Update config.py: HARVEST_MODULE_V3 = Web3.to_checksum_address(\"{v3_address}\")")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy HarvestModuleV3")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    args = parser.parse_args()
    deploy(dry_run=args.dry_run)
