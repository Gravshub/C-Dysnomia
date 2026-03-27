#!/usr/bin/env python3
"""Execute META.Beat() — works with any LAU/QING token on PulseChain.

Pre-requisite: SHIO tokens (Fornax, Fomalhaute, CHO) must already be at
the LAU and QING addresses. Run tx_acquire_shio.py first.

Game loop: CHEON.Su() → META.Beat() → WORLD.Code()
This script runs Beat only.

Returns: (Dione, Charge, Deimos, Yeo) — territory range and power metrics.

Usage:
  python scripts/tx_beat.py                                  # defaults (GIBS LAU, Joey wallet)
  python scripts/tx_beat.py --lau 0x1234... --qing 0x5678... # custom LAU/QING
  python scripts/tx_beat.py --wallet 0xABCD...               # custom wallet
  python scripts/tx_beat.py --waat 12345                     # custom QING Waat
"""
import argparse
from web3 import Web3
from eth_account import Account
import os, sys

# ── Defaults (Joey / GIBS) ───────────────────────────────────
DEFAULT_WALLET = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
DEFAULT_LAU    = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
DEFAULT_QING   = "0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35"
DEFAULT_WAAT   = 251913148994206487765525643443518492465195287520927385378321984475167864513

# ── CLI ──────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--lau",    default=DEFAULT_LAU,    help="LAU token address (default: GIBS)")
parser.add_argument("--qing",   default=DEFAULT_QING,   help="QING venue address (default: GIBS QING)")
parser.add_argument("--waat",   default=DEFAULT_WAAT, type=int, help="QING Waat value (default: GIBS QING Waat)")
parser.add_argument("--wallet", default=DEFAULT_WALLET, help="Wallet address (default: Joey)")
args = parser.parse_args()

SUBMIT_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ────────────────────────────────────────────────
WALLET      = Web3.to_checksum_address(args.wallet)
LAU_ADDR    = Web3.to_checksum_address(args.lau)
QING_ADDR   = Web3.to_checksum_address(args.qing)
META        = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
FORNAX      = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE  = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
CHO_TOKEN   = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")

QING_WAAT   = args.waat

# ── Private Key ──────────────────────────────────────────────
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. source .env first.")
    sys.exit(1)

account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == WALLET.lower(), "Key mismatch!"

# ── ABIs ─────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

META_ABI = [
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Beat","outputs":[
        {"name":"Dione","type":"uint256"},
        {"name":"Charge","type":"uint256"},
        {"name":"Deimos","type":"uint256"},
        {"name":"Yeo","type":"uint256"}
    ],"stateMutability":"nonpayable","type":"function"},
]

QING_ABI = [
    {"inputs":[],"name":"Waat","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
]

meta     = w3.eth.contract(address=META, abi=META_ABI)
fornax   = w3.eth.contract(address=FORNAX, abi=ERC20_ABI)
fomalh   = w3.eth.contract(address=FOMALHAUTE, abi=ERC20_ABI)
cho      = w3.eth.contract(address=CHO_TOKEN, abi=ERC20_ABI)
gibs_q   = w3.eth.contract(address=QING_ADDR, abi=QING_ABI)

def fmt(val):
    return f"{val / 1e18:.6f}"

# ── Pre-flight: Verify SHIO balances ────────────────────────
print(f"\n{'='*60}")
print(f"  PRE-FLIGHT: SHIO BALANCE CHECK")
print(f"{'='*60}")

checks = [
    ("Fornax",     fornax, "LAU",  LAU_ADDR),
    ("Fornax",     fornax, "QING", QING_ADDR),
    ("Fomalhaute", fomalh, "LAU",  LAU_ADDR),
    ("CHO",        cho,    "LAU",  LAU_ADDR),
    ("CHO",        cho,    "QING", QING_ADDR),
]

all_ok = True
for label, token, addr_name, addr in checks:
    bal = token.functions.balanceOf(addr).call()
    ok = bal > 0
    status = "OK" if ok else "ZERO!"
    print(f"  {label:12s} @ {addr_name:10s}: {fmt(bal)} [{status}]")
    if not ok:
        all_ok = False

if not all_ok:
    print("\nFATAL: Missing SHIO tokens. Run tx_acquire_shio.py first.")
    sys.exit(1)

# Verify QING Waat
qing_waat = gibs_q.functions.Waat().call()
qing_entropy = gibs_q.functions.Entropy().call()
print(f"\nQING Waat: {qing_waat}")
print(f"QING Entropy: {qing_entropy}")
assert qing_waat == QING_WAAT, f"Waat mismatch! Expected {QING_WAAT}, got {qing_waat}"

# ── Dry-run Beat ─────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  DRY-RUN: META.Beat({QING_WAAT})")
print(f"{'='*60}")

try:
    result = meta.functions.Beat(QING_WAAT).call({'from': WALLET, 'gas': 5000000})
    dione, charge, deimos, yeo = result
    print(f"\n  DRY-RUN SUCCESS!")
    print(f"  Dione:  {dione}")
    print(f"  Charge: {charge}")
    print(f"  Deimos: {deimos}")
    print(f"  Yeo:    {yeo}")
except Exception as e:
    print(f"\n  DRY-RUN FAILED: {e}")
    print(f"\n  Beat is still reverting. Check:")
    print(f"    - SHIO balances above (all must be > 0)")
    print(f"    - Enteh has SHIO balance ≈ 11/0.001/0.001 — try acquiring more")
    sys.exit(1)

# ── Execute Beat ─────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  EXECUTE: META.Beat({QING_WAAT})")
print(f"{'='*60}")

nonce     = w3.eth.get_transaction_count(WALLET)
gas_price = w3.eth.gas_price
gas_est   = meta.functions.Beat(QING_WAAT).estimate_gas({'from': WALLET})
print(f"  Nonce: {nonce}  Gas est: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")

tx = meta.functions.Beat(QING_WAAT).build_transaction({
    'from': WALLET, 'nonce': nonce,
    'gas': int(gas_est * 1.3), 'gasPrice': gas_price, 'chainId': 369,
})
signed = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"  TX sent: 0x{tx_hash.hex()}")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
print(f"  Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas used: {receipt['gasUsed']:,}")
assert receipt['status'] == 1, "Beat TX FAILED!"

# Decode return values from logs or re-call
print(f"\n  META.Beat() ✓")
print(f"  TX: 0x{tx_hash.hex()}")
print(f"  Block: {receipt['blockNumber']:,}")

# Re-read via call to get the result values (state may have changed)
print(f"\n{'='*60}")
print(f"  RESULTS")
print(f"{'='*60}")
print(f"  Dione:  {dione}")
print(f"  Charge: {charge}")
print(f"  Deimos: {deimos}")
print(f"  Yeo:    {yeo}")

pls_remaining = w3.eth.get_balance(WALLET)
print(f"\n  PLS remaining: {pls_remaining / 1e18:.2f}")
print(f"\nBeat complete! QING has been measured.")
print(f"Next step: WORLD.Code() for territory claiming (when WORLD is deployed)")
