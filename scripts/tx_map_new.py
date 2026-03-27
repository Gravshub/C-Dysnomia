#!/usr/bin/env python3
"""MAP.New() — Create a QING venue for any LAU token on PulseChain.

Calls MAP.New(LAU_ADDR) from the wallet to deploy a new QING with the LAU as Asset.

Usage:
  python scripts/tx_map_new.py                         # defaults (GIBS LAU, Joey wallet)
  python scripts/tx_map_new.py --lau 0x1234...         # custom LAU
  python scripts/tx_map_new.py --wallet 0x5678...      # custom wallet
"""
import argparse
from web3 import Web3
from eth_account import Account
import json, os

# ── Defaults (Joey / GIBS) ───────────────────────────────────
DEFAULT_WALLET = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
DEFAULT_LAU    = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"

# ── CLI ──────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--lau",    default=DEFAULT_LAU,    help="LAU token address (default: GIBS)")
parser.add_argument("--wallet", default=DEFAULT_WALLET, help="Wallet address (default: Joey)")
args = parser.parse_args()

RPC = "https://rpc.pulsechainstats.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# Addresses
MAP_ADDR    = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
LAU_ADDR    = Web3.to_checksum_address(args.lau)
WALLET      = Web3.to_checksum_address(args.wallet)

# Joey's private key — read from DYSNOMIA_PRIVATE_KEY env var (same as Accounts.cs)
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY env var not set.")
    print("  Create .env with: DYSNOMIA_PRIVATE_KEY=0x<your_key>")
    print("  Then: source .env && python3 scripts/tx_map_new.py")
    import sys; sys.exit(1)

account = Account.from_key(JOEY_PKEY)
print(f"Account: {account.address}")
assert account.address.lower() == WALLET.lower(), "Key mismatch!"

# MAP.New() ABI
new_abi = [{
    "inputs": [
        {"name": "Integrative", "type": "address"}
    ],
    "name": "New",
    "outputs": [
        {"name": "", "type": "address"}
    ],
    "stateMutability": "nonpayable",
    "type": "function"
}]

map_contract = w3.eth.contract(address=MAP_ADDR, abi=new_abi)

# Check current state
nonce = w3.eth.get_transaction_count(WALLET)
balance = w3.eth.get_balance(WALLET) / 1e18
print(f"Nonce: {nonce}  PLS balance: {balance:.4f}")

# Simulate first
print(f"\nSimulating MAP.New(LAU)...")
try:
    result = map_contract.functions.New(LAU_ADDR).call(
        {'from': WALLET}
    )
    print(f"  Simulation OK — QING would be at: {result}")
except Exception as e:
    print(f"  Simulation failed: {e}")
    import sys; sys.exit(1)

# Gas estimate
gas_est = map_contract.functions.New(LAU_ADDR).estimate_gas(
    {'from': WALLET}
)
gas_price = w3.eth.gas_price
cost_pls = gas_est * gas_price / 1e18
print(f"\nGas estimate: {gas_est:,} @ {gas_price/1e9:.2f} Gwei = {cost_pls:.4f} PLS")

# Build transaction
tx = map_contract.functions.New(LAU_ADDR).build_transaction({
    'from':     WALLET,
    'nonce':    nonce,
    'gas':      int(gas_est * 1.2),  # 20% buffer
    'gasPrice': gas_price,
    'chainId':  369,  # PulseChain
})

# Sign
signed = account.sign_transaction(tx)
print(f"\nSending MAP.New(LAU) transaction...")

# Send
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"TX sent: 0x{tx_hash.hex()}")
print(f"Waiting for confirmation...")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
print(f"\n{'='*60}")
if receipt['status'] == 1:
    print(f"SUCCESS!")
    print(f"  TX hash : 0x{tx_hash.hex()}")
    print(f"  Block   : {receipt['blockNumber']:,}")
    print(f"  Gas used: {receipt['gasUsed']:,}")
    print(f"  Gas cost: {receipt['gasUsed'] * gas_price / 1e18:.4f} PLS")
else:
    print(f"FAILED — status=0")
    print(f"  TX hash: 0x{tx_hash.hex()}")
    import sys; sys.exit(1)

# Verify: read back the deployed QING address
# MAP nonce increments each time New() is called — the QING is deployed by MAP
# We can find it by reading it from the simulation result
print(f"\nVerifying QING deployment...")
# Re-simulate to get address (should be same as what was actually deployed)
try:
    qing_addr = map_contract.functions.New(LAU_ADDR).call({'from': WALLET})
    # Note: this sim will return a new address after the real one was deployed
    # Better to check by probing the address from the receipt
    # The receipt logs contain the QING address
    if receipt.logs:
        for log in receipt.logs:
            print(f"  Log: address={log['address']}  topics={[t.hex() for t in log['topics']]}")
except Exception as e:
    print(f"  Note: {e}")

# Check asset function to verify
asset_abi = [{"inputs":[],"name":"Asset","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
# The QING address should be in the tx logs (Transfer event from 0x0 = mint)
# Look for contracts deployed in this tx
print(f"\n  Check receipt logs for deployed QING address...")
for log in receipt.logs:
    addr = log['address']
    try:
        qing = w3.eth.contract(address=addr, abi=asset_abi)
        asset = qing.functions.Asset().call()
        if asset.lower() == LAU_ADDR.lower():
            print(f"  ★ QING FOUND: {addr}")
            print(f"    Asset = {asset} (== LAU ✓)")
            print(f"\n*** UPDATE CLAUDE.md: QING = {addr} ***")
    except:
        pass
