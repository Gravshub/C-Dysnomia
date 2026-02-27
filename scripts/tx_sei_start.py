#!/usr/bin/env python3
"""
TX 1: SEI.Start() — Create Joey's YUE wallet.
Call SEI.Start(GIBS_ADDR, "Gibson Wallet", "GIBSw") from Joey's wallet.
"""
from web3 import Web3
from eth_account import Account
import json, os

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# Addresses
SEI_ADDR    = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
GIBS_ADDR   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
CHAN_ADDR   = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# Joey's private key — read from DYSNOMIA_PRIVATE_KEY env var (same as Accounts.cs)
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY env var not set.")
    print("  Create .env with: DYSNOMIA_PRIVATE_KEY=0x<your_key>")
    print("  Then: source .env && python3 scripts/tx_sei_start.py")
    import sys; sys.exit(1)

account = Account.from_key(JOEY_PKEY)
print(f"Account: {account.address}")
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

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
nonce = w3.eth.get_transaction_count(JOEY_WALLET)
balance = w3.eth.get_balance(JOEY_WALLET) / 1e18
print(f"Nonce: {nonce}  PLS balance: {balance:.4f}")

# Simulate first
print(f"\nSimulating SEI.Start()...")
try:
    result = sei.functions.Start(GIBS_ADDR, "Gibson Wallet", "GIBSw").call(
        {'from': JOEY_WALLET}
    )
    print(f"  Simulation OK — YUE would be: {result[0]}")
    print(f"  UserToken: {result[1]}")
except Exception as e:
    print(f"  Simulation failed: {e}")
    import sys; sys.exit(1)

# Gas estimate
gas_est = sei.functions.Start(GIBS_ADDR, "Gibson Wallet", "GIBSw").estimate_gas(
    {'from': JOEY_WALLET}
)
gas_price = w3.eth.gas_price
cost_pls = gas_est * gas_price / 1e18
print(f"\nGas estimate: {gas_est:,} @ {gas_price/1e9:.2f} Gwei = {cost_pls:.4f} PLS")

# Build transaction
tx = sei.functions.Start(GIBS_ADDR, "Gibson Wallet", "GIBSw").build_transaction({
    'from':     JOEY_WALLET,
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

# Verify: CHAN.Yan(Joey) should now return YUE address
print(f"\nVerifying via CHAN.Yan(Joey)...")
yan_abi = [{"inputs":[{"type":"address"}],"name":"Yan","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
chan = w3.eth.contract(address=CHAN_ADDR, abi=yan_abi)
yue_addr = chan.functions.Yan(JOEY_WALLET).call()
print(f"  CHAN.Yan(Joey) = {yue_addr}")

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
    print(f"\n*** UPDATE CLAUDE.md: Joey's YUE = {yue_addr} ***")
else:
    print(f"  ✗ YUE not found in CHAN — check transaction")
