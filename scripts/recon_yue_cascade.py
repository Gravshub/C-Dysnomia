#!/usr/bin/env python3
"""
recon_yue_cascade.py — Phase 1 discovery for YUE Cascade Pump

Sub-commands (--check):
  yuan      Phase 1a: assert CHOA.Yuan(token) == bal(EOA) + 10×bal(LAU) + 40×bal(YUE)
  exits     Phase 1b: per-token YUE.hasMint() + Hong() exit feasibility
  tree      Phase 1c: re-scan V2 Federal Parent()/Debenture()/totalSupply, build children
  holdings  Phase 1d: refresh joey balances for FED/FDIC/DFM/PARADE/WM/WPLS/AFFECTION/PLS
  all       Run all four in order

Read-only. No state-changing TX. Writes:
  scripts/data/yue_exit_check.json
  scripts/data/maria_v2federal_tree.json
  scripts/data/yue_park_state.json

Spec: docs/superpowers/specs/2026-04-25-yue-cascade-pump-design.md
"""

import argparse
import json
import os
import sys
from typing import Optional

from eth_abi import encode as abi_encode
from eth_abi import decode as abi_decode
from web3 import Web3

# ─── Player identity ─────────────────────────────────────────────────────
JOEY     = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
JOEY_LAU = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_YUE = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")

# ─── Game contract addresses ─────────────────────────────────────────────
CHO      = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN     = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
CHOA     = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
V2MINTER = Web3.to_checksum_address("0xc15c5F699Daf5e1135732139f05D2c05b3EF4354")
WITHOUT  = Web3.to_checksum_address("0x173216Ed67eBF3E6767D86e8b3Ff32e0d64437bF")

# ─── Tokens ──────────────────────────────────────────────────────────────
FED        = Web3.to_checksum_address("0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff")
FDIC       = Web3.to_checksum_address("0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9")
DFM        = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
PARADE     = Web3.to_checksum_address("0xE37ACc54711562510FaFC45d8199Ee329ebBceDd")
WM         = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
WPLS       = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
AFFECTION  = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")

# Parking targets (Phase 2 inputs)
PARK_TOKENS = {"FDIC": FDIC, "PARADE": PARADE, "DFM": DFM}
HOLDING_TOKENS = {**PARK_TOKENS, "FED": FED, "WM": WM, "WPLS": WPLS, "AFFECTION": AFFECTION}

# ─── RPC ─────────────────────────────────────────────────────────────────
READ_RPC  = os.environ.get("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
w3_read   = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR  = os.path.join(REPO_ROOT, "scripts", "data")
EXIT_FILE = os.path.join(DATA_DIR, "yue_exit_check.json")
TREE_FILE = os.path.join(DATA_DIR, "maria_v2federal_tree.json")
HOLD_FILE = os.path.join(DATA_DIR, "yue_park_state.json")
V2F_INPUT = os.path.join(REPO_ROOT, "scripts", "Joystick", "data", "v2_federal_tokens.json")

# ─── Function selectors ──────────────────────────────────────────────────
SEL_BALANCE_OF  = Web3.keccak(text="balanceOf(address)")[:4]
SEL_DECIMALS    = Web3.keccak(text="decimals()")[:4]
SEL_TOTAL_SUP   = Web3.keccak(text="totalSupply()")[:4]
SEL_DEBENTURE   = Web3.keccak(text="Debenture()")[:4]
SEL_PARENT      = Web3.keccak(text="Parent()")[:4]
SEL_SYMBOL      = Web3.keccak(text="symbol()")[:4]
SEL_HAS_MINT    = Web3.keccak(text="hasMint(address)")[:4]
SEL_CHOA_YUAN   = Web3.keccak(text="Yuan(address)")[:4]
SEL_V2M_TT      = Web3.keccak(text="TreasuryTokens(address)")[:4]

# ─── Reads ───────────────────────────────────────────────────────────────
def erc20_balance(token: str, holder: str) -> int:
    data = SEL_BALANCE_OF + abi_encode(["address"], [holder])
    raw  = w3_read.eth.call({"to": token, "data": data})
    return abi_decode(["uint256"], raw)[0]

def erc20_decimals(token: str) -> int:
    raw = w3_read.eth.call({"to": token, "data": SEL_DECIMALS})
    return abi_decode(["uint8"], raw)[0]

def erc20_total_supply(token: str) -> int:
    raw = w3_read.eth.call({"to": token, "data": SEL_TOTAL_SUP})
    return abi_decode(["uint256"], raw)[0]

def erc20_symbol(token: str) -> str:
    raw = w3_read.eth.call({"to": token, "data": SEL_SYMBOL})
    return abi_decode(["string"], raw)[0]

def tt_debenture(token: str) -> bool:
    raw = w3_read.eth.call({"to": token, "data": SEL_DEBENTURE})
    return abi_decode(["bool"], raw)[0]

def tt_parent(token: str) -> str:
    raw = w3_read.eth.call({"to": token, "data": SEL_PARENT})
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])

def yue_has_mint(yue: str, token: str) -> bool:
    data = SEL_HAS_MINT + abi_encode(["address"], [token])
    raw  = w3_read.eth.call({"to": yue, "data": data})
    return abi_decode(["bool"], raw)[0]

def choa_yuan(token: str, from_addr: str) -> int:
    """CHOA.Yuan(token) — uses tx.origin under the hood, must call as joey."""
    data = SEL_CHOA_YUAN + abi_encode(["address"], [token])
    raw  = w3_read.eth.call({"to": CHOA, "data": data, "from": from_addr})
    return abi_decode(["uint256"], raw)[0]

def v2m_treasury_owner(token: str) -> str:
    data = SEL_V2M_TT + abi_encode(["address"], [token])
    raw  = w3_read.eth.call({"to": V2MINTER, "data": data})
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])

# ─── Atomic JSON writes ──────────────────────────────────────────────────
def atomic_write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp, path)

# ─── Phase 1a: Yuan sanity ───────────────────────────────────────────────
def check_yuan() -> int:
    """For each parking token, assert CHOA.Yuan == bal(EOA) + 10×bal(LAU) + 40×bal(YUE)."""
    print(f"[1a] Yuan sanity: CHOA={CHOA} from joey={JOEY}")
    fail = 0
    for sym, token in PARK_TOKENS.items():
        b_eoa = erc20_balance(token, JOEY)
        b_lau = erc20_balance(token, JOEY_LAU)
        b_yue = erc20_balance(token, JOEY_YUE)
        expected = b_eoa + 10 * b_lau + 40 * b_yue
        try:
            actual = choa_yuan(token, JOEY)
        except Exception as e:
            print(f"  {sym:8s}  Yuan() reverted: {e}")
            fail += 1
            continue
        ok = actual == expected
        print(f"  {sym:8s}  Yuan={actual}  expected={expected}  {'OK' if ok else 'MISMATCH'}")
        if not ok:
            fail += 1
    if fail:
        print(f"[1a] FAIL: {fail} mismatches — abort plan, investigate before parking")
        return 1
    print("[1a] PASS")
    return 0

# ─── Stubs for later sub-commands (filled in subsequent tasks) ───────────
def check_exits() -> int:
    raise NotImplementedError("Task 2 fills this in")

def check_tree() -> int:
    raise NotImplementedError("Task 3 fills this in")

def check_holdings() -> int:
    raise NotImplementedError("Task 4 fills this in")

# ─── CLI ─────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", required=True,
                    choices=["yuan", "exits", "tree", "holdings", "all"])
    args = ap.parse_args()

    if not w3_read.is_connected():
        print(f"ERROR: read RPC not connected: {READ_RPC}")
        return 2

    if args.check == "yuan":     return check_yuan()
    if args.check == "exits":    return check_exits()
    if args.check == "tree":     return check_tree()
    if args.check == "holdings": return check_holdings()
    if args.check == "all":
        for fn in (check_yuan, check_exits, check_tree, check_holdings):
            rc = fn()
            if rc != 0:
                print(f"halted at {fn.__name__}, rc={rc}")
                return rc
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
