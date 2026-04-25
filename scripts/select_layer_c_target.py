#!/usr/bin/env python3
"""
select_layer_c_target.py — Phase 4: rank Maria-deployed V2 Federal tokens
for use as Layer C target.

Reads:
  scripts/data/maria_v2federal_tree.json
  scripts/data/yue_park_state.json

Writes:
  scripts/data/target_choice.json

Ranking (lexicographic, descending priority):
  1. parent_reachable: True  (parent ∈ {DFM, FDIC, PARADE} OR parent==FED & joey holds FED)
  2. child_count desc        (more children = better Layer D path)
  3. is_qing_underlying      (TODO: requires QING enum — left as None for v1)
  4. total_supply asc        (smaller float = cheaper to dominate)
"""

import json
import os
import sys
from typing import Optional

from web3 import Web3

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TREE_FILE  = os.path.join(REPO_ROOT, "scripts", "data", "maria_v2federal_tree.json")
HOLD_FILE  = os.path.join(REPO_ROOT, "scripts", "data", "yue_park_state.json")
OUT_FILE   = os.path.join(REPO_ROOT, "scripts", "data", "target_choice.json")

REACHABLE_PARENTS = {
    Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E"): "DFM",
    Web3.to_checksum_address("0x812571A12330A74E2A3C1fF8953f6f3aac7a83e9"): "FDIC",
    Web3.to_checksum_address("0xE37ACc54711562510FaFC45d8199Ee329ebBceDd"): "PARADE",
}
FED = Web3.to_checksum_address("0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff")

def atomic_write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp, path)

def main():
    if not os.path.exists(TREE_FILE):
        print(f"ABORT: missing {TREE_FILE} — run recon_yue_cascade.py --check tree first")
        return 1
    if not os.path.exists(HOLD_FILE):
        print(f"ABORT: missing {HOLD_FILE} — run recon_yue_cascade.py --check holdings first")
        return 1

    with open(TREE_FILE) as f:
        tree = json.load(f)
    with open(HOLD_FILE) as f:
        hold = json.load(f)

    fed_balance_wei = int(hold["balances_wei"].get("FED", "0"))

    candidates = []
    for t in tree["tokens"]:
        parent = Web3.to_checksum_address(t["parent"])
        parent_sym = REACHABLE_PARENTS.get(parent)
        if parent == FED and fed_balance_wei > 0:
            parent_sym = "FED"
        parent_reachable = parent_sym is not None
        child_count = len(t.get("children", []))
        total_supply = int(t["total_supply"])

        # Skip self-referential targets entirely
        if parent.lower() == t["address"].lower():
            continue

        candidates.append({
            "address": t["address"],
            "symbol": t["symbol"],
            "parent": parent,
            "parent_symbol": parent_sym,
            "parent_reachable": parent_reachable,
            "debenture": t["debenture"],
            "child_count": child_count,
            "is_qing_underlying": None,    # v1: not enumerated
            "total_supply": str(total_supply),
            "deployer": t.get("deployer"),
        })

    # Ranking key: reachable first (True > False), then child_count desc, then -total_supply
    def key(c):
        return (
            0 if c["parent_reachable"] else 1,
            -c["child_count"],
            int(c["total_supply"]),
        )
    candidates.sort(key=key)

    reachable = [c for c in candidates if c["parent_reachable"]]
    if not reachable:
        winner = None
        runner_up = None
        fallback = {
            "self_deployed": True,
            "rationale": "No Maria token has reachable parent. Fall back to self-deploy with Parent=PARADE.",
        }
    else:
        winner = reachable[0]
        runner_up = reachable[1] if len(reachable) > 1 else None
        fallback = None

    out = {
        "scanned_at_block": tree["scanned_at_block"],
        "winner": winner,
        "runner_up": runner_up,
        "fallback": fallback,
        "all_candidates": candidates,
    }
    atomic_write_json(OUT_FILE, out)

    print(f"[Phase 4] {len(candidates)} candidates, {len(reachable)} reachable")
    if winner:
        print(f"  WINNER:    {winner['symbol']:10s} parent={winner['parent_symbol']}  children={winner['child_count']}  supply={int(winner['total_supply']) // 10**18:>20,d}")
    if runner_up:
        print(f"  RUNNER-UP: {runner_up['symbol']:10s} parent={runner_up['parent_symbol']}  children={runner_up['child_count']}")
    if fallback:
        print(f"  FALLBACK:  self-deploy with Parent=PARADE")
    print(f"wrote {OUT_FILE}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
