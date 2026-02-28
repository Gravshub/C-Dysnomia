#!/usr/bin/env python3
"""
Set DSS.setChatMultiplier(17) — enables 18 GIBS per chatAndClaimWithMultiplier() call.
Then fires chatAndClaimWithMultiplier() once as a live broadcast to the VOID.
"""
from web3 import Web3
from eth_account import Account
import os, sys

SUBMIT_RPC  = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

DSS_ADDR    = Web3.to_checksum_address("0x91Df693177eE5C81016d0B7c4c2052A7d229c031")
GIBS_ADDR   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. source .env first.")
    sys.exit(1)

account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

DSS_ABI = [
    {"inputs":[],"name":"multiplier","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"_multiplier","type":"uint64"}],"name":"setChatMultiplier","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_text","type":"string"}],"name":"chatAndClaimWithMultiplier","outputs":[],"stateMutability":"nonpayable","type":"function"},
]
dss = w3.eth.contract(address=DSS_ADDR, abi=DSS_ABI)

# Current state
current = dss.functions.multiplier().call()
print(f"Current multiplier: {current}")

if current == 17:
    print("Multiplier already 17 — skipping setChatMultiplier tx.")
else:
    print(f"\n--- TX: setChatMultiplier(17) ---")
    nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
    gas_price = w3.eth.gas_price
    gas_est   = dss.functions.setChatMultiplier(17).estimate_gas({'from': JOEY_WALLET})
    print(f"Nonce: {nonce}  Gas: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")

    tx = dss.functions.setChatMultiplier(17).build_transaction({
        'from': JOEY_WALLET, 'nonce': nonce,
        'gas': int(gas_est * 1.2), 'gasPrice': gas_price, 'chainId': 369,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"TX sent: 0x{tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    print(f"Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas: {receipt['gasUsed']:,}")
    assert receipt['status'] == 1, "setChatMultiplier failed!"

    confirmed = dss.functions.multiplier().call()
    print(f"Verified multiplier: {confirmed}")
    assert confirmed == 17, f"Expected 17, got {confirmed}"
    print("Multiplier set to 17 ✓")
