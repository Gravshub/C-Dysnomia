#!/usr/bin/env python3
"""
deploy_harvest_v3.py — Deploy updated HarvestModule and register mintLPAndSellPair on JoystickHub.

Compiles HarvestModule from JoystickHub.sol (which now includes mintLPAndSellPair),
deploys it, and registers ONLY the new mintLPAndSellPair selector on the Hub proxy.
Existing selectors (primeGibs, mintLPAndSell, etc.) stay on Hub:Harvest V2 — both coexist.

Usage:
  python3 scripts/deploy_harvest_v3.py --dry-run    # compile + print plan
  python3 scripts/deploy_harvest_v3.py               # deploy to mainnet
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path

from web3 import Web3
from eth_account import Account

try:
    from Crypto.Hash import keccak as keccak_mod
    def keccak256(text: str) -> bytes:
        k = keccak_mod.new(digest_bits=256)
        k.update(text.encode("utf-8"))
        return k.digest()
except ImportError:
    def keccak256(text: str) -> bytes:
        return Web3.keccak(text=text)


# ── Constants ──────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
ARTIFACT    = REPO_ROOT / "build" / "HarvestV3" / "combined.json"

SUBMIT_RPC  = "https://rpc.pulsechain.com"
READ_RPC    = "https://rpc-pulsechain.g4mm4.io"
CHAIN_ID    = 369
GAS_MULT    = 2.5

JOEY_WALLET   = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
JOYSTICK_HUB  = Web3.to_checksum_address("0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14")

# Only register the NEW selector — existing selectors stay on V2 module
MINT_LP_AND_SELL_PAIR_SIG = "mintLPAndSellPair(address,address,address,uint256,uint256,uint256,uint256,uint8,uint256,address[],uint8)"

# Hub ABI (minimal — only what we need)
HUB_ABI = [
    {
        "inputs": [
            {"internalType": "bytes4[]", "name": "selectors", "type": "bytes4[]"},
            {"internalType": "address", "name": "module", "type": "address"}
        ],
        "name": "batchRegisterModule",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"name": "selector", "type": "bytes4"}],
        "name": "module",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def fn_selector(sig: str) -> bytes:
    return keccak256(sig)[:4]


def build_gas_params(w3):
    """Build EIP-1559 gas params from latest block."""
    block = w3.eth.get_block("latest")
    base_fee = block["baseFeePerGas"]
    priority = max(w3.to_wei(1, "gwei"), base_fee // 10)
    max_fee = base_fee * 2 + priority
    return {
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority,
    }


def send_tx(w3, account, tx_dict, label="TX"):
    """Simulate, estimate, sign, send, wait. Returns receipt."""
    print(f"  [{label}] Simulating via eth_call...")
    try:
        sim_tx = {k: v for k, v in tx_dict.items() if k not in ("gas", "maxFeePerGas", "maxPriorityFeePerGas", "type")}
        w3.eth.call(sim_tx)
        print(f"  [{label}] Simulation passed")
    except Exception as e:
        print(f"  [{label}] SIMULATION FAILED: {e}")
        sys.exit(1)

    print(f"  [{label}] Estimating gas...")
    try:
        gas_est = w3.eth.estimate_gas(tx_dict)
    except Exception as e:
        print(f"  [{label}] estimate_gas FAILED: {e}")
        sys.exit(1)

    gas_limit = int(gas_est * GAS_MULT)
    tx_dict["gas"] = gas_limit
    print(f"  [{label}] Gas estimate: {gas_est:,} -> limit: {gas_limit:,} ({GAS_MULT}x)")

    signed = account.sign_transaction(tx_dict)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  [{label}] TX sent: 0x{tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if receipt["status"] != 1:
        print(f"  [{label}] TX FAILED (status=0)!")
        sys.exit(1)

    print(f"  [{label}] Confirmed. Gas used: {receipt['gasUsed']:,}")
    return receipt


def compile_if_needed():
    """Compile HarvestModule from JoystickHub.sol if artifact missing."""
    if ARTIFACT.exists():
        artifact = json.loads(ARTIFACT.read_text())
        byte_len = len(artifact["bytecode"]) // 2 - 1  # subtract 0x prefix
        func_names = [e.get("name", "") for e in artifact["abi"] if e.get("type") == "function"]
        if "mintLPAndSellPair" in func_names:
            print(f"  Using cached artifact: {byte_len:,} bytes, {len(func_names)} functions")
            return artifact["abi"], artifact["bytecode"]
        print(f"  Cached artifact missing mintLPAndSellPair — recompiling...")

    print(f"  Compiling HarvestModule from JoystickHub.sol...")
    try:
        from scripts.deploy_joystick_hub import ensure_solc, compile_contracts
    except ImportError:
        sys.path.insert(0, str(REPO_ROOT))
        from scripts.deploy_joystick_hub import ensure_solc, compile_contracts

    source = (REPO_ROOT / "contracts" / "JoystickHub.sol").read_text()
    ensure_solc()
    contracts = compile_contracts(source)
    abi, bytecode_hex = contracts["HarvestModule"]

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    bytecode = "0x" + bytecode_hex
    ARTIFACT.write_text(json.dumps({"abi": abi, "bytecode": bytecode}, indent=2))
    print(f"  Saved artifact: {len(bytecode_hex)//2:,} bytes")
    return abi, bytecode


def main():
    parser = argparse.ArgumentParser(description="Deploy HarvestModule V3 (mintLPAndSellPair)")
    parser.add_argument("--dry-run", action="store_true", help="Compile + print plan only")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  HarvestModule V3 Deploy — mintLPAndSellPair")
    print("=" * 60)

    # ── Step 1: Load / compile artifact ───────────────────────────────
    print(f"\n[1/3] Loading HarvestModule artifact...")
    abi, bytecode = compile_if_needed()
    byte_len = len(bytecode) // 2 - 1
    print(f"  HarvestModule: {byte_len:,} bytes ({byte_len/1024:.1f} KB)")

    if byte_len > 24576:
        print(f"  ERROR: Exceeds 24,576 byte EIP-170 limit!")
        sys.exit(1)

    # Show the selector we'll register
    selector = fn_selector(MINT_LP_AND_SELL_PAIR_SIG)
    print(f"\n  Selector to register:")
    print(f"    0x{selector.hex()} -> {MINT_LP_AND_SELL_PAIR_SIG}")
    print(f"\n  NOTE: Only mintLPAndSellPair is registered on the new module.")
    print(f"  Existing selectors (primeGibs, mintLPAndSell, etc.) stay on Hub:Harvest V2.")

    if args.dry_run:
        print(f"\n[DRY RUN] Would deploy {byte_len:,} bytes + register 1 selector on Hub.")
        print(f"  Estimated gas: ~2.5M (deploy) + ~50K (register) = ~2.55M total")
        return

    # ── Step 2: Load wallet ───────────────────────────────────────────
    print(f"\n[2/3] Loading wallet...")
    pkey = os.environ.get("DYSNOMIA_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY")
    if not pkey:
        # Try .env.pulse
        for path in ["/opt/joystick/.env.pulse", os.path.expanduser("~/.env.pulse")]:
            if os.path.isfile(path):
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip())
                break
        pkey = os.environ.get("DYSNOMIA_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY")

    if not pkey:
        print("  ERROR: No private key. Set DYSNOMIA_PRIVATE_KEY or place .env.pulse.")
        sys.exit(1)

    account = Account.from_key(pkey)
    if account.address.lower() != JOEY_WALLET.lower():
        print(f"  ERROR: Key resolves to {account.address}, expected {JOEY_WALLET}")
        sys.exit(1)
    print(f"  Wallet: {account.address}")

    w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print("  ERROR: Cannot connect to RPC.")
        sys.exit(1)

    block = w3.eth.block_number
    pls_bal = w3.eth.get_balance(JOEY_WALLET)
    print(f"  Block: {block:,}  PLS: {pls_bal / 1e18:,.0f}")

    nonce = w3.eth.get_transaction_count(account.address)
    print(f"  Starting nonce: {nonce}")

    # ── Step 3a: Deploy HarvestModule ─────────────────────────────────
    print(f"\n[3/3a] Deploying HarvestModule...")
    gas_params = build_gas_params(w3)
    print(f"  maxFeePerGas: {gas_params['maxFeePerGas'] / 1e9:.2f} Gwei")

    factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    deploy_tx = factory.constructor().build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "type": 2,
        **gas_params,
    })

    receipt = send_tx(w3, account, deploy_tx, label="DEPLOY")
    module_addr = receipt["contractAddress"]
    print(f"\n  >>> HarvestModule V3 deployed at: {module_addr}")
    nonce += 1

    # ── Step 3b: Register mintLPAndSellPair selector ──────────────────
    print(f"\n[3/3b] Registering mintLPAndSellPair on JoystickHub...")
    hub = w3.eth.contract(address=JOYSTICK_HUB, abi=HUB_ABI)
    gas_params = build_gas_params(w3)

    register_tx = hub.functions.batchRegisterModule(
        [selector], Web3.to_checksum_address(module_addr)
    ).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "type": 2,
        **gas_params,
    })

    receipt = send_tx(w3, account, register_tx, label="REGISTER")
    print(f"  Selector 0x{selector.hex()} registered -> {module_addr}")
    nonce += 1

    # ── Verify ────────────────────────────────────────────────────────
    print(f"\n[VERIFY] Checking selector routing...")
    time.sleep(3)
    w3_read = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))
    hub_read = w3_read.eth.contract(address=JOYSTICK_HUB, abi=HUB_ABI)

    impl = hub_read.functions.module(selector).call()
    assert impl.lower() == module_addr.lower(), f"Selector not routed! Got {impl}"
    print(f"  mintLPAndSellPair -> {impl} VERIFIED")

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  DEPLOYMENT COMPLETE")
    print(f"{'=' * 60}")
    print(f"  HarvestModule V3: {module_addr}")
    print(f"  JoystickHub:      {JOYSTICK_HUB}")
    print(f"  Selector:         0x{selector.hex()} (mintLPAndSellPair)")
    print(f"  Block:            {receipt['blockNumber']}")
    print(f"\n  For config.py:")
    print(f'  HARVEST_MODULE_V3 = Web3.to_checksum_address("{module_addr}")')
    print()


if __name__ == "__main__":
    main()
