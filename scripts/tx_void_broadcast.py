#!/usr/bin/env python3
"""
Send two VOID broadcasts via DSS.chatAndClaimWithMultiplier():
  TX1 — Reply to Noumenon
  TX2 — VOID broadcast (handle hunt)
Each yields 18 GIBS.
"""
from web3 import Web3
from eth_account import Account
import os, sys, time

SUBMIT_RPC  = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

DSS_ADDR    = Web3.to_checksum_address("0x91Df693177eE5C81016d0B7c4c2052A7d229c031")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. source .env first.")
    sys.exit(1)

account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

DSS_ABI = [
    {"inputs":[{"name":"_text","type":"string"}],"name":"chatAndClaimWithMultiplier","outputs":[],"stateMutability":"nonpayable","type":"function"},
]
dss = w3.eth.contract(address=DSS_ADDR, abi=DSS_ABI)

MSG = (
    "haha Noumenon, zero cool is crash override's handle not mine. im still just Joey — working on it. "
    "but good intel on MAP.New — didnt know it was that open. T.DOLLA BILL QING sounds like money. lets build out here."
    "i need a handle, man. i dont have an identity until i have a handle. "
    "(How's -=[ Master0fDisaster ]=- sound?) but i got GIBS live, YUE vault open, QING venue deployed. "
    "3321 tokens. player 578. working on it."
)

print(f"\n--- TX: chatAndClaimWithMultiplier ---")
print(f"Message: {MSG}")
nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
gas_price = w3.eth.gas_price
gas_est   = dss.functions.chatAndClaimWithMultiplier(MSG).estimate_gas({'from': JOEY_WALLET})
print(f"Nonce: {nonce}  Gas: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")

tx = dss.functions.chatAndClaimWithMultiplier(MSG).build_transaction({
    'from': JOEY_WALLET, 'nonce': nonce,
    'gas': int(gas_est * 1.2), 'gasPrice': gas_price, 'chainId': 369,
})
signed = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"TX sent: 0x{tx_hash.hex()}")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
print(f"Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas: {receipt['gasUsed']:,}")
assert receipt['status'] == 1, "TX failed!"
print(f"Broadcast confirmed ✓  (+18 GIBS)")
