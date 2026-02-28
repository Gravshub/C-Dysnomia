#!/usr/bin/env python3
"""
Execute CHEON.Su(GIBS_QING) — Preparatory step for META.Beat()

Game loop: CHEON.Su(QingAddr) → META.Beat(QingWaat) → WORLD.Code(lat, lon, QingAddr)

Su() builds YUE bar weights (Hypobar/Epibar) that prime Yue.React() inside
Ring.Eta() for the subsequent Beat call. Enteh skips Su() and calls Beat
directly — both approaches work; Su() may yield better territory metrics.

Returns: (Charge, Hypobar, Epibar)
  Charge  — ReactYue output, CHO/Xia energy level
  Hypobar — lower YUE bar weight (fed to Ring.Eta via Yue.React)
  Epibar  — upper YUE bar weight

Pre-requisites (same as Beat):
  - SHIO tokens at GIBS_LAU: Fornax > 0, Fomalhaute > 0, CHO > 0
  - SHIO tokens at GIBS_QING: Fornax > 0, CHO > 0
  - Joey's YUE wallet (SEI.Start() done — block 25,893,644) ✓

Usage:
  python scripts/tx_cheon_su.py             # dry-run then execute
  python scripts/tx_cheon_su.py --dry-run   # simulate only, no tx sent
"""
import argparse, os, sys
from web3 import Web3
from eth_account import Account

# ── CLI ──────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="CHEON.Su() — YUE bar primer")
parser.add_argument("--dry-run", action="store_true", help="Simulate only, no TX sent")
args = parser.parse_args()

# ── RPC ──────────────────────────────────────────────────────
SUBMIT_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ────────────────────────────────────────────────
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU    = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING   = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
CHEON       = Web3.to_checksum_address("0x3d23084cA3F40465553797b5138CFC456E61FB5D")
FORNAX      = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE  = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
CHO_TOKEN   = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")

# ── Private Key ──────────────────────────────────────────────
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. source .env first.")
    sys.exit(1)
account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

# ── ABIs ─────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

CHEON_ABI = [
    {"inputs":[{"name":"Qing","type":"address"}],"name":"Su",
     "outputs":[
         {"name":"Charge","type":"uint256"},
         {"name":"Hypobar","type":"uint256"},
         {"name":"Epibar","type":"uint256"}
     ],
     "stateMutability":"nonpayable","type":"function"},
]

# ── Contracts ────────────────────────────────────────────────
cheon      = w3.eth.contract(address=CHEON, abi=CHEON_ABI)
fornax     = w3.eth.contract(address=FORNAX, abi=ERC20_ABI)
fomalhaute = w3.eth.contract(address=FOMALHAUTE, abi=ERC20_ABI)
cho_token  = w3.eth.contract(address=CHO_TOKEN, abi=ERC20_ABI)

def fmt(val):
    return f"{val / 1e18:.6f}"

# ── Pre-flight: SHIO balance check ───────────────────────────
print(f"\n{'='*60}")
print(f"  PRE-FLIGHT: SHIO BALANCE CHECK")
print(f"{'='*60}")
print(f"  (Su() calls Chan.ReactYue → same SHIO requirements as Beat)")

checks = [
    ("Fornax",     fornax,     "GIBS_LAU",  GIBS_LAU),
    ("Fornax",     fornax,     "GIBS_QING", GIBS_QING),
    ("Fomalhaute", fomalhaute, "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_QING", GIBS_QING),
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
    print("\nFATAL: Missing SHIO tokens.")
    print("Run tx_full_beat_flow.py (or tx_acquire_shio_p2.py) first.")
    sys.exit(1)

print("\nSHIO balances OK.")

# ── Dry-run: CHEON.Su(GIBS_QING) ─────────────────────────────
print(f"\n{'='*60}")
print(f"  DRY-RUN: CHEON.Su({GIBS_QING})")
print(f"{'='*60}")

try:
    result = cheon.functions.Su(GIBS_QING).call({'from': JOEY_WALLET, 'gas': 5_000_000})
    charge, hypobar, epibar = result
    print(f"\n  DRY-RUN SUCCESS!")
    print(f"  Charge:  {charge}  ({fmt(charge)})")
    print(f"  Hypobar: {hypobar}  ({fmt(hypobar)})")
    print(f"  Epibar:  {epibar}  ({fmt(epibar)})")
except Exception as e:
    print(f"\n  DRY-RUN FAILED: {e}")
    print("\n  Possible causes:")
    print("    - SHIO balances insufficient (need more than dust)")
    print("    - SEI.Start() not called (YUE wallet not created)")
    print("    - Chan state not initialized for Joey's YUE")
    sys.exit(1)

if args.dry_run:
    print(f"\n[--dry-run] Stopping here. Re-run without --dry-run to execute.")
    sys.exit(0)

# ── Execute: CHEON.Su(GIBS_QING) ─────────────────────────────
print(f"\n{'='*60}")
print(f"  EXECUTE: CHEON.Su({GIBS_QING})")
print(f"{'='*60}")

nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
gas_price = w3.eth.gas_price
gas_est   = cheon.functions.Su(GIBS_QING).estimate_gas({'from': JOEY_WALLET})
print(f"  Nonce: {nonce}  Gas est: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")

tx = cheon.functions.Su(GIBS_QING).build_transaction({
    'from': JOEY_WALLET, 'nonce': nonce,
    'gas': int(gas_est * 1.3), 'gasPrice': gas_price, 'chainId': 369,
})
signed = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"  TX sent: 0x{tx_hash.hex()}")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
print(f"  Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas used: {receipt['gasUsed']:,}")
assert receipt['status'] == 1, "Su() TX FAILED!"

# ── Results ───────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RESULTS — CHEON.Su()")
print(f"{'='*60}")
print(f"  Charge:  {charge}  ({fmt(charge)})")
print(f"  Hypobar: {hypobar}  ({fmt(hypobar)})")
print(f"  Epibar:  {epibar}  ({fmt(epibar)})")
print(f"\n  TX: 0x{tx_hash.hex()}")
print(f"  Block: {receipt['blockNumber']:,}")

pls_remaining = w3.eth.get_balance(JOEY_WALLET)
print(f"\n  PLS remaining: {pls_remaining / 1e18:.2f}")
print(f"\nSu() complete! YUE bars primed for Beat.")
print(f"Next step: run tx_beat.py (or tx_full_beat_flow.py)")
