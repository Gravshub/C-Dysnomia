#!/usr/bin/env python3
"""
tgsv7_recon.py — Phase 1: Read-only TGSV7 deployment verification and balance snapshot.

Zero gas, zero risk. Run FIRST before any on-chain operations.

Usage:
    python scripts/Joystick/tools/tgsv7_recon.py
"""
import json
import os
import sys
import time

# Standalone script — insert parent package into sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_JOYSTICK_DIR = os.path.dirname(_SCRIPT_DIR)
_SCRIPTS_DIR = os.path.dirname(_JOYSTICK_DIR)
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from Joystick.core.config import (
    JOEY_WALLET, AFFECTION, WM, WPLS, GIBS_LAU, GIBS_QING,
    TGSV7, TGSV5,
)
from Joystick.core.chain import (
    w3_read, erc20, safe, multicall,
    tgsv7_contract, tgsv5_contract,
    TGSV7_ABI, TGSV5_ABI,
)

ZERO = "0x" + "0" * 40


def tag(ok: bool) -> str:
    return "[PASS]" if ok else "[FAIL]"


def run_recon():
    print("=" * 60)
    print("  TGSV7 DEPLOYMENT RECON")
    print("=" * 60)

    # ── Step 0: Address check ─────────────────────────────────────────────
    print(f"\nTGSV7_ADDRESS: {TGSV7 or '(not set)'}")
    print(f"TGSV5_ADDRESS: {TGSV5 or '(not set)'}")
    if not TGSV7:
        print("[FAIL] TGSV7_ADDRESS not set in .env — cannot proceed")
        sys.exit(1)

    tgsv7 = tgsv7_contract()

    # ── Step 1: Verify ownership and authorization ────────────────────────
    print(f"\n{'─'*60}")
    print("  Contract Verification")
    print(f"{'─'*60}")

    owner = safe(tgsv7, "owner")
    authorized = safe(tgsv7, "authorized", JOEY_WALLET)
    paused = safe(tgsv7, "paused")

    owner_ok = owner and owner.lower() == JOEY_WALLET.lower()
    auth_ok = authorized is True
    pause_ok = paused is False

    print(f"  owner():              {owner}")
    print(f"  {tag(owner_ok)} owner == JOEY_WALLET")
    print(f"  authorized(Joey):     {authorized}")
    print(f"  {tag(auth_ok)} Joey is authorized")
    print(f"  paused():             {paused}")
    print(f"  {tag(pause_ok)} Contract not paused")

    # ── Step 2: External references ───────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  External References")
    print(f"{'─'*60}")

    refs = {}
    for ref_name in ["minterV4", "minterV3", "mv", "routerV1", "routerV2"]:
        val = safe(tgsv7, ref_name)
        refs[ref_name] = val
        ok = val is not None and val != ZERO
        print(f"  {ref_name}():  {val}")
        print(f"  {tag(ok)} {ref_name} is set")

    # ── Step 3: Balance snapshot ──────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  Balance Snapshot")
    print(f"{'─'*60}")

    # Joey EOA balances
    aff_c = erc20(AFFECTION)
    wm_c = erc20(WM)
    gibs_c = erc20(GIBS_LAU)

    joey_results = multicall([
        (aff_c, "balanceOf", [JOEY_WALLET]),
        (wm_c, "balanceOf", [JOEY_WALLET]),
        (gibs_c, "balanceOf", [JOEY_WALLET]),
    ])

    pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
    aff_bal = joey_results[0] or 0
    wm_bal = joey_results[1] or 0
    gibs_bal = joey_results[2] or 0

    print(f"\n  Joey EOA ({JOEY_WALLET[:10]}...):")
    print(f"    PLS:        {pls_bal / 1e18:,.2f}")
    print(f"    AFFECTION:  {aff_bal / 1e18:.4f}")
    print(f"    WM/MV:      {wm_bal / 1e18:.4f}")
    print(f"    GIBS:       {gibs_bal / 1e18:.4f}")

    # TGSV7 internal balances
    tgsv7_native = safe(tgsv7, "nativeBal")
    try:
        tgsv7_bals = safe(tgsv7, "batchBal", [AFFECTION, WM, WPLS])
    except Exception:
        tgsv7_bals = None

    print(f"\n  TGSV7 ({TGSV7[:10]}...):")
    print(f"    Native PLS: {(tgsv7_native or 0) / 1e18:,.4f}")
    if tgsv7_bals and len(tgsv7_bals) >= 3:
        print(f"    AFFECTION:  {tgsv7_bals[0] / 1e18:.4f}")
        print(f"    WM/MV:      {tgsv7_bals[1] / 1e18:.4f}")
        print(f"    WPLS:       {tgsv7_bals[2] / 1e18:.4f}")
    else:
        # Fallback: individual bal() calls
        for name, addr in [("AFFECTION", AFFECTION), ("WM/MV", WM), ("WPLS", WPLS)]:
            bal = safe(tgsv7, "bal", addr)
            print(f"    {name}:  {(bal or 0) / 1e18:.4f}")

    # ── Step 4: MV state ─────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  MV/WM Token State")
    print(f"{'─'*60}")

    wm_total = safe(wm_c, "totalSupply")
    wm_allowance = safe(wm_c, "allowance", JOEY_WALLET, TGSV7)
    print(f"  MV.totalSupply():             {(wm_total or 0) / 1e18:.4f}")
    print(f"  MV.balanceOf(Joey):           {wm_bal / 1e18:.4f}")
    print(f"  MV.allowance(Joey→TGSV7):     {(wm_allowance or 0) / 1e18:.4f}")

    has_mv = wm_bal > 0
    print(f"  {tag(has_mv)} Joey has MV {'(ready for deposit)' if has_mv else '(needs Phase 0 bootstrap)'}")

    # ── Step 5: Registry ──────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  TGSV7 Registry")
    print(f"{'─'*60}")

    reg_len = safe(tgsv7, "registryLen")
    print(f"  registryLen(): {reg_len}")

    # ── Step 6: TGSv5 status ─────────────────────────────────────────────
    if TGSV5:
        print(f"\n{'─'*60}")
        print("  TGSv5 Status")
        print(f"{'─'*60}")
        try:
            tgsv5 = tgsv5_contract()
            v5_owner = safe(tgsv5, "owner")
            v5_auth = safe(tgsv5, "authorized", JOEY_WALLET)
            v5_paused = safe(tgsv5, "paused")
            print(f"  owner():          {v5_owner}")
            print(f"  authorized(Joey): {v5_auth}")
            print(f"  paused():         {v5_paused}")
            print(f"  {tag(v5_auth is True and v5_paused is False)} TGSv5 ready for mintWM()")
        except Exception as exc:
            print(f"  [FAIL] TGSv5 error: {exc}")

    # ── Step 7: Gas price ─────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  Gas Price")
    print(f"{'─'*60}")

    gas_price = w3_read.eth.gas_price
    print(f"  Current: {gas_price / 1e9:.2f} Gwei")
    from Joystick.core.config import GAS_PRICE_CEIL
    gas_ok = gas_price < GAS_PRICE_CEIL
    print(f"  {tag(gas_ok)} Below {GAS_PRICE_CEIL / 1e9:.0f} Gwei ceiling")

    # ── Summary ───────────────────────────────────────────────────────────
    all_pass = all([
        owner_ok, auth_ok, pause_ok, gas_ok,
        refs.get("minterV4") and refs["minterV4"] != ZERO,
        refs.get("minterV3") and refs["minterV3"] != ZERO,
        refs.get("mv") and refs["mv"] != ZERO,
    ])

    print(f"\n{'='*60}")
    print(f"  {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
    if not has_mv:
        print(f"  NOTE: MV balance is 0 — run Phase 0 bootstrap before minting")
    print(f"{'='*60}\n")

    # ── Save report ───────────────────────────────────────────────────────
    report = {
        "timestamp": int(time.time()),
        "tgsv7_address": TGSV7,
        "owner": owner,
        "authorized": authorized,
        "paused": paused,
        "refs": {k: v for k, v in refs.items()},
        "joey_balances": {
            "pls": str(pls_bal),
            "affection": str(aff_bal),
            "wm": str(wm_bal),
            "gibs": str(gibs_bal),
        },
        "tgsv7_native_bal": str(tgsv7_native or 0),
        "registry_len": reg_len,
        "gas_price_gwei": gas_price / 1e9,
        "all_pass": all_pass,
    }

    data_dir = os.path.join(_PROJECT_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    report_path = os.path.join(data_dir, "tgsv7_recon.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved: {report_path}")

    return all_pass


if __name__ == "__main__":
    success = run_recon()
    sys.exit(0 if success else 1)
