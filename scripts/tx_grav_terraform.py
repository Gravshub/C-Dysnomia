#!/usr/bin/env python3
"""
Join Grav QING + Terraform via CHOA.Chat

TX1: GravQING.Join(GIBS)           — free, mints 1 Grav QING token
TX2: CHOA.Chat(GravQING, msg)      — terraforming: +1 GIBS, +1 CHOA, CHOA → YUE wallet
"""
from web3 import Web3
from eth_account import Account
import os, sys, time

SUBMIT_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_ADDR   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GRAV_QING   = Web3.to_checksum_address("0x6152e1b78a4f428BF26348B658E7107c6BcF747c")
CHOA_ADDR   = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
JOEY_YUE    = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")

JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. source .env first.")
    sys.exit(1)

account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

QING_ABI = [
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"Join","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"Admitted","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]
CHOA_ABI = [
    {"inputs":[{"name":"Qing","type":"address"},{"name":"MSG","type":"string"}],"name":"Chat","outputs":[{"type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
]
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

grav_qing = w3.eth.contract(address=GRAV_QING, abi=QING_ABI)
choa      = w3.eth.contract(address=CHOA_ADDR, abi=CHOA_ABI)
gibs      = w3.eth.contract(address=GIBS_ADDR, abi=ERC20_ABI)
choa_tok  = w3.eth.contract(address=CHOA_ADDR, abi=ERC20_ABI)

# Pre-flight state
print(f"\n--- Pre-flight ---")
print(f"GIBS balance (Joey):    {gibs.functions.balanceOf(JOEY_WALLET).call()/1e18:.0f}")
print(f"CHOA in YUE wallet:     {choa_tok.functions.balanceOf(JOEY_YUE).call()/1e18:.4f}")
print(f"Grav QING total supply: {grav_qing.functions.totalSupply().call()/1e18:.0f}")
print(f"Joey admitted (GIBS):   {grav_qing.functions.Admitted(GIBS_ADDR).call()}")

TERRAFORM_MSG = "player 578 terraforming grav sector. Joey in the grid. still working on a handle. hack the planet."

def send_tx(fn_call, label):
    nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
    gas_price = w3.eth.gas_price
    gas_est   = fn_call.estimate_gas({'from': JOEY_WALLET})
    print(f"  Nonce: {nonce}  Gas: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")
    tx = fn_call.build_transaction({
        'from': JOEY_WALLET, 'nonce': nonce,
        'gas': int(gas_est * 1.2), 'gasPrice': gas_price, 'chainId': 369,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: 0x{tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    print(f"  Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas used: {receipt['gasUsed']:,}")
    assert receipt['status'] == 1, f"{label} failed!"
    print(f"  {label} ✓")
    return receipt

# TX 1 — Join Grav QING
print(f"\n--- TX 1: GravQING.Join(GIBS) ---")
send_tx(grav_qing.functions.Join(GIBS_ADDR), "Join Grav QING")

time.sleep(3)

# TX 2 — CHOA.Chat (terraform)
print(f"\n--- TX 2: CHOA.Chat(GravQING, msg) ---")
print(f"  Message: {TERRAFORM_MSG}")
send_tx(choa.functions.Chat(GRAV_QING, TERRAFORM_MSG), "CHOA.Chat (terraform)")

# Post-flight state
print(f"\n--- Post-flight ---")
print(f"GIBS balance (Joey):    {gibs.functions.balanceOf(JOEY_WALLET).call()/1e18:.0f}")
print(f"CHOA in YUE wallet:     {choa_tok.functions.balanceOf(JOEY_YUE).call()/1e18:.4f}")
print(f"Grav QING total supply: {grav_qing.functions.totalSupply().call()/1e18:.0f}")
print(f"Joey admitted (GIBS):   {grav_qing.functions.Admitted(GIBS_ADDR).call()}")
print("\nTerraforming complete.")
