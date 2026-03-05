#!/usr/bin/env python3
"""
tgsv8_mint_wm_test.py — Test TGSv8.mintWM() — the new integrated WM batch minter.

Usage:
    python scripts/Joystick/tools/tgsv8_mint_wm_test.py --dry-run
    python scripts/Joystick/tools/tgsv8_mint_wm_test.py --broadcast
    python scripts/Joystick/tools/tgsv8_mint_wm_test.py --broadcast --count 6
"""
import argparse
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

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("mint_wm_test")

from web3 import Web3

from Joystick.core.config import JOEY_WALLET, WM, TGSV8
from Joystick.core.chain import w3_read, w3_submit, erc20, safe, tgsv8_contract
from Joystick.core.executor import send_tx


def preflight() -> bool:
    """Check prerequisites."""
    print("=" * 60)
    print("  TGSV8 mintWM PRE-FLIGHT")
    print("=" * 60)

    if not TGSV8:
        print("[FAIL] TGSV8_ADDRESS not set")
        return False

    tgsv8 = tgsv8_contract()

    paused = safe(tgsv8, "paused")
    authorized = safe(tgsv8, "authorized", JOEY_WALLET)
    if paused:
        print("[FAIL] TGSv8 is paused")
        return False
    if not authorized:
        print("[FAIL] Joey not authorized on TGSv8")
        return False
    print("[PASS] TGSv8 active and authorized")

    mv_addr = safe(tgsv8, "mv")
    if not mv_addr or mv_addr == "0x" + "0" * 40:
        print("[FAIL] mv() not set on TGSv8")
        return False
    print(f"[PASS] mv() = {mv_addr}")

    # Current WM balances
    wm_joey = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
    wm_tgsv8 = safe(tgsv8, "bal", WM) or 0
    print(f"  WM in Joey EOA:  {wm_joey / 1e18:.4f}")
    print(f"  WM in TGSv8:     {wm_tgsv8 / 1e18:.4f}")

    # Gas
    gas_price = w3_read.eth.gas_price
    pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
    print(f"  Gas: {gas_price / 1e9:.2f} Gwei")
    print(f"  PLS: {pls_bal / 1e18:,.2f}")

    return True


def test_mint_wm(count: int, dry_run: bool) -> dict | None:
    """Test mintWM(count)."""
    print(f"\n{'─'*60}")
    print(f"  Test: mintWM({count})")
    print(f"{'─'*60}")

    tgsv8_read = tgsv8_contract()
    tgsv8_sub = tgsv8_contract(w3=w3_submit)

    # Record WM balance before
    wm_joey_before = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
    wm_tgsv8_before = safe(tgsv8_read, "bal", WM) or 0

    # Simulate
    try:
        tgsv8_read.functions.mintWM(count).call({"from": JOEY_WALLET})
        print(f"  Simulation OK")
    except Exception as exc:
        print(f"[FAIL] Simulation failed: {exc}")
        return None

    # Gas estimate
    try:
        gas_est = tgsv8_read.functions.mintWM(count).estimate_gas({"from": JOEY_WALLET})
        gas_price = w3_read.eth.gas_price
        gas_cost = gas_est * 1.3 * gas_price / 1e18
        print(f"  Gas estimate: {gas_est:,} ({gas_cost:.4f} PLS)")
        print(f"  Per-RHO gas:  {gas_est // count:,}")
    except Exception as exc:
        print(f"[FAIL] Gas estimation failed: {exc}")
        return None

    # Execute
    receipt = send_tx(
        tgsv8_sub.functions.mintWM(count),
        f"TGSv8.mintWM({count})",
        dry_run=dry_run,
    )

    result = {
        "count": count,
        "gas_estimate": gas_est,
        "gas_cost_pls": gas_cost,
    }

    if receipt:
        gas_used = receipt["gasUsed"]
        actual_cost = gas_used * receipt.get("effectiveGasPrice", gas_price) / 1e18
        result["gas_used"] = gas_used
        result["actual_cost_pls"] = actual_cost
        result["block"] = receipt["blockNumber"]
        result["tx_hash"] = f"0x{receipt['transactionHash'].hex()}"
        result["per_rho_gas"] = gas_used // count

        # Check WM balance after
        # Note: WM.RHO() mints to tx.origin (Joey), not to the contract
        wm_joey_after = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
        wm_tgsv8_after = safe(tgsv8_read, "bal", WM) or 0
        joey_delta = wm_joey_after - wm_joey_before
        tgsv8_delta = wm_tgsv8_after - wm_tgsv8_before

        result["wm_joey_delta"] = joey_delta
        result["wm_tgsv8_delta"] = tgsv8_delta

        print(f"\n  [PASS] mintWM({count}) succeeded")
        print(f"  Block:          {receipt['blockNumber']}")
        print(f"  Gas used:       {gas_used:,} ({actual_cost:.4f} PLS)")
        print(f"  Per-RHO gas:    {gas_used // count:,}")
        print(f"  WM Joey delta:  {joey_delta / 1e18:.4f}")
        print(f"  WM TGSv8 delta: {tgsv8_delta / 1e18:.4f}")

        # WM.RHO() mints to tx.origin, so joey should have received
        total_delta = joey_delta + tgsv8_delta
        if total_delta > 0:
            print(f"  [PASS] WM minted: {total_delta / 1e18:.4f}")
        else:
            print(f"  [WARN] No WM balance change detected")

    elif dry_run:
        print(f"\n  [dry-run] Would mint {count} WM via RHO()")

    return result


def main():
    parser = argparse.ArgumentParser(description="TGSv8 mintWM Test")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    parser.add_argument("--broadcast", action="store_true", help="Send TXs on-chain")
    parser.add_argument("--count", type=int, default=6, help="Batch count for second test (default 6)")
    args = parser.parse_args()

    if not args.dry_run and not args.broadcast:
        print("Specify --dry-run or --broadcast")
        sys.exit(1)

    dry_run = args.dry_run

    if not preflight():
        sys.exit(1)

    # Test 1: Single mintWM(1)
    result1 = test_mint_wm(1, dry_run)
    if result1 is None:
        print("\n[FAIL] mintWM(1) failed — aborting")
        sys.exit(1)

    # Test 2: Batch mintWM(N)
    result_batch = test_mint_wm(args.count, dry_run)

    # Summary
    print(f"\n{'='*60}")
    print(f"  MINT WM GAS BASELINE")
    print(f"{'='*60}")

    gas_price = w3_read.eth.gas_price
    print(f"  Gas price: {gas_price / 1e9:.2f} Gwei")

    for label, r in [("mintWM(1)", result1), (f"mintWM({args.count})", result_batch)]:
        if r:
            gas_key = "gas_used" if "gas_used" in r else "gas_estimate"
            cost_key = "actual_cost_pls" if "actual_cost_pls" in r else "gas_cost_pls"
            print(f"  {label}: {r[gas_key]:,} gas = {r[cost_key]:.4f} PLS")
            if "per_rho_gas" in r:
                print(f"    per-RHO: {r['per_rho_gas']:,} gas")

    # Save baseline
    baseline = {
        "timestamp": int(time.time()),
        "tgsv8_address": TGSV8,
        "gas_price_gwei": gas_price / 1e9,
        "mint_wm_1": result1,
        "mint_wm_batch": result_batch,
    }

    data_dir = os.path.join(_PROJECT_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    baseline_path = os.path.join(data_dir, "tgsv8_mint_wm_baseline.json")
    with open(baseline_path, "w") as f:
        json.dump(baseline, f, indent=2, default=str)
    print(f"\n  Baseline saved: {baseline_path}")

    print(f"\n{'='*60}")
    print(f"  MINT WM TEST {'COMPLETE' if not dry_run else 'DRY RUN COMPLETE'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
