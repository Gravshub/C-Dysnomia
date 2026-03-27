#!/usr/bin/env python3
"""Send a VOID broadcast via DSS.chatAndClaimWithMultiplier() — works with any wallet on PulseChain.

Usage:
  python scripts/chat_send.py --message "hello from the grid"
  python scripts/chat_send.py --message "test" --wallet 0xABCD...
  python scripts/chat_send.py --message "test" --multiplier 17
"""
import argparse
import os
import sys
import time

from web3 import Web3
from eth_account import Account

# ── Ecosystem constants (never change) ────────────────────────────────────────
SUBMIT_RPC = "https://rpc.pulsechain.com"
DSS_ADDR   = Web3.to_checksum_address("0x91Df693177eE5C81016d0B7c4c2052A7d229c031")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_WALLET     = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
DEFAULT_MULTIPLIER = 17

DSS_ABI = [
    {"inputs":[{"name":"_text","type":"string"}],"name":"chatAndClaimWithMultiplier","outputs":[],"stateMutability":"nonpayable","type":"function"},
]


def main():
    parser = argparse.ArgumentParser(
        description="Send a VOID broadcast via DSS.chatAndClaimWithMultiplier()"
    )
    parser.add_argument("--message", type=str, required=True,
                        help="Message text to broadcast (REQUIRED)")
    parser.add_argument("--wallet", type=str, default=DEFAULT_WALLET,
                        help=f"Sender wallet address (default: Joey {DEFAULT_WALLET})")
    parser.add_argument("--multiplier", type=int, default=DEFAULT_MULTIPLIER,
                        help=f"Chat multiplier (default: {DEFAULT_MULTIPLIER}, unused for now but future-proof)")
    args = parser.parse_args()

    # ── Private key lookup ────────────────────────────────────────────────────
    pkey = os.environ.get("DYSNOMIA_PRIVATE_KEY", "") or os.environ.get("MINTER_PRIVATE_KEY", "")
    if not pkey:
        print("ERROR: Neither DYSNOMIA_PRIVATE_KEY nor MINTER_PRIVATE_KEY is set.")
        print("  Set one of these environment variables before running.")
        sys.exit(1)

    account = Account.from_key(pkey)
    wallet = Web3.to_checksum_address(args.wallet)

    # Derive wallet from key rather than asserting a hardcoded match
    if account.address.lower() != wallet.lower():
        print(f"WARNING: Private key resolves to {account.address}, but --wallet is {wallet}")
        print(f"  Using derived address {account.address} as sender.")
        wallet = account.address

    w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
    print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

    dss = w3.eth.contract(address=DSS_ADDR, abi=DSS_ABI)
    msg = args.message

    print(f"\n--- TX: chatAndClaimWithMultiplier ---")
    print(f"Wallet:  {wallet}")
    print(f"Message: {msg}")
    nonce     = w3.eth.get_transaction_count(wallet)
    gas_price = w3.eth.gas_price
    gas_est   = dss.functions.chatAndClaimWithMultiplier(msg).estimate_gas({'from': wallet})
    print(f"Nonce: {nonce}  Gas: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")

    tx = dss.functions.chatAndClaimWithMultiplier(msg).build_transaction({
        'from': wallet, 'nonce': nonce,
        'gas': int(gas_est * 1.2), 'gasPrice': gas_price, 'chainId': 369,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"TX sent: 0x{tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    print(f"Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas: {receipt['gasUsed']:,}")
    assert receipt['status'] == 1, "TX failed!"
    print(f"Broadcast confirmed (+18 GIBS)")


if __name__ == "__main__":
    main()
