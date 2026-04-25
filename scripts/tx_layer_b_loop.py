#!/usr/bin/env python3
"""
tx_layer_b_loop.py — Run tx_layer_b_cycle.py at N=1M, K=100 in a loop with
hard inter-cycle invariant assertions. No auto-retry on failure.

CLI:
  --cycles <int>   Number of cycles to run (default 100)
  --n <int>        Tokens per round (default 1_000_000)
  --hold-back <K>  Ammo retention per round (default 100)
  --dry-run        Pass through to tx_layer_b_cycle.py
  --yes            Pass through to tx_layer_b_cycle.py
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Dict

from eth_abi import encode as abi_encode
from eth_abi import decode as abi_decode
from web3 import Web3

JOEY     = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
DFM      = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
PARADE   = Web3.to_checksum_address("0xE37ACc54711562510FaFC45d8199Ee329ebBceDd")

READ_RPC = os.environ.get("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
w3 = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAYER_B    = os.path.join(REPO_ROOT, "scripts", "tx_layer_b_cycle.py")
AMMO_STATE = os.path.join(REPO_ROOT, "scripts", "data", "layer_b_ammo.json")

SEL_BALANCE_OF = Web3.keccak(text="balanceOf(address)")[:4]

def bal(token, holder):
    data = SEL_BALANCE_OF + abi_encode(["address"], [holder])
    return abi_decode(["uint256"], w3.eth.call({"to": token, "data": data}))[0]

def snapshot(ammo_addrs) -> Dict[str, int]:
    s = {"DFM_joey": bal(DFM, JOEY), "PARADE_joey": bal(PARADE, JOEY)}
    for i, a in enumerate(ammo_addrs):
        s[f"vault_DFM_{i}"]  = bal(DFM, a)
        s[f"joey_ammo_{i}"]  = bal(a, JOEY)
    return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles",    type=int, default=100)
    ap.add_argument("--n",         type=int, default=1_000_000)
    ap.add_argument("--hold-back", type=int, default=100)
    ap.add_argument("--dry-run",   action="store_true")
    ap.add_argument("--yes",       action="store_true")
    args = ap.parse_args()

    with open(AMMO_STATE) as f:
        ammo_addrs = [Web3.to_checksum_address(a["address"]) for a in json.load(f)["ammo"]]
    if len(ammo_addrs) != 5:
        print(f"ABORT: expected 5 ammo, got {len(ammo_addrs)}")
        return 1

    N, K = args.n, args.hold_back
    expected_d_dfm    = -(5*N + 5*K) * 10**18
    expected_d_parade = (5*N) * 10**18
    expected_d_vault  = N * 10**18
    expected_d_joey_ammo = K * 10**18

    for c in range(1, args.cycles + 1):
        print(f"\n========== cycle {c}/{args.cycles}  N={N:,}  K={K} ==========")
        pre = snapshot(ammo_addrs)

        cmd = ["python3", LAYER_B, "--phase", "cycle", "--n", str(N), "--hold-back", str(K)]
        if args.dry_run: cmd.append("--dry-run")
        if args.yes:     cmd.append("--yes")
        rc = subprocess.call(cmd, cwd=REPO_ROOT)
        if rc != 0:
            print(f"ABORT: tx_layer_b_cycle exit {rc}")
            return rc

        if args.dry_run:
            print("(dry-run) skipping invariant check")
            continue

        post = snapshot(ammo_addrs)
        d_dfm    = post["DFM_joey"]    - pre["DFM_joey"]
        d_parade = post["PARADE_joey"] - pre["PARADE_joey"]
        ok = (d_dfm == expected_d_dfm) and (d_parade == expected_d_parade)
        for i in range(5):
            d_v = post[f"vault_DFM_{i}"] - pre[f"vault_DFM_{i}"]
            d_a = post[f"joey_ammo_{i}"] - pre[f"joey_ammo_{i}"]
            ok = ok and (d_v == expected_d_vault) and (d_a == expected_d_joey_ammo)
            print(f"  ammo {i}: Δvault={d_v} (exp {expected_d_vault})  Δjoey={d_a} (exp {expected_d_joey_ammo})")

        print(f"  ΔDFM_joey={d_dfm} (exp {expected_d_dfm})  ΔPARADE_joey={d_parade} (exp {expected_d_parade})")
        if not ok:
            print(f"ABORT: invariant failure at cycle {c} — DO NOT auto-retry")
            return 1

    print(f"\n[done] {args.cycles} cycles passed all invariants")
    return 0

if __name__ == "__main__":
    sys.exit(main())
