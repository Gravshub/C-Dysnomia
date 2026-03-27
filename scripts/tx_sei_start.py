#!/usr/bin/env python3
"""SEI.Start() — Create a YUE wallet for any LAU token on PulseChain.

Calls SEI.Start(LAU_ADDR, name, symbol) from the wallet.

Usage:
  python scripts/tx_sei_start.py                              # defaults (GIBS LAU, Joey wallet)
  python scripts/tx_sei_start.py --lau 0x1234...              # custom LAU
  python scripts/tx_sei_start.py --wallet 0x5678...           # custom wallet
  python scripts/tx_sei_start.py --name "My Wallet" --symbol "MYW"  # custom YUE name/symbol
"""
import argparse
from web3 import Web3
from eth_account import Account
import json, os

# ── Defaults (Joey / GIBS) ───────────────────────────────────
DEFAULT_WALLET = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
DEFAULT_LAU    = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
DEFAULT_NAME   = "Gibson Wallet"
DEFAULT_SYMBOL = "GIBSw"

# ── CLI ──────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--lau",    default=DEFAULT_LAU,    help="LAU token address (default: GIBS)")
parser.add_argument("--wallet", default=DEFAULT_WALLET, help="Wallet address (default: Joey)")
parser.add_argument("--name",   default=DEFAULT_NAME,   help="YUE wallet name (default: Gibson Wallet)")
parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="YUE wallet symbol (default: GIBSw)")
args = parser.parse_args()

# Use main RPC for tx submission (reliable), pulsechainstats for reads
SUBMIT_RPC = "https://rpc.pulsechain.com"
RPC = "https://rpc.pulsechainstats.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# Addresses
SEI_ADDR    = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
LAU_ADDR    = Web3.to_checksum_address(args.lau)
CHAN_ADDR   = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
WALLET      = Web3.to_checksum_address(args.wallet)

# Joey's private key — read from DYSNOMIA_PRIVATE_KEY env var (same as Accounts.cs)
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY env var not set.")
    print("  Create .env with: DYSNOMIA_PRIVATE_KEY=0x<your_key>")
    print("  Then: source .env && python3 scripts/tx_sei_start.py")
    import sys; sys.exit(1)

account = Account.from_key(JOEY_PKEY)
print(f"Account: {account.address}")
assert account.address.lower() == WALLET.lower(), "Key mismatch!"

# SEI.Start() ABI
start_abi = [{
    "inputs": [
        {"name": "LauToken",   "type": "address"},
        {"name": "YueName",    "type": "string"},
        {"name": "YueSymbol",  "type": "string"}
    ],
    "name": "Start",
    "outputs": [
        {"name": "Yue",       "type": "address"},
        {"name": "UserToken", "type": "address"}
    ],
    "stateMutability": "nonpayable",
    "type": "function"
}]

sei = w3.eth.contract(address=SEI_ADDR, abi=start_abi)

# Check current state
nonce = w3.eth.get_transaction_count(WALLET)
balance = w3.eth.get_balance(WALLET) / 1e18
print(f"Nonce: {nonce}  PLS balance: {balance:.4f}")

# Simulate first
print(f"\nSimulating SEI.Start()...")
try:
    result = sei.functions.Start(LAU_ADDR, args.name, args.symbol).call(
        {'from': WALLET}
    )
    print(f"  Simulation OK — YUE would be: {result[0]}")
    print(f"  UserToken: {result[1]}")
except Exception as e:
    print(f"  Simulation failed: {e}")
    import sys; sys.exit(1)

# Gas estimate
gas_est = sei.functions.Start(LAU_ADDR, args.name, args.symbol).estimate_gas(
    {'from': WALLET}
)
gas_price = w3.eth.gas_price
cost_pls = gas_est * gas_price / 1e18
print(f"\nGas estimate: {gas_est:,} @ {gas_price/1e9:.2f} Gwei = {cost_pls:.4f} PLS")

# Build transaction
tx = sei.functions.Start(LAU_ADDR, args.name, args.symbol).build_transaction({
    'from':     WALLET,
    'nonce':    nonce,
    'gas':      int(gas_est * 1.2),  # 20% buffer
    'gasPrice': gas_price,
    'chainId':  369,  # PulseChain
})

# Sign
signed = account.sign_transaction(tx)
print(f"\nSending SEI.Start() transaction...")

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

# Verify: CHAN.Yan(wallet) should now return YUE address
print(f"\nVerifying via CHAN.Yan(wallet)...")
yan_abi = [{"inputs":[{"type":"address"}],"name":"Yan","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
chan = w3.eth.contract(address=CHAN_ADDR, abi=yan_abi)
yue_addr = chan.functions.Yan(WALLET).call()
print(f"  CHAN.Yan(wallet) = {yue_addr}")

if yue_addr and yue_addr != "0x0000000000000000000000000000000000000000":
    print(f"  ✓ YUE CREATED: {yue_addr}")
    # Get YUE token name
    name_abi = [{"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
    try:
        yue_contract = w3.eth.contract(address=yue_addr, abi=name_abi)
        yue_name = yue_contract.functions.name().call()
        print(f"  YUE name: {yue_name}")
    except:
        pass
    print(f"\n*** UPDATE CLAUDE.md: YUE = {yue_addr} ***")
else:
    print(f"  ✗ YUE not found in CHAN — check transaction")
