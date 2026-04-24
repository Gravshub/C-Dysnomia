#!/usr/bin/env python3
"""
tx_dfm_cycle.py — FDIC → DFM Treasury Cycle

Phases:
  --phase approve    Static MAX approvals (WM→V2Minter, FDIC→DFM)
  --phase deploy     Deploy 5 ammo tokens + FDIC→ammo + ammo→DFM approvals
  --phase cycle      Execute one 11-TX batch (DFM.mint + 5×ammo.mint + 5×DFM.Claim)

Flags:
  --n <int>          Tokens per round for cycle phase (default 10)
  --dry-run          eth_call simulate every TX, submit nothing
  --yes              Skip per-phase interactive confirmation
  --verify           Print balances + ammo state + allowances, exit

Spec: docs/superpowers/specs/2026-04-24-fdic-dfm-cycle-design.md
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

# ─── Addresses (checksummed) ─────────────────────────────────────────────
JOEY     = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
FDIC     = Web3.to_checksum_address("0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9")
DFM      = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
FED      = Web3.to_checksum_address("0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff")
WM       = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
V2MINTER = Web3.to_checksum_address("0xc15c5F699Daf5e1135732139f05D2c05b3EF4354")

# ─── Constants ───────────────────────────────────────────────────────────
CHAIN_ID       = 369
GAS_MULT       = 2.5
GAS_PRICE_CEIL = 2_000_000 * 10**9      # 2M Gwei in wei
PLS_FLOOR      = 100_000 * 10**18        # 100K PLS gas floor
MAX_UINT256    = (1 << 256) - 1
PRIORITY_FEE   = 1_000_000                # 1M wei priority tip

READ_RPC   = os.environ.get("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
SUBMIT_RPC = os.environ.get("PULSECHAIN_RPC",      "https://rpc.pulsechain.com")

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_FILE = os.path.join(REPO_ROOT, "scripts", "data", "dfm_cycle_ammo.json")

# ─── Function selectors ──────────────────────────────────────────────────
SEL_BALANCE_OF   = Web3.keccak(text="balanceOf(address)")[:4]
SEL_ALLOWANCE    = Web3.keccak(text="allowance(address,address)")[:4]
SEL_APPROVE      = Web3.keccak(text="approve(address,uint256)")[:4]
SEL_DECIMALS     = Web3.keccak(text="decimals()")[:4]
SEL_DEBENTURE    = Web3.keccak(text="Debenture()")[:4]
SEL_PARENT       = Web3.keccak(text="Parent()")[:4]
SEL_TT_MINT      = Web3.keccak(text="mint(uint256)")[:4]
SEL_TT_CLAIM     = Web3.keccak(text="Claim(address,uint256)")[:4]
SEL_V2M_NEW      = Web3.keccak(text="New(string,string,uint256,address)")[:4]
SEL_V2M_TT       = Web3.keccak(text="TreasuryTokens(address)")[:4]

# ─── Web3 clients ────────────────────────────────────────────────────────
w3_read   = Web3(Web3.HTTPProvider(READ_RPC,   request_kwargs={"timeout": 30}))
w3_submit = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))

# ─── ERC20 / TT reads (via raw eth_call to avoid contract-object overhead) ───
def erc20_balance(token: str, holder: str) -> int:
    data = SEL_BALANCE_OF + abi_encode(["address"], [holder])
    raw  = w3_read.eth.call({"to": token, "data": data})
    return abi_decode(["uint256"], raw)[0]

def erc20_allowance(token: str, owner: str, spender: str) -> int:
    data = SEL_ALLOWANCE + abi_encode(["address", "address"], [owner, spender])
    raw  = w3_read.eth.call({"to": token, "data": data})
    return abi_decode(["uint256"], raw)[0]

def tt_debenture(token: str) -> bool:
    raw = w3_read.eth.call({"to": token, "data": SEL_DEBENTURE})
    return abi_decode(["bool"], raw)[0]

def tt_parent(token: str) -> str:
    raw = w3_read.eth.call({"to": token, "data": SEL_PARENT})
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])

def v2m_treasury_owner(token: str) -> str:
    data = SEL_V2M_TT + abi_encode(["address"], [token])
    raw  = w3_read.eth.call({"to": V2MINTER, "data": data})
    return Web3.to_checksum_address(abi_decode(["address"], raw)[0])


# ─── State file I/O ──────────────────────────────────────────────────────
def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"deployed_at_block": None, "ammo": []}
    with open(STATE_FILE) as f:
        return json.load(f)

def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


# ─── --verify mode ───────────────────────────────────────────────────────
def do_verify() -> None:
    block = w3_read.eth.block_number
    print(f"Block: {block}")
    print(f"\n=== Joey Wallet ({JOEY}) ===")
    print(f"  PLS:  {w3_read.eth.get_balance(JOEY)/1e18:>22,.4f}")
    print(f"  FDIC: {erc20_balance(FDIC, JOEY)/1e18:>22,.6f}")
    print(f"  FED:  {erc20_balance(FED,  JOEY)/1e18:>22,.6f}")
    print(f"  WM:   {erc20_balance(WM,   JOEY)/1e18:>22,.6f}")
    print(f"  DFM:  {erc20_balance(DFM,  JOEY)/1e18:>22,.6f}")
    print(f"  Nonce: {w3_read.eth.get_transaction_count(JOEY)}")

    print(f"\n=== Allowances (MAX = {MAX_UINT256}) ===")
    wm_to_v2m   = erc20_allowance(WM,   JOEY, V2MINTER)
    fdic_to_dfm = erc20_allowance(FDIC, JOEY, DFM)
    print(f"  WM   → V2Minter: {wm_to_v2m}  {'(MAX)' if wm_to_v2m >= MAX_UINT256 >> 1 else '(NOT SET)'}")
    print(f"  FDIC → DFM:      {fdic_to_dfm}  {'(MAX)' if fdic_to_dfm >= MAX_UINT256 >> 1 else '(NOT SET)'}")

    state = load_state()
    print(f"\n=== Ammo state ({STATE_FILE}) ===")
    if not state.get("ammo"):
        print("  (none deployed)")
    else:
        for ammo in state["ammo"]:
            addr = ammo["address"]
            bal_fdic    = erc20_balance(FDIC, addr)
            fdic_to_a   = erc20_allowance(FDIC, JOEY, addr)
            a_to_dfm    = erc20_allowance(addr, JOEY, DFM)
            deb_now     = tt_debenture(addr)
            print(f"  {ammo['symbol']:>6} @ {addr}")
            print(f"    FDIC locked:     {bal_fdic/1e18:,.6f}")
            print(f"    Debenture:       {deb_now}")
            print(f"    FDIC → ammo:     {'(MAX)' if fdic_to_a >= MAX_UINT256 >> 1 else '(NOT SET)'}")
            print(f"    ammo → DFM:      {'(MAX)' if a_to_dfm >= MAX_UINT256 >> 1 else '(NOT SET)'}")


# ─── CLI ─────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="FDIC → DFM treasury cycle")
    parser.add_argument("--phase", choices=["approve", "deploy", "cycle"], help="phase to execute")
    parser.add_argument("--n", type=int, default=10, help="tokens per round (cycle phase)")
    parser.add_argument("--dry-run", action="store_true", help="simulate only, do not submit")
    parser.add_argument("--yes",     action="store_true", help="skip per-phase confirmation")
    parser.add_argument("--verify",  action="store_true", help="print state and exit")
    args = parser.parse_args()

    if args.verify:
        do_verify()
        return 0

    if not args.phase:
        parser.error("--phase is required unless using --verify")

    if args.phase == "approve":
        print("TODO: implement approve phase")
    elif args.phase == "deploy":
        print("TODO: implement deploy phase")
    elif args.phase == "cycle":
        print(f"TODO: implement cycle phase (N={args.n})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
