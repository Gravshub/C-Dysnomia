#!/usr/bin/env python3
"""
verify_key.py — confirm the private key in .env resolves to Joey's address.

No transaction sent. No gas spent. No RPC call needed.
Key derivation is pure local crypto (secp256k1 + keccak256).

Usage:
    source .env && python scripts/verify_key.py
    # or
    DYSNOMIA_PRIVATE_KEY=0x... python scripts/verify_key.py
"""

import os
import sys
from eth_account import Account

JOEY_ADDRESS = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"

key = os.environ.get("DYSNOMIA_PRIVATE_KEY", "").strip()
if not key:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. Run:  source .env")
    sys.exit(1)

try:
    acct = Account.from_key(key)
except Exception as e:
    print(f"ERROR: could not parse private key — {e}")
    sys.exit(1)

derived = acct.address

print(f"Derived address : {derived}")
print(f"Expected (Joey) : {JOEY_ADDRESS}")

if derived.lower() == JOEY_ADDRESS.lower():
    print("OK  Key is correct.")
else:
    print("MISMATCH  Wrong key — do NOT use this for transactions.")
    sys.exit(1)
