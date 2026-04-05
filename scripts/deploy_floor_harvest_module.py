#!/usr/bin/env python3
"""
Deploy FloorHarvestModule to PulseChain mainnet.

Steps:
  1. Deploy FloorHarvestModule from pre-compiled artifact
  2. Register 3 selectors on JoystickHub via batchRegisterModule
  3. Set 5 config keys via batchSetConfig
  4. Verify via floorConfig() and quoteFloorCycle()

Usage:
  source /opt/joystick/.env.pulse
  python3 scripts/deploy_floor_harvest_module.py
"""
import os
import sys
import json
import time
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
ARTIFACT    = REPO_ROOT / "build" / "FloorHarvestModule" / "combined.json"

SUBMIT_RPC  = "https://rpc.pulsechain.com"
READ_RPC    = "https://rpc-pulsechain.g4mm4.io"
CHAIN_ID    = 369
GAS_MULT    = 2.5

JOEY_WALLET   = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
JOYSTICK_HUB  = Web3.to_checksum_address("0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14")

# Config values
GIBS_LAU      = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
AFFECTION     = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
GIBS_WPLS     = "0x7BCa1c997c475eac9c61417e88bed158ACA757f0"
BURN_369      = "0x0000000000000000000000000000000000000369"
GIBS_IS_TOKEN0 = 1  # GIBS 0x66... < WPLS 0xa1...

# Config keys (keccak256 of string)
CONFIG = {
    "floor.gibsLau":       int(GIBS_LAU, 16),
    "floor.affection":     int(AFFECTION, 16),
    "floor.gibsWplsPair":  int(GIBS_WPLS, 16),
    "floor.gibsIsToken0":  GIBS_IS_TOKEN0,
    "floor.burnAddr":      int(BURN_369, 16),
}

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
        "inputs": [
            {"internalType": "bytes32[]", "name": "keys", "type": "bytes32[]"},
            {"internalType": "uint256[]", "name": "values", "type": "uint256[]"}
        ],
        "name": "batchSetConfig",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
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
    # Simulate via eth_call
    print(f"  [{label}] Simulating via eth_call...")
    try:
        sim_tx = {k: v for k, v in tx_dict.items() if k not in ("gas", "maxFeePerGas", "maxPriorityFeePerGas", "type")}
        w3.eth.call(sim_tx)
        print(f"  [{label}] Simulation passed")
    except Exception as e:
        print(f"  [{label}] SIMULATION FAILED: {e}")
        sys.exit(1)

    # Estimate gas
    print(f"  [{label}] Estimating gas...")
    try:
        gas_est = w3.eth.estimate_gas(tx_dict)
    except Exception as e:
        print(f"  [{label}] estimate_gas FAILED: {e}")
        sys.exit(1)

    gas_limit = int(gas_est * GAS_MULT)
    tx_dict["gas"] = gas_limit
    print(f"  [{label}] Gas estimate: {gas_est:,} -> limit: {gas_limit:,} ({GAS_MULT}x)")

    # Sign and send
    signed = account.sign_transaction(tx_dict)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  [{label}] TX sent: 0x{tx_hash.hex()}")

    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if receipt["status"] != 1:
        print(f"  [{label}] TX FAILED (status=0)!")
        sys.exit(1)

    gas_used = receipt["gasUsed"]
    print(f"  [{label}] Confirmed. Gas used: {gas_used:,}")
    return receipt


def main():
    print()
    print("=" * 60)
    print("  FloorHarvestModule Deploy — PulseChain Mainnet")
    print("=" * 60)

    # ── Step 1: Load artifact ──────────────────────────────────────────
    print(f"\n[1/5] Loading compiled artifact...")
    if not ARTIFACT.exists():
        print(f"  ERROR: {ARTIFACT} not found.")
        sys.exit(1)

    artifact = json.loads(ARTIFACT.read_text())
    abi = artifact["abi"]
    bytecode = artifact["bin"]
    byte_len = len(bytecode) // 2
    print(f"  FloorHarvestModule: {byte_len:,} bytes ({byte_len/1024:.1f} KB)")
    print(f"  ABI entries: {len(abi)}")

    if byte_len > 24576:
        print(f"  ERROR: Exceeds 24,576 byte EIP-170 limit!")
        sys.exit(1)

    # ── Step 2: Load wallet ────────────────────────────────────────────
    print(f"\n[2/5] Loading wallet...")
    pkey = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
    if not pkey:
        print("  ERROR: DYSNOMIA_PRIVATE_KEY not set.")
        sys.exit(1)

    account = Account.from_key(pkey)
    if account.address.lower() != JOEY_WALLET.lower():
        print(f"  ERROR: Key resolves to {account.address}, expected {JOEY_WALLET}")
        sys.exit(1)
    print(f"  Wallet: {account.address}")

    # Connect to submit RPC (single provider — avoid race condition)
    w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print("  ERROR: Cannot connect to RPC.")
        sys.exit(1)

    block = w3.eth.block_number
    pls_bal = w3.eth.get_balance(JOEY_WALLET)
    print(f"  Block: {block:,}  PLS: {pls_bal / 1e18:,.0f}")

    nonce = w3.eth.get_transaction_count(account.address)
    print(f"  Starting nonce: {nonce}")

    # ── Step 3: Deploy FloorHarvestModule ──────────────────────────────
    print(f"\n[3/5] Deploying FloorHarvestModule...")
    gas_params = build_gas_params(w3)
    print(f"  maxFeePerGas: {gas_params['maxFeePerGas'] / 1e9:.2f} Gwei")
    print(f"  maxPriorityFeePerGas: {gas_params['maxPriorityFeePerGas'] / 1e9:.2f} Gwei")

    factory = w3.eth.contract(abi=abi, bytecode="0x" + bytecode)
    deploy_tx = factory.constructor().build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "type": 2,
        **gas_params,
    })

    receipt = send_tx(w3, account, deploy_tx, label="DEPLOY")
    module_addr = receipt["contractAddress"]
    print(f"\n  >>> FloorHarvestModule deployed at: {module_addr}")
    nonce += 1

    # ── Step 4: Register selectors on JoystickHub ─────────────────────
    print(f"\n[4/5] Registering selectors on JoystickHub...")
    selectors = [
        fn_selector("floorAndHarvest(uint256,uint256,uint256,bool,uint256)"),
        fn_selector("quoteFloorCycle(uint256,uint256,uint256)"),
        fn_selector("floorConfig()"),
    ]
    for i, sel in enumerate(selectors):
        print(f"  Selector {i}: 0x{sel.hex()}")

    hub = w3.eth.contract(address=JOYSTICK_HUB, abi=HUB_ABI)
    gas_params = build_gas_params(w3)

    register_tx = hub.functions.batchRegisterModule(
        selectors, Web3.to_checksum_address(module_addr)
    ).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "type": 2,
        **gas_params,
    })

    receipt = send_tx(w3, account, register_tx, label="REGISTER")
    print(f"  Selectors registered on Hub -> {module_addr}")
    nonce += 1

    # ── Step 5: Set config values ─────────────────────────────────────
    print(f"\n[5/5] Setting config values...")
    config_keys = []
    config_vals = []
    for key_str, val in CONFIG.items():
        k = keccak256(key_str)
        config_keys.append(k)
        config_vals.append(val)
        print(f"  {key_str}: 0x{k.hex()[:16]}... = {val}")

    gas_params = build_gas_params(w3)

    config_tx = hub.functions.batchSetConfig(
        config_keys, config_vals
    ).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "type": 2,
        **gas_params,
    })

    receipt = send_tx(w3, account, config_tx, label="CONFIG")
    print(f"  Config set: {len(config_keys)} keys")
    nonce += 1

    # ── Verify ─────────────────────────────────────────────────────────
    print(f"\n[VERIFY] Calling floorConfig() and quoteFloorCycle() on Hub...")

    # Use read RPC for verification
    w3_read = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))
    # Wait a moment for propagation
    time.sleep(3)

    floor_abi = abi + HUB_ABI
    hub_floor = w3_read.eth.contract(address=JOYSTICK_HUB, abi=floor_abi)

    try:
        cfg = hub_floor.functions.floorConfig().call()
        print(f"  floorConfig():")
        print(f"    gibsLau:      {cfg[0]}")
        print(f"    affection:    {cfg[1]}")
        print(f"    gibsWplsPair: {cfg[2]}")
        print(f"    gibsIsToken0: {cfg[3]}")
        print(f"    burnAddr:     {cfg[4]}")

        # Validate
        assert cfg[0].lower() == GIBS_LAU.lower(), f"gibsLau mismatch: {cfg[0]}"
        assert cfg[1].lower() == AFFECTION.lower(), f"affection mismatch: {cfg[1]}"
        assert cfg[2].lower() == GIBS_WPLS.lower(), f"gibsWplsPair mismatch: {cfg[2]}"
        assert cfg[3] == True, f"gibsIsToken0 mismatch: {cfg[3]}"
        assert cfg[4].lower() == BURN_369.lower(), f"burnAddr mismatch: {cfg[4]}"
        print(f"  floorConfig() VERIFIED OK")
    except Exception as e:
        print(f"  floorConfig() ERROR: {e}")
        sys.exit(1)

    try:
        # quoteFloorCycle(primeCount=17, lpBps=5000, wplsAvailable=2000e18)
        wpls_2000 = 2000 * 10**18
        quote = hub_floor.functions.quoteFloorCycle(17, 5000, wpls_2000).call()
        print(f"\n  quoteFloorCycle(17, 5000, 2000 WPLS):")
        print(f"    feasible:     {quote[0]}")
        print(f"    wplsNeeded:   {quote[1] / 1e18:.4f} WPLS")
        print(f"    wplsFromSell: {quote[2] / 1e18:.4f} WPLS")
        print(f"    netWpls:      {quote[3] / 1e18:.4f} WPLS")
        print(f"    lpGibs:       {quote[4] / 1e18:.4f}")
        print(f"    sellGibs:     {quote[5] / 1e18:.4f}")

        if not quote[0]:
            print(f"\n  WARNING: quoteFloorCycle returned feasible=False with 2000 WPLS")
            print(f"  Investigate: pair may be empty or reserves too low")
        else:
            print(f"  quoteFloorCycle() VERIFIED OK — feasible=True")
    except Exception as e:
        print(f"  quoteFloorCycle() ERROR: {e}")
        # Don't exit — deploy is done, just a verification issue

    # ── Summary ────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  DEPLOYMENT COMPLETE")
    print(f"{'=' * 60}")
    print(f"  FloorHarvestModule: {module_addr}")
    print(f"  JoystickHub:        {JOYSTICK_HUB}")
    print(f"  Selectors:          3 registered")
    print(f"  Config keys:        5 set")
    print(f"\n  For config.py, add after HARVEST_MODULE_V3:")
    print(f'  FLOOR_HARVEST_MODULE = Web3.to_checksum_address("{module_addr}")')
    print()


if __name__ == "__main__":
    main()
