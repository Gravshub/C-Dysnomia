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
from typing import Optional

from eth_abi import encode as abi_encode
from eth_abi import decode as abi_decode
from web3 import Web3
from web3.exceptions import ContractLogicError, TimeExhausted

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
GAS_PRICE_CEIL = 3_000_000 * 10**9
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

# ─── Gas + TX submission helpers ─────────────────────────────────────────
JOEY_PK = os.environ.get("JOEY_PK")

def build_gas_params() -> dict:
    base = w3_read.eth.gas_price  # impulses (wei)
    max_fee = int(base * 2) + PRIORITY_FEE
    if max_fee > GAS_PRICE_CEIL:
        raise RuntimeError(f"max_fee {max_fee} > ceiling {GAS_PRICE_CEIL}")
    return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": PRIORITY_FEE}

def estimate_and_send(tx: dict, label: str, dry_run: bool) -> Optional[str]:
    """Simulate, estimate, sign, send. Returns tx_hash or None for dry-run."""
    try:
        w3_read.eth.call(tx)
    except ContractLogicError as e:
        print(f"  [{label}] eth_call REVERT: {e}")
        return None
    try:
        gas_est = w3_read.eth.estimate_gas(tx)
    except Exception as e:
        print(f"  [{label}] estimate_gas FAIL: {e}")
        return None
    tx["gas"]      = int(gas_est * GAS_MULT)
    tx["nonce"]    = w3_submit.eth.get_transaction_count(JOEY)
    tx["chainId"]  = CHAIN_ID
    tx.update(build_gas_params())
    if dry_run:
        print(f"  [{label}] DRY-RUN gas={gas_est} (would send w/ gas={tx['gas']})")
        return None
    if not JOEY_PK:
        print(f"  [{label}] JOEY_PK env var unset — cannot sign")
        return None
    signed = w3_submit.eth.account.sign_transaction(tx, JOEY_PK)
    tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
    tx_hash_hex = "0x" + tx_hash.hex()
    print(f"  [{label}] sent: {tx_hash_hex}")
    try:
        rcpt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    except TimeExhausted:
        print(f"  [{label}] TIMEOUT after 300s waiting for receipt: {tx_hash_hex} — investigate manually before re-running")
        raise
    if rcpt.status != 1:
        raise RuntimeError(f"  [{label}] tx reverted: {tx_hash_hex}")
    return tx_hash_hex

# ─── --verify ────────────────────────────────────────────────────────────
def cmd_verify() -> int:
    """Pre-flight safety gate. Exit 0 = safe to park; non-zero = abort."""
    EXIT_CHECK_FILE = os.path.join(REPO_ROOT, "scripts", "data", "yue_exit_check.json")
    exit_verdicts = {}
    if os.path.exists(EXIT_CHECK_FILE):
        with open(EXIT_CHECK_FILE) as f:
            exit_data = json.load(f)
        exit_verdicts = {
            sym: e.get("exit_path_ok", False)
            for sym, e in exit_data.get("tokens", {}).items()
        }

    print(f"verify @ block {w3_read.eth.block_number}")

    pls = w3_read.eth.get_balance(JOEY)
    pls_ok = pls >= PLS_FLOOR
    print(f"  PLS(joey) = {pls/1e18:,.4f}  ({'OK' if pls_ok else 'BELOW FLOOR'})")

    without_bal = erc20_balance(WITHOUT, JOEY)
    without_ok = without_bal == 0
    print(f"  WITHOUT(joey) = {without_bal}  ({'WATCHDOG TRIGGERED' if not without_ok else 'clean'})")

    if not exit_verdicts:
        print(f"  WARN: {EXIT_CHECK_FILE} missing — Phase 1b not run; cannot determine park caps")

    yuan_ok_all = True
    for sym, token in PARK_TOKENS.items():
        d = erc20_decimals(token)
        be = erc20_balance(token, JOEY)
        bl = erc20_balance(token, JOEY_LAU)
        by = erc20_balance(token, JOEY_YUE)
        yu = choa_yuan(token)
        formula_ok = yu == be + 10*bl + 40*by
        if not formula_ok:
            yuan_ok_all = False
        cap = exit_verdicts.get(sym)
        if cap is True:
            cap_str = "exit:OK (aggressive park)"
        elif cap is False:
            cap_str = "exit:ONE-WAY (cap 10%)"
        else:
            cap_str = "exit:UNKNOWN"
        print(f"  {sym:8s}  EOA={be/10**d:>22,.4f}  LAU={bl/10**d:>16,.4f}  YUE={by/10**d:>22,.4f}  Yuan={yu/10**d:>22,.4f}  {'OK' if formula_ok else 'MISMATCH'}  {cap_str}")

    all_ok = pls_ok and without_ok and yuan_ok_all
    if not all_ok:
        reasons = []
        if not pls_ok: reasons.append("PLS below floor")
        if not without_ok: reasons.append("WITHOUT triggered")
        if not yuan_ok_all: reasons.append("Yuan formula MISMATCH")
        print(f"  FAIL: {', '.join(reasons)}")
        return 1
    return 0

def cmd_park(token_sym: str, total_human: int, chunks: int, dry_run: bool, yes: bool) -> int:
    token = PARK_TOKENS[token_sym]
    decimals = erc20_decimals(token)
    total_wei = total_human * 10**decimals
    chunk_wei = total_wei // chunks

    pls = w3_read.eth.get_balance(JOEY)
    if pls < PLS_FLOOR:
        print(f"ABORT: PLS={pls/1e18:.4f} below floor {PLS_FLOOR/1e18:.0f}")
        return 1

    without_bal = erc20_balance(WITHOUT, JOEY)
    if without_bal != 0:
        print(f"ABORT: WITHOUT={without_bal} (watchdog)")
        return 1

    eoa_bal = erc20_balance(token, JOEY)
    if eoa_bal < total_wei:
        print(f"ABORT: {token_sym} EOA balance {eoa_bal} < total {total_wei}")
        return 1

    print(f"park {token_sym}: total={total_human:,} ({total_wei} wei) over {chunks} chunks (~{chunk_wei/10**decimals:,.0f} per chunk)")
    if not yes:
        ans = input("proceed? [y/N] ").strip().lower()
        if ans != "y":
            print("aborted by user")
            return 1

    state = load_state()
    state.setdefault("parked", {}).setdefault(token_sym, "0")
    state.setdefault("history", [])

    for i in range(chunks):
        # Last chunk gobbles the remainder so we don't lose dust
        wei = chunk_wei if i < chunks - 1 else (total_wei - chunk_wei * (chunks - 1))
        print(f"\n--- chunk {i+1}/{chunks}: {wei/10**decimals:,.4f} {token_sym} ---")

        # Pre-state
        be0 = erc20_balance(token, JOEY)
        by0 = erc20_balance(token, JOEY_YUE)
        yu0 = choa_yuan(token)
        print(f"  pre:  EOA={be0/10**decimals:,.4f}  YUE={by0/10**decimals:,.4f}  Yuan={yu0/10**decimals:,.4f}")

        # Watchdog re-check before each chunk
        if erc20_balance(WITHOUT, JOEY) != 0:
            print("  ABORT: WITHOUT became nonzero mid-run")
            atomic_write_json(STATE_FILE, state)
            return 1

        data = SEL_TRANSFER + abi_encode(["address", "uint256"], [JOEY_YUE, wei])
        tx = {"from": JOEY, "to": token, "value": 0, "data": data}
        tx_hash = estimate_and_send(tx, f"transfer-{i+1}", dry_run)
        if dry_run:
            print(f"  dry-run only — skipping post-state assertions")
            continue
        if tx_hash is None:
            print(f"  ABORT: tx submission failed")
            atomic_write_json(STATE_FILE, state)
            return 1

        # Post-state assertions — read from w3_submit (same node that confirmed receipt)
        # to avoid read-RPC lag producing false mismatches
        def _post_bal(t: str, h: str) -> int:
            data = SEL_BALANCE_OF + abi_encode(["address"], [h])
            return abi_decode(["uint256"], w3_submit.eth.call({"to": t, "data": data}))[0]
        def _post_yuan(t: str) -> int:
            data = SEL_CHOA_YUAN + abi_encode(["address"], [t])
            return abi_decode(["uint256"], w3_submit.eth.call({"to": CHOA, "data": data, "from": JOEY}))[0]
        be1 = _post_bal(token, JOEY)
        by1 = _post_bal(token, JOEY_YUE)
        yu1 = _post_yuan(token)
        d_e  = be1 - be0
        d_y  = by1 - by0
        d_yu = yu1 - yu0
        print(f"  post: EOA={be1/10**decimals:,.4f}  YUE={by1/10**decimals:,.4f}  Yuan={yu1/10**decimals:,.4f}")
        print(f"        Δ EOA = {d_e}  (expect {-wei})")
        print(f"        Δ YUE = {d_y}  (expect {wei})")
        print(f"        Δ Yuan = {d_yu}  (expect {40*wei})")

        if d_e != -wei or d_y != wei or d_yu != 40 * wei:
            print(f"  ABORT: assertion failed")
            state["history"].append({
                "tx": tx_hash, "chunk": i+1, "wei": str(wei),
                "delta_eoa": str(d_e), "delta_yue": str(d_y), "delta_yuan": str(d_yu),
                "asserted": False,
            })
            atomic_write_json(STATE_FILE, state)
            return 1

        state["parked"][token_sym] = str(int(state["parked"].get(token_sym, "0")) + wei)
        state["history"].append({
            "tx": tx_hash, "chunk": i+1, "wei": str(wei), "asserted": True,
            "block": w3_read.eth.block_number,
        })
        atomic_write_json(STATE_FILE, state)

    print(f"\n[done] parked {total_human:,} {token_sym} into JOEY_YUE")
    return 0

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
