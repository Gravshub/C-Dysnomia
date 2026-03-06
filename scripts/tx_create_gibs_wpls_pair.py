#!/usr/bin/env python3
"""
Create GIBS/WPLS PulseX V1 liquidity pair.
This is the Engine 2 (DSS) unlock.

GIBS LAU:  0x66a08aa12da955eb63d7ac121a88b2b210a07b03
WPLS:      0xA1077a294dDE1B09bB078844df40758a5D0f9a27
V1 Router: 0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02

Requires:
  - Joey wallet has GIBS tokens and PLS
  - Amounts: seed with ~100 GIBS and corresponding PLS value
  - Always simulate via eth_call before broadcast

Usage:
  source .env.anvil
  python3 scripts/tx_create_gibs_wpls_pair.py
"""
import os
import sys
from web3 import Web3

RPC = os.getenv("RPC_URL", os.getenv("PULSECHAIN_RPC", "http://127.0.0.1:8545"))
KEY = os.getenv("JOEY_PRIVATE_KEY") or os.getenv("DYSNOMIA_PRIVATE_KEY")
if not KEY:
    print("ERROR: Set JOEY_PRIVATE_KEY or DYSNOMIA_PRIVATE_KEY")
    sys.exit(1)

w3 = Web3(Web3.HTTPProvider(RPC))

GIBS_LAU  = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
WPLS      = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
V1_ROUTER = Web3.to_checksum_address("0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02")
V1_FACTORY = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
JOEY      = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

FACTORY_ABI = [{
    "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"}],
    "name": "getPair", "outputs": [{"type": "address"}],
    "stateMutability": "view", "type": "function"
}]

ROUTER_ABI = [{
    "inputs": [
        {"name": "token", "type": "address"},
        {"name": "amountTokenDesired", "type": "uint256"},
        {"name": "amountTokenMin", "type": "uint256"},
        {"name": "amountETHMin", "type": "uint256"},
        {"name": "to", "type": "address"},
        {"name": "deadline", "type": "uint256"},
    ],
    "name": "addLiquidityETH",
    "outputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}],
    "stateMutability": "payable", "type": "function",
}]

ERC20_ABI = [
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"type": "bool"}],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "a", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# Check if pair already exists
factory = w3.eth.contract(address=V1_FACTORY, abi=FACTORY_ABI)
pair = factory.functions.getPair(GIBS_LAU, WPLS).call()
if pair != "0x" + "0" * 40:
    print(f"GIBS/WPLS V1 pair already exists: {pair}")
    print("Engine 2 (DSS) is already unlocked.")
    sys.exit(0)

print("GIBS/WPLS pair does NOT exist — creating...")

gibs = w3.eth.contract(address=GIBS_LAU, abi=ERC20_ABI)
router = w3.eth.contract(address=V1_ROUTER, abi=ROUTER_ABI)
acct = w3.eth.account.from_key(KEY)

gibs_bal = gibs.functions.balanceOf(JOEY).call()
pls_bal = w3.eth.get_balance(JOEY)
print(f"GIBS balance: {gibs_bal / 1e18:.4f}")
print(f"PLS balance:  {pls_bal / 1e18:.0f}")

# Seed with 100 GIBS + 1000 PLS equivalent
GIBS_AMOUNT = min(gibs_bal, int(100 * 1e18))
PLS_AMOUNT = int(1000 * 1e18)

if gibs_bal == 0:
    print("ERROR: No GIBS balance. Acquire GIBS first.")
    sys.exit(1)

if pls_bal < PLS_AMOUNT + int(500 * 1e18):
    print(f"WARNING: Low PLS ({pls_bal/1e18:.0f}). May fail.")

# Step 1: Approve GIBS to router
nonce = w3.eth.get_transaction_count(JOEY)
print("Simulating approve...")
gibs.functions.approve(V1_ROUTER, GIBS_AMOUNT).call({"from": JOEY})

approve_tx = gibs.functions.approve(V1_ROUTER, GIBS_AMOUNT).build_transaction({
    "from": JOEY, "gas": 100_000, "gasPrice": w3.eth.gas_price,
    "nonce": nonce, "chainId": 369
})
signed = acct.sign_transaction(approve_tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
print(f"Approve TX: {tx_hash.hex()} status={receipt.status}")
assert receipt.status == 1, "Approve failed"

# Step 2: addLiquidityETH
nonce += 1
deadline = w3.eth.get_block("latest")["timestamp"] + 600

print("Simulating addLiquidityETH...")
router.functions.addLiquidityETH(
    GIBS_LAU, GIBS_AMOUNT, int(GIBS_AMOUNT * 0.99), int(PLS_AMOUNT * 0.99),
    JOEY, deadline
).call({"from": JOEY, "value": PLS_AMOUNT})

add_liq_tx = router.functions.addLiquidityETH(
    GIBS_LAU, GIBS_AMOUNT, int(GIBS_AMOUNT * 0.99), int(PLS_AMOUNT * 0.99),
    JOEY, deadline
).build_transaction({
    "from": JOEY, "gas": 300_000, "gasPrice": w3.eth.gas_price,
    "nonce": nonce, "chainId": 369, "value": PLS_AMOUNT
})
signed2 = acct.sign_transaction(add_liq_tx)
tx_hash2 = w3.eth.send_raw_transaction(signed2.raw_transaction)
receipt2 = w3.eth.wait_for_transaction_receipt(tx_hash2)
print(f"AddLiquidity TX: {tx_hash2.hex()} status={receipt2.status}")
if receipt2.status == 1:
    print("GIBS/WPLS pair created — Engine 2 (DSS) is now unlocked")
else:
    print("AddLiquidity failed — check balances and try again")
