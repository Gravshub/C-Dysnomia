#!/usr/bin/env python3
"""
tx_yue_park.py — YUE Cascade Pump Phase 2: park EOA tokens into JOEY_YUE

Mechanism: plain ERC20.transfer(JOEY_YUE, chunk). No approval needed (sender
is the EOA, transferring its own balance). Per-chunk assertion battery
verifies CHOA.Yuan delta matches 40 × chunk_amount.

CLI:
  --token {FDIC,PARADE,DFM}   Required (except --verify)
  --amount <int>              Total amount in whole tokens (script multiplies by 10^decimals)
  --chunks <int>              Split amount into N transfers (default 4)
  --dry-run                   eth_call simulate every transfer, submit none
  --yes                       Skip per-chunk interactive confirmation
  --verify                    Print balances + Yuan reads for all parking tokens, exit

Park targets (subject to Phase 1b cap rule — adjust if exit_path_ok=false):
  Token   | EOA reserve | Park target
  --------|-------------|-------------
  DFM     |   600 M     |   5.35 B
  FDIC    |    50 B     |  65.95 T
  PARADE  |     1 T     |  95.79 T

Spec: docs/superpowers/specs/2026-04-25-yue-cascade-pump-design.md
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

from eth_abi import encode as abi_encode
from eth_abi import decode as abi_decode
from web3 import Web3
from web3.exceptions import ContractLogicError

# ─── Identity (mirrors recon_yue_cascade.py — keep in sync) ──────────────
JOEY      = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
JOEY_LAU  = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_YUE  = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
CHOA      = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
WITHOUT   = Web3.to_checksum_address("0x173216Ed67eBF3E6767D86e8b3Ff32e0d64437bF")

FDIC      = Web3.to_checksum_address("0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9")
DFM       = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
PARADE    = Web3.to_checksum_address("0xE37ACc54711562510FaFC45d8199Ee329ebBceDd")
PARK_TOKENS = {"FDIC": FDIC, "PARADE": PARADE, "DFM": DFM}

# ─── Constants ───────────────────────────────────────────────────────────
CHAIN_ID       = 369
GAS_MULT       = 2.5
GAS_PRICE_CEIL = 2_000_000 * 10**9
PLS_FLOOR      = 100_000 * 10**18
PRIORITY_FEE   = 100_000 * 10**9         # 100K Beats — see memory feedback_pulsechain_priority_fee

READ_RPC   = os.environ.get("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
SUBMIT_RPC = os.environ.get("PULSECHAIN_RPC",      "https://rpc.pulsechain.com")

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_FILE = os.path.join(REPO_ROOT, "scripts", "data", "yue_park_state.json")

# ─── Selectors ───────────────────────────────────────────────────────────
SEL_BALANCE_OF  = Web3.keccak(text="balanceOf(address)")[:4]
SEL_DECIMALS    = Web3.keccak(text="decimals()")[:4]
SEL_TRANSFER    = Web3.keccak(text="transfer(address,uint256)")[:4]
SEL_CHOA_YUAN   = Web3.keccak(text="Yuan(address)")[:4]

# ─── Web3 ────────────────────────────────────────────────────────────────
w3_read   = Web3(Web3.HTTPProvider(READ_RPC,   request_kwargs={"timeout": 30}))
w3_submit = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))

# ─── Reads ───────────────────────────────────────────────────────────────
def erc20_balance(token: str, holder: str) -> int:
    data = SEL_BALANCE_OF + abi_encode(["address"], [holder])
    raw  = w3_read.eth.call({"to": token, "data": data})
    return abi_decode(["uint256"], raw)[0]

def erc20_decimals(token: str) -> int:
    raw = w3_read.eth.call({"to": token, "data": SEL_DECIMALS})
    return abi_decode(["uint8"], raw)[0]

def choa_yuan(token: str) -> int:
    data = SEL_CHOA_YUAN + abi_encode(["address"], [token])
    raw  = w3_read.eth.call({"to": CHOA, "data": data, "from": JOEY})
    return abi_decode(["uint256"], raw)[0]

# ─── Atomic state ────────────────────────────────────────────────────────
def atomic_write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp, path)

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"parked": {}, "history": []}

# ─── --verify ────────────────────────────────────────────────────────────
def cmd_verify() -> int:
    print(f"verify @ block {w3_read.eth.block_number}")
    pls = w3_read.eth.get_balance(JOEY)
    print(f"  PLS(joey) = {pls/1e18:,.4f}  ({'OK' if pls > PLS_FLOOR else 'BELOW FLOOR'})")
    without_bal = erc20_balance(WITHOUT, JOEY)
    print(f"  WITHOUT(joey) = {without_bal}  ({'WATCHDOG TRIGGERED' if without_bal > 0 else 'clean'})")
    for sym, token in PARK_TOKENS.items():
        d = erc20_decimals(token)
        be = erc20_balance(token, JOEY)
        bl = erc20_balance(token, JOEY_LAU)
        by = erc20_balance(token, JOEY_YUE)
        yu = choa_yuan(token)
        ok = yu == be + 10*bl + 40*by
        print(f"  {sym:8s}  EOA={be/10**d:>22,.4f}  LAU={bl/10**d:>16,.4f}  YUE={by/10**d:>22,.4f}  Yuan={yu/10**d:>22,.4f}  {'OK' if ok else 'MISMATCH'}")
    return 0 if without_bal == 0 else 1

# ─── Stub for chunked transfer (Task 7 fills in) ─────────────────────────
def cmd_park(token_sym: str, total_human: int, chunks: int, dry_run: bool, yes: bool) -> int:
    raise NotImplementedError("Task 7 fills this in")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", choices=list(PARK_TOKENS.keys()))
    ap.add_argument("--amount", type=int, help="whole-token units (script applies decimals)")
    ap.add_argument("--chunks", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if not w3_read.is_connected():
        print(f"ERROR: read RPC not connected: {READ_RPC}")
        return 2

    if args.verify:
        return cmd_verify()

    if not args.token or args.amount is None:
        print("--token and --amount required (or use --verify)")
        return 2

    return cmd_park(args.token, args.amount, args.chunks, args.dry_run, args.yes)

if __name__ == "__main__":
    sys.exit(main())
