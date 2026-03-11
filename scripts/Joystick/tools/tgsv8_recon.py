#!/usr/bin/env python3
"""
tgsv8_recon.py — Read-only TGSv8 deployment verification and balance snapshot.

Zero gas, zero risk. Run FIRST before any on-chain operations.

Usage:
    python scripts/Joystick/tools/tgsv8_recon.py
"""
import json
import os
import sys
import time

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
    TGSV8,
)
from Joystick.core.chain import (
    w3_read, erc20, safe, multicall,
    tgsv8_contract, TGSV8_ABI,
)

ZERO = "0x" + "0" * 40


def tag(ok: bool) -> str:
    return "[PASS]" if ok else "[FAIL]"


def run_recon():
    print("=" * 60)
    print("  TGSV8 DEPLOYMENT RECON")
    print("=" * 60)

    # ── Step 0: Address check ─────────────────────────────────────────────
    print(f"\nTGSV8_ADDRESS: {TGSV8 or '(not set)'}")
    if not TGSV8:
        print("[FAIL] TGSV8_ADDRESS not set in .env — cannot proceed")
        sys.exit(1)

    tgsv8 = tgsv8_contract()

    # ── Step 1: Verify ownership and authorization ────────────────────────
    print(f"\n{'─'*60}")
    print("  Contract Verification")
    print(f"{'─'*60}")

    owner = safe(tgsv8, "owner")
    authorized = safe(tgsv8, "authorized", JOEY_WALLET)
    paused = safe(tgsv8, "paused")

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
    for ref_name in ["minterV4", "minterV3", "mv", "wpls", "routerV1", "routerV2", "factoryV1", "factoryV2"]:
        val = safe(tgsv8, ref_name)
        refs[ref_name] = val
        ok = val is not None and val != ZERO
        print(f"  {ref_name}():  {val}")
        print(f"  {tag(ok)} {ref_name} is set")

    # ── Step 3: Balance snapshot ──────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  Balance Snapshot")
    print(f"{'─'*60}")

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

    # TGSV8 internal balances
    tgsv8_native = safe(tgsv8, "nativeBal")
    try:
        tgsv8_bals = safe(tgsv8, "batchBal", [AFFECTION, WM, WPLS])
    except Exception:
        tgsv8_bals = None

    print(f"\n  TGSV8 ({TGSV8[:10]}...):")
    print(f"    Native PLS: {(tgsv8_native or 0) / 1e18:,.4f}")
    if tgsv8_bals and len(tgsv8_bals) >= 3:
        print(f"    AFFECTION:  {tgsv8_bals[0] / 1e18:.4f}")
        print(f"    WM/MV:      {tgsv8_bals[1] / 1e18:.4f}")
        print(f"    WPLS:       {tgsv8_bals[2] / 1e18:.4f}")
    else:
        for name, addr in [("AFFECTION", AFFECTION), ("WM/MV", WM), ("WPLS", WPLS)]:
            bal = safe(tgsv8, "bal", addr)
            print(f"    {name}:  {(bal or 0) / 1e18:.4f}")

    # ── Step 4: MV state ─────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  MV/WM Token State")
    print(f"{'─'*60}")

    wm_total = safe(wm_c, "totalSupply")
    wm_allowance = safe(wm_c, "allowance", JOEY_WALLET, TGSV8)
    print(f"  MV.totalSupply():             {(wm_total or 0) / 1e18:.4f}")
    print(f"  MV.balanceOf(Joey):           {wm_bal / 1e18:.4f}")
    print(f"  MV.allowance(Joey→TGSV8):     {(wm_allowance or 0) / 1e18:.4f}")

    has_mv = wm_bal > 0
    print(f"  {tag(has_mv)} Joey has MV {'(ready for deposit)' if has_mv else '(needs mintWM bootstrap)'}")

    # ── Step 5: Registry ──────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  TGSV8 Registry")
    print(f"{'─'*60}")

    reg_len = safe(tgsv8, "registryLen")
    op_nonce = safe(tgsv8, "opNonce")
    max_batch = safe(tgsv8, "maxBatch")
    print(f"  registryLen(): {reg_len}")
    print(f"  opNonce():     {op_nonce}")
    print(f"  maxBatch():    {max_batch}")

    # ── Step 6: Gas price ─────────────────────────────────────────────────
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
        refs.get("routerV1") and refs["routerV1"] != ZERO,
        refs.get("routerV2") and refs["routerV2"] != ZERO,
    ])

    print(f"\n{'='*60}")
    print(f"  {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
    if not has_mv:
        print(f"  NOTE: MV balance is 0 — use TGSv8.mintWM() to bootstrap")
    print(f"{'='*60}\n")

    # ── Save report ───────────────────────────────────────────────────────
    report = {
        "timestamp": int(time.time()),
        "tgsv8_address": TGSV8,
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
        "tgsv8_native_bal": str(tgsv8_native or 0),
        "registry_len": reg_len,
        "op_nonce": op_nonce,
        "gas_price_gwei": gas_price / 1e9,
        "all_pass": all_pass,
    }

    data_dir = os.path.join(_PROJECT_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    report_path = os.path.join(data_dir, "tgsv8_recon.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved: {report_path}")

    return all_pass


if __name__ == "__main__":
    success = run_recon()
    sys.exit(0 if success else 1)
