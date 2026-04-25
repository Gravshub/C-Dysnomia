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
SEL_GETRATE     = Web3.keccak(text="GetAssetRate(address,address)")[:4]  # YUE exit B-check

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

# ─── Helpers ─────────────────────────────────────────────────────────────
def _load_candidate_qings() -> list:
    """
    Returns checksummed addresses to probe for GetAssetRate.

    Currently uses V2 Federal tokens as a proxy for the QING universe (each V2
    Federal token may anchor a QING). Replace with MAP/CHOA enumeration when
    that becomes available. The single source-of-truth swap point is this
    function — callers should not know about V2F_INPUT.
    """
    if not os.path.exists(V2F_INPUT):
        return []
    with open(V2F_INPUT) as f:
        v2f = json.load(f)
    return [Web3.to_checksum_address(t["address"]) for t in v2f.get("tokens", [])]


# ─── Stubs for later sub-commands (filled in subsequent tasks) ───────────
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

    candidate_qings = _load_candidate_qings()
    if not candidate_qings:
        print(f"  WARN: no candidate QINGs available; B-check will be empty")

    out = {
        "checked_at_block": w3_read.eth.block_number,
        "candidate_source": "v2_federal_tokens.json (PROXY — not real QING enumeration; B may be undercounted)",
        "candidate_count": len(candidate_qings),
        "tokens": {},
    }
    for sym, token in PARK_TOKENS.items():
        try:
            has_mint = yue_has_mint(JOEY_YUE, token)
        except Exception as e:
            print(f"  {sym}: hasMint reverted ({e}) — assuming False")
            has_mint = False

        hong_paths = []
        non_revert_errors = []
        for qing in candidate_qings:
            data = SEL_GETRATE + abi_encode(["address", "address"], [qing, token])
            try:
                raw = w3_read.eth.call({"to": JOEY_YUE, "data": data})
                rate = abi_decode(["uint256"], raw)[0]
                if rate > 0:
                    hong_paths.append({"qing": qing, "rate": str(rate)})
            except Exception as e:
                err_str = str(e).lower()
                if "execution reverted" in err_str or "revert" in err_str:
                    # Expected: not a valid (Qing, SpendAsset) pair. Skip silently.
                    pass
                else:
                    # Transport / decode / other — do NOT silently mask
                    non_revert_errors.append({"qing": qing, "error": str(e)})

        if non_revert_errors:
            print(f"  WARN: {len(non_revert_errors)} non-revert errors during GetAssetRate scan for {sym}")

        exit_ok = has_mint or len(hong_paths) > 0
        verdict = "OK" if exit_ok else "ONE-WAY (cap 10%)"
        print(f"  {sym:8s}  hasMint={has_mint}  hong_paths={len(hong_paths)}  -> {verdict}")
        out["tokens"][sym] = {
            "address": token,
            "has_mint": has_mint,
            "hong_paths": hong_paths,
            "non_revert_errors": non_revert_errors,
            "exit_path_ok": exit_ok,
        }

    atomic_write_json(EXIT_FILE, out)
    print(f"[1b] wrote {EXIT_FILE}")
    return 0

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
