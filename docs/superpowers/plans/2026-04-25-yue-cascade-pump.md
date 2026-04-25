# YUE Cascade Pump Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote Joey's V2 Federal bag (FDIC + PARADE + DFM) from the 1× wallet tier to the 40× YUE tier, and deploy a Layer C cascade target that consumes the parked PARADE.

**Architecture:** Five phases gated on a recon-only Phase 1 discovery. Two new scripts under `scripts/` follow the existing `tx_*.py` prototyping pattern: `tx_yue_park.py` (Phase 2 chunked transfers with 40× delta assertions) and `tx_layer_c_cycle.py` (Phase 5 mint-claim cycle, mirror of `tx_layer_b_cycle.py`). One recon script (`recon_yue_cascade.py`) consolidates all four Phase 1 sub-checks. Two thin operational helpers (`tx_layer_b_loop.py` wrapper, `select_layer_c_target.py` ranker). State persists to `scripts/data/*.json` via atomic `os.replace()`.

**Tech Stack:** Python 3, `web3.py`, `eth_abi`, PulseChain (chain 369). Reads via `rpc-pulsechain.g4mm4.io`, submits via `rpc.pulsechain.com`. `JOEY_PK` env var for signing. EIP-1559 Type 2 gas, 100K Beats priority tip, 2.5× `estimate_gas` multiplier.

**Spec:** `docs/superpowers/specs/2026-04-25-yue-cascade-pump-design.md`

---

## File structure

**Created (code):**
- `scripts/recon_yue_cascade.py` (~400 lines) — Phase 1 read-only discovery, four `--check` sub-commands
- `scripts/tx_yue_park.py` (~300 lines) — Phase 2 chunked YUE transfers
- `scripts/tx_layer_b_loop.py` (~120 lines) — Phase 3 wrapper around existing `tx_layer_b_cycle.py`
- `scripts/select_layer_c_target.py` (~150 lines) — Phase 4 ranker, no TX
- `scripts/tx_layer_c_cycle.py` (~720 lines) — Phase 5 cycle, byte-for-byte copy of `tx_layer_b_cycle.py` with constants edited

**Created (runtime state, atomic writes):**
- `scripts/data/yue_exit_check.json` (Phase 1b output)
- `scripts/data/maria_v2federal_tree.json` (Phase 1c output)
- `scripts/data/yue_park_state.json` (Phase 1d / Phase 2 state)
- `scripts/data/target_choice.json` (Phase 4 output)
- `scripts/data/layer_c_ammo.json` (Phase 5 deploy state)

**Reused unchanged:**
- `scripts/tx_layer_b_cycle.py` (Phase 3 driver — only wrapped, not edited)
- `scripts/Joystick/data/v2_federal_tokens.json` (Phase 1c input)

**No tests.** Follows the project convention from `scripts/CLAUDE.md`: `tx_*.py` and `recon_*.py` are prototyping scripts; safety comes from `--dry-run` live-simulation against the real chain plus `--verify` read-only inspection, not unit tests. Each TX must pass `--dry-run` before being submitted.

---

## Operational task gates

Operational tasks (those that submit transactions) are clearly labeled **[OPERATIONAL]** below. They MUST:
1. Be approved by Joey before submission
2. Run `--dry-run` first and only proceed if every TX simulates clean
3. Re-read `WITHOUT.balanceOf(joey)` immediately before each submit batch — abort if nonzero
4. Re-read `eth_gasPrice` and skip if above ceiling

The plan executes in this order:
- Implementation tasks 1–4, 6, 7, 10, 12, 14: write code, dry-run only, no on-chain TX
- Operational tasks 5, 8, 9, 11, 13, 15, 16: submit TX after explicit user approval

---

### Task 1: Scaffold `recon_yue_cascade.py` with shared utilities and Phase 1a (Yuan sanity)

**Files:**
- Create: `scripts/recon_yue_cascade.py`

- [ ] **Step 1: Create the script with shared constants, RPC, ERC-20/CHOA reads, and `--check yuan` sub-command**

```python
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
```

- [ ] **Step 2: Verify connectivity and Phase 1a runs against the real chain**

Run: `JOEY_PK=dummy python3 scripts/recon_yue_cascade.py --check yuan`
Expected: prints three lines (FDIC / PARADE / DFM), each showing `Yuan=<int>  expected=<int>  OK`. Final line `[1a] PASS`. Exit 0.

If MISMATCH appears for any token, STOP — the entire plan's premise is broken; investigate `solidity/dysnomia/domain/sky/02_choa.sol:28-31` for an updated formula before proceeding.

- [ ] **Step 3: Commit**

```bash
git add scripts/recon_yue_cascade.py
git commit -m "feat(recon): scaffold YUE cascade Phase 1 + Yuan sanity check

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Phase 1b — YUE exit-mechanism check

**Files:**
- Modify: `scripts/recon_yue_cascade.py` (replace `check_exits` stub)

- [ ] **Step 1: Replace the `check_exits` stub with the real implementation**

Replace `def check_exits() -> int: raise NotImplementedError(...)` with:

```python
def check_exits() -> int:
    """
    For each parking token:
      A = YUE.hasMint(token) — Withdraw is theoretically callable
      B = at least one QING returns non-zero rate with `token` as SpendAsset (Hong path)

    Decision rule:
      A or B  -> "exit_path_ok": True  -> aggressive parking allowed
      neither -> "exit_path_ok": False -> cap parking at 10% of bag

    Note: B requires QING enumeration. We use the v2_federal_tokens.json input as
    a proxy for the QING universe (each V2 Federal token may anchor a QING). For a
    more thorough scan, future work can enumerate from MAP/CHOA. For Phase 1b we
    accept that 'B' may be undercounted — the safer side; we'd just over-cap.
    """
    print(f"[1b] YUE exit-mechanism check on JOEY_YUE={JOEY_YUE}")

    if not os.path.exists(V2F_INPUT):
        print(f"  WARN: {V2F_INPUT} missing; B-check will be empty")
        candidate_qings = []
    else:
        with open(V2F_INPUT) as f:
            v2f = json.load(f)
        candidate_qings = [Web3.to_checksum_address(t["address"]) for t in v2f.get("tokens", [])]

    SEL_GETRATE = Web3.keccak(text="GetAssetRate(address,address)")[:4]

    out = {"checked_at_block": w3_read.eth.block_number, "tokens": {}}
    for sym, token in PARK_TOKENS.items():
        try:
            has_mint = yue_has_mint(JOEY_YUE, token)
        except Exception as e:
            print(f"  {sym}: hasMint reverted ({e}) — assuming False")
            has_mint = False

        hong_paths = []
        for qing in candidate_qings:
            data = SEL_GETRATE + abi_encode(["address", "address"], [qing, token])
            try:
                raw = w3_read.eth.call({"to": JOEY_YUE, "data": data})
                rate = abi_decode(["uint256"], raw)[0]
                if rate > 0:
                    hong_paths.append({"qing": qing, "rate": str(rate)})
            except Exception:
                # GetAssetRate reverts when pair invalid — that's fine, just no path
                pass

        exit_ok = has_mint or len(hong_paths) > 0
        verdict = "OK" if exit_ok else "ONE-WAY (cap 10%)"
        print(f"  {sym:8s}  hasMint={has_mint}  hong_paths={len(hong_paths)}  -> {verdict}")
        out["tokens"][sym] = {
            "address": token,
            "has_mint": has_mint,
            "hong_paths": hong_paths,
            "exit_path_ok": exit_ok,
        }

    atomic_write_json(EXIT_FILE, out)
    print(f"[1b] wrote {EXIT_FILE}")
    return 0
```

- [ ] **Step 2: Run against the real chain**

Run: `python3 scripts/recon_yue_cascade.py --check exits`
Expected: three lines printed, one per token, each ending in `OK` or `ONE-WAY (cap 10%)`. File `scripts/data/yue_exit_check.json` written. Exit 0.

- [ ] **Step 3: Inspect the output**

Run: `cat scripts/data/yue_exit_check.json`
Expected: JSON with `checked_at_block` and a `tokens` map keyed by symbol, each entry containing `address`, `has_mint`, `hong_paths` array, `exit_path_ok` boolean.

- [ ] **Step 4: Commit**

```bash
git add scripts/recon_yue_cascade.py scripts/data/yue_exit_check.json
git commit -m "feat(recon): YUE exit-mechanism check (Phase 1b)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Phase 1c — V2 Federal tree re-scan

**Files:**
- Modify: `scripts/recon_yue_cascade.py` (replace `check_tree` stub)

- [ ] **Step 1: Replace the `check_tree` stub**

```python
def check_tree() -> int:
    """
    Re-scan V2 Federal tokens from v2_federal_tokens.json:
      - Parent() (correct the "FED/BAR chain" placeholder)
      - Debenture()
      - totalSupply()
      - decimals()
      - V2Minter.TreasuryTokens(token) -> deployer
    Then build a 'children' array per token by joining each token against
    every other token's Parent.

    Note: we do NOT scan V2Minter.New() events here — the v2_federal_tokens.json
    universe is treated as authoritative. If new Maria tokens land later, the
    canopy/phreak intelligence files surface them; rebuild this file then.
    """
    print(f"[1c] V2 Federal tree re-scan from {V2F_INPUT}")
    if not os.path.exists(V2F_INPUT):
        print(f"  ERROR: input missing: {V2F_INPUT}")
        return 1
    with open(V2F_INPUT) as f:
        v2f = json.load(f)

    tokens_in = v2f.get("tokens", [])
    print(f"  scanning {len(tokens_in)} tokens")

    enriched = []
    for entry in tokens_in:
        addr = Web3.to_checksum_address(entry["address"])
        sym  = entry.get("symbol", "?")
        try:
            parent = tt_parent(addr)
            deb    = tt_debenture(addr)
            sup    = erc20_total_supply(addr)
            dec    = erc20_decimals(addr)
        except Exception as e:
            print(f"  {sym} ({addr}): read failed: {e}")
            continue
        try:
            deployer = v2m_treasury_owner(addr)
        except Exception:
            deployer = None
        enriched.append({
            "address": addr,
            "symbol": sym,
            "parent": parent,
            "debenture": deb,
            "total_supply": str(sup),
            "decimals": dec,
            "deployer": deployer,
            "pls_per_token": entry.get("pls_per_token"),
            "self_balance": entry.get("selfBalance"),
        })
        print(f"  {sym:10s} parent={parent[:10]}…  Deb={deb}  sup={sup // 10**dec:>20d}  deployer={deployer[:10] if deployer else 'none'}…")

    # Build children
    by_addr = {t["address"]: t for t in enriched}
    for t in enriched:
        t["children"] = [
            {"address": c["address"], "symbol": c["symbol"]}
            for c in enriched
            if c["parent"] == t["address"] and c["address"] != t["address"]
        ]

    out = {
        "scanned_at_block": w3_read.eth.block_number,
        "v2minter": V2MINTER,
        "tokens": enriched,
    }
    atomic_write_json(TREE_FILE, out)
    print(f"[1c] wrote {TREE_FILE} with {len(enriched)} tokens")
    return 0
```

- [ ] **Step 2: Run against the real chain**

Run: `python3 scripts/recon_yue_cascade.py --check tree`
Expected: ~14 lines printed (one per token), parent shown for each. File `scripts/data/maria_v2federal_tree.json` written. Exit 0.

- [ ] **Step 3: Spot-check that PARADE's Parent is now DFM (corrects the prior `"FED/BAR chain"` placeholder)**

Run: `python3 -c "import json; d=json.load(open('scripts/data/maria_v2federal_tree.json')); p=[t for t in d['tokens'] if t['symbol']=='PARADE'][0]; print('PARADE parent:', p['parent'])"`
Expected: `PARADE parent: 0x51160F352ED148C89d48dfe6384Edd07aFA24E0E` (= DFM).

If it prints anything else, the on-chain `Parent()` reader is wrong — investigate before continuing.

- [ ] **Step 4: Commit**

```bash
git add scripts/recon_yue_cascade.py scripts/data/maria_v2federal_tree.json
git commit -m "feat(recon): V2 Federal tree re-scan with corrected parents (Phase 1c)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Phase 1d — Holdings refresh

**Files:**
- Modify: `scripts/recon_yue_cascade.py` (replace `check_holdings` stub)

- [ ] **Step 1: Replace the `check_holdings` stub**

```python
def check_holdings() -> int:
    """Refresh joey balances for every token relevant to parking + cascade decisions."""
    print(f"[1d] holdings refresh for joey={JOEY}")
    out = {
        "scanned_at_block": w3_read.eth.block_number,
        "joey": JOEY,
        "joey_lau": JOEY_LAU,
        "joey_yue": JOEY_YUE,
        "balances_wei": {},
        "balances_human": {},
    }
    pls_wei = w3_read.eth.get_balance(JOEY)
    out["balances_wei"]["PLS"]   = str(pls_wei)
    out["balances_human"]["PLS"] = pls_wei / 10**18
    print(f"  {'PLS':10s} {pls_wei / 10**18:>22,.4f}")

    for sym, token in HOLDING_TOKENS.items():
        try:
            bal = erc20_balance(token, JOEY)
            dec = erc20_decimals(token)
        except Exception as e:
            print(f"  {sym}: read failed: {e}")
            out["balances_wei"][sym] = "0"
            out["balances_human"][sym] = 0.0
            continue
        out["balances_wei"][sym]   = str(bal)
        out["balances_human"][sym] = bal / 10**dec
        print(f"  {sym:10s} {bal / 10**dec:>22,.4f}")

    # Watchdog
    try:
        without_bal = erc20_balance(WITHOUT, JOEY)
    except Exception:
        without_bal = 0
    out["balances_wei"]["WITHOUT"]   = str(without_bal)
    out["balances_human"]["WITHOUT"] = without_bal / 10**18
    print(f"  {'WITHOUT':10s} {without_bal / 10**18:>22,.4f}  {'WATCHDOG TRIGGERED' if without_bal > 0 else 'clean'}")

    atomic_write_json(HOLD_FILE, out)
    print(f"[1d] wrote {HOLD_FILE}")
    return 1 if without_bal > 0 else 0
```

- [ ] **Step 2: Run against the real chain**

Run: `python3 scripts/recon_yue_cascade.py --check holdings`
Expected: prints PLS + 7 token balances + WITHOUT line. WITHOUT must show `clean`. File `scripts/data/yue_park_state.json` written. Exit 0.

If WITHOUT shows `WATCHDOG TRIGGERED` (nonzero balance), STOP — the watchdog returned 1; surface to user before any other action.

- [ ] **Step 3: Compare against spec recon and CLAUDE.md**

The spec lists FDIC ≈ 66T, PARADE ≈ 96.79T, DFM ≈ 5.95B, PLS ≈ 1.05M as of 2026-04-25. Output should be in the same order of magnitude. Significant divergence means either the spec is stale or this script is wrong — investigate before continuing to parking.

- [ ] **Step 4: Commit**

```bash
git add scripts/recon_yue_cascade.py scripts/data/yue_park_state.json
git commit -m "feat(recon): holdings refresh + WITHOUT watchdog (Phase 1d)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: **[OPERATIONAL]** Run all four Phase 1 sub-checks and confirm gate

**Files:** none modified (state files already produced by Tasks 1–4 individually).

This task is a single end-to-end run that confirms the full Phase 1 gate produces the expected outputs in one shot. Required before any state-changing TX.

- [ ] **Step 1: Get user approval**

Ask: "Phase 1 is read-only. Approve running `--check all` against the real chain?"
Wait for explicit yes.

- [ ] **Step 2: Run the consolidated check**

Run: `python3 scripts/recon_yue_cascade.py --check all`
Expected: four sub-phases run in order, all PASS / OK output, exit 0. Three JSON files updated.

- [ ] **Step 3: Decide on parking caps from `yue_exit_check.json`**

For each token, read `exit_path_ok`. If false for any token, that token's Phase 2 park target is capped at 10% of EOA balance (per spec Phase 2 sizing rule). Document the actual targets in a comment block at the top of `tx_yue_park.py` when you write it (Task 6).

- [ ] **Step 4: Commit if any state file changed**

Run: `git status -s scripts/data/`
If diffs present:
```bash
git add scripts/data/yue_exit_check.json scripts/data/maria_v2federal_tree.json scripts/data/yue_park_state.json
git commit -m "chore(recon): refresh Phase 1 state at $(date -u +%Y-%m-%dT%H:%M:%SZ)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Scaffold `tx_yue_park.py` with `--verify` mode

**Files:**
- Create: `scripts/tx_yue_park.py`

- [ ] **Step 1: Create the script**

```python
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
```

- [ ] **Step 2: Run --verify**

Run: `python3 scripts/tx_yue_park.py --verify`
Expected: prints PLS + WITHOUT + 3 token rows. Each token row shows EOA / LAU / YUE / Yuan and ends in `OK`. Exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/tx_yue_park.py
git commit -m "feat(park): scaffold tx_yue_park.py with --verify mode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Implement chunked transfer with assertion battery

**Files:**
- Modify: `scripts/tx_yue_park.py` (replace `cmd_park` stub, add gas/sign helpers)

- [ ] **Step 1: Add gas params and TX submission helpers above `cmd_park`**

Insert this block between `def load_state()` and `def cmd_verify()`:

```python
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
    print(f"  [{label}] sent: 0x{tx_hash.hex()}")
    rcpt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if rcpt.status != 1:
        raise RuntimeError(f"  [{label}] tx reverted: 0x{tx_hash.hex()}")
    return "0x" + tx_hash.hex()
```

- [ ] **Step 2: Replace the `cmd_park` stub**

```python
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

        # Post-state assertions
        be1 = erc20_balance(token, JOEY)
        by1 = erc20_balance(token, JOEY_YUE)
        yu1 = choa_yuan(token)
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
```

- [ ] **Step 3: Dry-run a tiny park (1 token unit) to confirm the flow**

Run: `python3 scripts/tx_yue_park.py --token DFM --amount 1 --chunks 1 --dry-run --yes`
Expected: prints pre-state, "DRY-RUN gas=…", "dry-run only — skipping post-state assertions", "[done] parked 1 DFM …". Exit 0.

If it fails to simulate, debug before running live.

- [ ] **Step 4: Commit**

```bash
git add scripts/tx_yue_park.py
git commit -m "feat(park): chunked YUE deposit with 40× Yuan delta assertions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: **[OPERATIONAL]** Sentinel pass — park 1% per token

**Files:** none modified. Operational TX only.

The sentinel chunk validates the assertion battery against the real chain before scaling.

- [ ] **Step 1: Compute 1% values from `yue_park_state.json` and `yue_exit_check.json`**

Run: `python3 -c "
import json
hold = json.load(open('scripts/data/yue_park_state.json'))['balances_human']
exit = json.load(open('scripts/data/yue_exit_check.json'))['tokens']
caps = {'FDIC': 65_950_000_000_000, 'PARADE': 95_790_000_000_000, 'DFM': 5_350_000_000}
for sym in ('FDIC','PARADE','DFM'):
    eok = exit[sym]['exit_path_ok']
    target = caps[sym] if eok else int(hold[sym] * 0.10)
    sentinel = max(1, target // 100)
    print(f'{sym}: exit_ok={eok}  target={target:,}  sentinel(1%)={sentinel:,}')
"`
Expected: three lines, one per token. Note the sentinel value for each — used in step 2.

- [ ] **Step 2: Get user approval for the sentinel parking**

Ask: "Sentinel parking will transfer 1% of the planned park-target for each of FDIC, PARADE, DFM into JOEY_YUE. Total 3 TX. Approve?"
Wait for explicit yes.

- [ ] **Step 3: Dry-run all three**

Run (substituting `<sentinel>` with the value from Step 1):
```bash
python3 scripts/tx_yue_park.py --token FDIC   --amount <sentinel> --chunks 1 --dry-run --yes
python3 scripts/tx_yue_park.py --token PARADE --amount <sentinel> --chunks 1 --dry-run --yes
python3 scripts/tx_yue_park.py --token DFM    --amount <sentinel> --chunks 1 --dry-run --yes
```
Expected: each prints `DRY-RUN gas=…` and exits 0. If any fails, halt and investigate.

- [ ] **Step 4: Submit live, one at a time, with full assertion check**

```bash
python3 scripts/tx_yue_park.py --token FDIC   --amount <sentinel> --chunks 1 --yes
python3 scripts/tx_yue_park.py --token PARADE --amount <sentinel> --chunks 1 --yes
python3 scripts/tx_yue_park.py --token DFM    --amount <sentinel> --chunks 1 --yes
```
Expected per run: pre-state, `[transfer-1] sent: 0x…`, post-state, three Δ lines all matching expected, `[done] parked …`.

If any assertion fails, the script aborts and the state file records `asserted: false`. Investigate before scaling.

- [ ] **Step 5: Commit state**

```bash
git add scripts/data/yue_park_state.json
git commit -m "chore(park): sentinel chunk landed for FDIC/PARADE/DFM

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: **[OPERATIONAL]** Full Phase 2 parking

**Files:** none modified. Operational TX only.

Park the remaining 99% of each token in 4 chunks per token (12 TX total).

- [ ] **Step 1: Get user approval**

Ask: "Phase 2 full parking: 4 chunks × 3 tokens = 12 TX, moving up to ~5.35B DFM, ~65.95T FDIC, ~95.79T PARADE into JOEY_YUE. Approve?"
Wait for explicit yes.

- [ ] **Step 2: Compute remaining-99% amounts**

Same caps as Task 8 Step 1 minus the sentinel already parked. For simplicity, use the full target less the sentinel:
- FDIC: cap − sentinel
- PARADE: cap − sentinel
- DFM: cap − sentinel

(The exact integer math is fine; chunks=4 will split evenly with the last chunk taking the remainder.)

- [ ] **Step 3: Dry-run each**

```bash
python3 scripts/tx_yue_park.py --token FDIC   --amount <fdic_remainder>   --chunks 4 --dry-run --yes
python3 scripts/tx_yue_park.py --token PARADE --amount <parade_remainder> --chunks 4 --dry-run --yes
python3 scripts/tx_yue_park.py --token DFM    --amount <dfm_remainder>    --chunks 4 --dry-run --yes
```
Expected: 12 dry-run lines per token (4 chunks × 1 line each). All exit 0.

- [ ] **Step 4: Submit live, in series, monitoring for any abort**

```bash
python3 scripts/tx_yue_park.py --token FDIC   --amount <fdic_remainder>   --chunks 4 --yes
python3 scripts/tx_yue_park.py --token PARADE --amount <parade_remainder> --chunks 4 --yes
python3 scripts/tx_yue_park.py --token DFM    --amount <dfm_remainder>    --chunks 4 --yes
```
Expected: 4 chunks per token, each with passing assertions. Final state in `yue_park_state.json` shows full target parked.

If a single chunk fails its assertion, stop, investigate, do NOT auto-retry.

- [ ] **Step 5: Confirm final state via `--verify`**

Run: `python3 scripts/tx_yue_park.py --verify`
Expected: each token's YUE balance is at the target (within ~1% sentinel + dust); each Yuan row ends in `OK`.

- [ ] **Step 6: Commit state**

```bash
git add scripts/data/yue_park_state.json
git commit -m "chore(park): Phase 2 full parking complete

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Build `tx_layer_b_loop.py` wrapper

**Files:**
- Create: `scripts/tx_layer_b_loop.py`

- [ ] **Step 1: Create the wrapper**

```python
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
```

- [ ] **Step 2: Dry-run a single cycle**

Run: `python3 scripts/tx_layer_b_loop.py --cycles 1 --dry-run --yes`
Expected: prints `========== cycle 1/1  N=1,000,000  K=100 ==========`, then `tx_layer_b_cycle.py` dry-run output, then `(dry-run) skipping invariant check`. Exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/tx_layer_b_loop.py
git commit -m "feat(layer_b): wrapper loop with hard inter-cycle invariant assertions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: **[OPERATIONAL]** Phase 3 — run 100 Layer B cycles in tmux

**Files:** none modified. Operational only.

Long-running session — do NOT background-fork from a one-off shell call.

- [ ] **Step 1: Confirm DFM EOA reserve**

Run: `python3 scripts/tx_yue_park.py --verify`
Expected: DFM EOA shows ≥ 600 M (the Phase 2 reserve).

If less, top up before continuing — the loop needs 500.05 M DFM.

- [ ] **Step 2: Get user approval**

Ask: "Phase 3 Layer B loop: 100 cycles × 11 TX = 1,100 TX, ≈3.5 hours, ≈50 PLS gas, consumes ~500 M DFM, produces ~500 M PARADE + 10K of each 幹B. Approve?"
Wait for explicit yes.

- [ ] **Step 3: Open tmux and start the loop**

```bash
tmux new-session -d -s layerB "python3 scripts/tx_layer_b_loop.py --cycles 100 --n 1000000 --hold-back 100 --yes 2>&1 | tee /tmp/layer_b_loop.log"
tmux ls
```
Expected: `layerB: 1 windows ...` printed.

- [ ] **Step 4: Monitor progress**

Run periodically: `tail -50 /tmp/layer_b_loop.log`
Expected: cycle counter advancing, each cycle showing 5 ammo lines + summary line, all assertions passing.

If the log shows `ABORT: invariant failure`, the script halted; investigate before restarting.

- [ ] **Step 5: Wait for completion**

Run: `tmux attach -t layerB` (Ctrl-B then D to detach; final line `[done] 100 cycles passed all invariants` indicates success).

- [ ] **Step 6: Verify final state**

Run: `python3 scripts/tx_yue_park.py --verify`
Expected: DFM EOA decreased by ~500.05 M; PARADE EOA increased by ~500 M.

- [ ] **Step 7: Commit any state changes**

Run: `git status -s scripts/data/`
If `layer_b_ammo.json` changed, commit:
```bash
git add scripts/data/layer_b_ammo.json
git commit -m "chore(layer_b): 100-cycle production run complete

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Build `select_layer_c_target.py` ranker

**Files:**
- Create: `scripts/select_layer_c_target.py`

- [ ] **Step 1: Create the script**

```python
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
```

- [ ] **Step 2: Run it**

Run: `python3 scripts/select_layer_c_target.py`
Expected: prints "N candidates, M reachable" + WINNER + RUNNER-UP lines (or FALLBACK if none reachable). File `scripts/data/target_choice.json` written. Exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/select_layer_c_target.py scripts/data/target_choice.json
git commit -m "feat(layer_c): target selection ranker (Phase 4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: **[OPERATIONAL]** Phase 4 — confirm target choice with user

**Files:** none modified.

- [ ] **Step 1: Display the choice**

Run: `python3 -c "
import json
d = json.load(open('scripts/data/target_choice.json'))
w = d.get('winner') or d.get('fallback')
print(json.dumps(w, indent=2))
print('runner_up:', json.dumps(d.get('runner_up'), indent=2))
"`

- [ ] **Step 2: Get user approval**

Ask: "Phase 4 selected target = `<winner symbol>` (parent=`<parent_symbol>`, children=`<n>`). Runner-up = `<runner_up symbol>`. Approve this target for Phase 5 deploy? Or override?"

If user overrides, edit `scripts/data/target_choice.json` to swap `winner` and `runner_up` (or specify a different candidate). Re-confirm with user.

- [ ] **Step 3: Commit any override**

If `target_choice.json` was edited:
```bash
git add scripts/data/target_choice.json
git commit -m "chore(layer_c): manual target override per user

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Create `tx_layer_c_cycle.py` (mirror of Layer B)

**Files:**
- Create: `scripts/tx_layer_c_cycle.py`

- [ ] **Step 1: Copy the Layer B script verbatim**

Run: `cp scripts/tx_layer_b_cycle.py scripts/tx_layer_c_cycle.py`

- [ ] **Step 2: Read the chosen target from `target_choice.json` and apply edits**

Read: `cat scripts/data/target_choice.json` — note `winner.address` (TARGET) and `winner.parent` (TARGET_PARENT).

Apply these edits to `scripts/tx_layer_c_cycle.py` (use Edit tool with exact strings for each):

(a) Replace the docstring header. Old:
```python
"""
tx_layer_b_cycle.py — DFM → PARADE Treasury Cycle (Layer B)

Stage 2 of the FDIC→DFM→PARADE cascade. Cycle uses 5 self-deployed ammo
(幹B01-B05, Parent=DFM, Debenture=true) to pump DFM into PARADE (Maria's
pre-existing V2 Federal token whose Parent is DFM).
```
New (substitute `<TARGET_SYM>` and `<TARGET_PARENT_SYM>` from `target_choice.json`):
```python
"""
tx_layer_c_cycle.py — <TARGET_PARENT_SYM> → <TARGET_SYM> Treasury Cycle (Layer C)

Stage 3 of the FDIC→DFM→PARADE→<TARGET_SYM> cascade. Cycle uses 5 self-deployed ammo
(幹C01-C05, Parent=<TARGET_PARENT_SYM>, Debenture=true) to pump <TARGET_PARENT_SYM>
into <TARGET_SYM>.
```

(b) Replace the address constants. Old:
```python
DFM      = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
PARADE   = Web3.to_checksum_address("0xE37ACc54711562510FaFC45d8199Ee329ebBceDd")
```
New (substitute actual addresses from `target_choice.json`):
```python
TARGET_PARENT = Web3.to_checksum_address("<winner.parent address>")
TARGET        = Web3.to_checksum_address("<winner.address>")
```

(c) Rename ALL remaining occurrences of `DFM` to `TARGET_PARENT` and `PARADE` to `TARGET` (use Edit's `replace_all`):
- `replace_all` `DFM` → `TARGET_PARENT`  (apply only to identifier usages — ammo symbol strings like `"幹B"` should not change to `"幹C"` via this; do that separately)
- `replace_all` `PARADE` → `TARGET`

(d) Rename ammo symbols: `replace_all` `"幹 B0` → `"幹 C0` and `"幹B0` → `"幹C0` (covers the Solidity-side names and Python-side display strings).

(e) Change the state file path. Old:
```python
STATE_FILE = os.path.join(REPO_ROOT, "scripts", "data", "layer_b_ammo.json")
```
New:
```python
STATE_FILE = os.path.join(REPO_ROOT, "scripts", "data", "layer_c_ammo.json")
```

(f) Update the `Plan:` line in the module docstring. Old:
```python
Plan: /home/joey/.claude/plans/nested-noodling-garden.md
```
New:
```python
Plan: docs/superpowers/plans/2026-04-25-yue-cascade-pump.md
```

- [ ] **Step 3: Smoke test the script with `--verify`**

Run: `python3 scripts/tx_layer_c_cycle.py --verify`
Expected: prints balances + (empty) ammo state. No errors. Exit 0.

If `--verify` errors out with a missing state file, that's normal at first run — but a NameError or AttributeError indicates the rename was incomplete. Re-check the diff and fix.

- [ ] **Step 4: Commit**

```bash
git add scripts/tx_layer_c_cycle.py
git commit -m "feat(layer_c): mirror tx_layer_b_cycle.py for Layer C target

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: **[OPERATIONAL]** Phase 5 approve + deploy + probe

**Files:** runtime state only (`scripts/data/layer_c_ammo.json`).

Same operational pattern as Layer B (existing `nested-noodling-garden.md` plan).

- [ ] **Step 1: Confirm prerequisites**

- WM balance ≥ 5 (one per ammo deploy): `python3 -c "from scripts.tx_layer_c_cycle import erc20_balance, WM, JOEY; print(erc20_balance(WM, JOEY) / 1e18)"` — note: this requires `tx_layer_c_cycle.py` to be importable. If import errors, just rely on `--verify` output from Task 14 Step 3.
- TARGET_PARENT EOA balance ≥ 10 (for the probe `mint(1)` + ammo seed `mint(1)`).

- [ ] **Step 2: Get user approval for `--phase approve`**

Ask: "Layer C `--phase approve` will issue ≤2 MAX approvals (WM→V2Minter if needed, TARGET_PARENT→TARGET). Approve?"

- [ ] **Step 3: Dry-run + submit approve phase**

```bash
python3 scripts/tx_layer_c_cycle.py --phase approve --dry-run --yes
python3 scripts/tx_layer_c_cycle.py --phase approve --yes
```
Expected: dry-run shows 0–2 approvals; submit lands them.

- [ ] **Step 4: Get user approval for `--phase deploy`**

Ask: "Layer C `--phase deploy`: 5 ammo deploys + 10 approvals = 15 TX, costs 5 WM. Approve?"

- [ ] **Step 5: Dry-run + submit deploy phase**

```bash
python3 scripts/tx_layer_c_cycle.py --phase deploy --dry-run --yes
python3 scripts/tx_layer_c_cycle.py --phase deploy --yes
```
Expected: 5 ammo addresses written to `scripts/data/layer_c_ammo.json`, each with `debenture_verified: true` and `parent` matching TARGET_PARENT.

- [ ] **Step 6: Get user approval for `--phase probe`**

Ask: "Layer C `--phase probe`: 1 mint + 1 claim at amount=1 to verify TARGET accepts our 幹C ammo. Approve?"

- [ ] **Step 7: Dry-run + submit probe phase**

```bash
python3 scripts/tx_layer_c_cycle.py --phase probe --dry-run --yes
python3 scripts/tx_layer_c_cycle.py --phase probe --yes
```
Expected: TARGET balance increases by 1, 幹C01 balance returns to 0 after Claim, state file updates `probe_verified: true`.

If the probe Claim reverts, the chosen target's `Claim()` doesn't accept our ammo — switch to the runner-up (Task 13) and restart Phase 5 deploy with new ammo (NB: ammo cannot be repurposed if the runner-up's parent differs; see spec stop conditions).

- [ ] **Step 8: Commit deploy state**

```bash
git add scripts/data/layer_c_ammo.json scripts/tx_layer_c_cycle.py
git commit -m "chore(layer_c): deploy + probe complete

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: **[OPERATIONAL]** Phase 5 first 10 production cycles

**Files:** runtime state only.

- [ ] **Step 1: Confirm PARADE EOA reserve**

Run: `python3 scripts/tx_yue_park.py --verify`
Expected: PARADE EOA shows ≥ 50 M (10 cycles × 5,000,500 PARADE/cycle = 50.005 M).

- [ ] **Step 2: Get user approval**

Ask: "Phase 5 first 10 cycles: 10 × 11 TX = 110 TX, ~5 PLS gas, consumes ~50 M PARADE, produces ~50 M TARGET. Slow run with full inter-cycle verification. Approve?"

- [ ] **Step 3: Dry-run a single cycle**

Run: `python3 scripts/tx_layer_c_cycle.py --phase cycle --n 1000000 --hold-back 100 --dry-run --yes`
Expected: 11 dry-run lines, all OK. Exit 0.

- [ ] **Step 4: Run 10 cycles serially with manual verification between each**

There is no Layer C wrapper script (we will build one only after Layer C stabilises — see "Out of scope" in spec). For the first 10 cycles, run by hand:

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do
  echo "=== cycle $i ==="
  python3 scripts/tx_layer_c_cycle.py --phase cycle --n 1000000 --hold-back 100 --yes || break
  python3 scripts/tx_layer_c_cycle.py --verify
done
```
Expected: 10 cycles, each printing pre/post balances and Δ assertions matching `5N+5K`/`5N`/`N`/`K` per the spec.

If any cycle aborts, STOP and investigate before continuing. Do not auto-retry.

- [ ] **Step 5: Commit final state**

```bash
git add scripts/data/layer_c_ammo.json
git commit -m "chore(layer_c): 10-cycle production run complete

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Memory update**

Per spec persistence section, write the following memory files:

`/home/joey/.claude/projects/-opt-joystick-repo/memory/project_layer_c_cycle.md`:
```markdown
---
name: Layer C cascade live
description: Layer C TARGET cycle deployed and verified, N ammo (幹C01-05) live
type: project
---

Layer C target = `<TARGET_SYM>` at `<TARGET_ADDR>` (parent=`<TARGET_PARENT_SYM>`).
Ammo `幹C01..C05` deployed at block `<DEPLOY_BLOCK>`, all Debenture=true.
First 10 production cycles at N=1M, K=100 verified — invariants held.
Script: scripts/tx_layer_c_cycle.py. State: scripts/data/layer_c_ammo.json.

**Why:** Phase 5 of YUE Cascade Pump (spec 2026-04-25-yue-cascade-pump-design.md).
**How to apply:** Resume cycles by calling `tx_layer_c_cycle.py --phase cycle --n N --hold-back K`. Only escalate N after invariants prove stable for ≥100 cycles.
```

`/home/joey/.claude/projects/-opt-joystick-repo/memory/project_yue_parked_balances.md`:
```markdown
---
name: YUE-parked balances
description: Final per-token YUE balances after Phase 2, plus exit-mechanism verdict
type: project
---

Parked into JOEY_YUE (`0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0`):
  FDIC:   <amount> (exit_path_ok=<bool>)
  PARADE: <amount> (exit_path_ok=<bool>)
  DFM:    <amount> (exit_path_ok=<bool>)

EOA reserves retained for ongoing cycles:
  FDIC: 50 B / DFM: 600 M (post Phase 3) / PARADE: 1 T (less Phase 5 consumption)

**Why:** Yuan tier promotion 1× → 40× per CHOA.Yuan formula.
**How to apply:** Before un-parking any token, re-check `yue_exit_check.json` — tokens with exit_path_ok=false can only leave via `Hong()` (swap to QING-priced asset).
```

Update `MEMORY.md` index with both entries.

---

## Self-review

Spec coverage:
- Phase 1a/1b/1c/1d → Tasks 1, 2, 3, 4, 5 ✓
- Phase 2 (parking) → Tasks 6, 7, 8, 9 ✓
- Phase 3 (Layer B scaling) → Tasks 10, 11 ✓
- Phase 4 (target selection) → Tasks 12, 13 ✓
- Phase 5 (Layer C deploy + cycle) → Tasks 14, 15, 16 ✓
- Safety rails (gas floor, ceiling, EIP-1559, watchdog, atomic writes) → embedded in every operational task ✓
- Out-of-scope items (Phase 6, CROWS, Layer D, QING audit, TGSv8 atomic, concurrent submission, bot integration) — correctly absent ✓
- Persistence (memory entries) → Task 16 Step 6 ✓
- RPC strategy (READ_RPC vs SUBMIT_RPC) → embedded in every script's constants block ✓

Type / signature consistency:
- `JOEY`, `JOEY_LAU`, `JOEY_YUE`, `CHOA`, `WITHOUT`, `PARK_TOKENS` — defined in Task 1, reused identically in Tasks 4, 6, 7 ✓
- `erc20_balance`, `choa_yuan`, `atomic_write_json` — defined in Task 1, redefined locally in Task 6 (intentional — script independence) ✓
- `cmd_park` signature — declared in Task 6, implemented in Task 7 ✓
- `PRIORITY_FEE = 100_000 * 10**9` — matches memory `feedback_pulsechain_priority_fee` ✓

Placeholder scan: no TBD/TODO/"implement later"/"add appropriate handling" outside of the explicitly-deferred Phase 6 / out-of-scope items, which are noted in the spec rather than left as plan gaps. Note: `is_qing_underlying: None` in Task 12 is an explicit design choice (QING enumeration deferred), documented in the script's docstring.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-yue-cascade-pump.md`. Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, two-stage review between tasks, fast iteration. Best for the implementation tasks (1, 2, 3, 4, 6, 7, 10, 12, 14) which can be done in parallel-isolated worktrees.

2. **Inline Execution** — Execute tasks in this session using executing-plans, with checkpoints at every operational task. Required for Tasks 5, 8, 9, 11, 13, 15, 16 (operational TX), since user approval gates each one.

The implementation tasks are fully self-contained and amenable to subagent dispatch; the operational tasks require interactive user approval and on-chain monitoring, so they're naturally inline. A hybrid is fine: subagents for code, inline for execution.
