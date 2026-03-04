#!/usr/bin/env python3
"""
tgsv7_bootstrap_mv.py — Phase 0: Mint MV via TGSv5.mintWM(N) and optionally deposit into TGSV7.

MV (WM) is mintable for gas-only cost via WM.RHO(). TGSv5 wraps this as mintWM(N).
Each RHO() call mints 1 WM to tx.origin (Joey's EOA).

Usage:
    python scripts/Joystick/tools/tgsv7_bootstrap_mv.py --count 6 --dry-run
    python scripts/Joystick/tools/tgsv7_bootstrap_mv.py --count 6 --broadcast
    python scripts/Joystick/tools/tgsv7_bootstrap_mv.py --count 6 --broadcast --deposit-tgsv7
"""
import argparse
import os
import sys

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
log = logging.getLogger("bootstrap_mv")

from Joystick.core.config import JOEY_WALLET, WM, TGSV7, TGSV5
from Joystick.core.chain import (
    w3_read, w3_submit, erc20, safe,
    tgsv5_contract, tgsv7_contract,
)
from Joystick.core.executor import send_tx, approve_if_needed
from Joystick.core import wallet


def main():
    parser = argparse.ArgumentParser(description="Bootstrap MV via TGSv5.mintWM()")
    parser.add_argument("--count", type=int, default=6, help="Number of MV to mint (default: 6)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only, no TXs")
    parser.add_argument("--broadcast", action="store_true", help="Send TXs on-chain")
    parser.add_argument("--deposit-tgsv7", action="store_true",
                        help="After minting, deposit MV into TGSV7")
    args = parser.parse_args()

    if not args.dry_run and not args.broadcast:
        print("Specify --dry-run or --broadcast")
        sys.exit(1)

    dry_run = args.dry_run

    print("=" * 60)
    print("  MV BOOTSTRAP via TGSv5.mintWM()")
    print("=" * 60)

    # ── Pre-flight checks ─────────────────────────────────────────────────
    if not TGSV5:
        print("[FAIL] TGSV5_ADDRESS not set in .env")
        sys.exit(1)

    tgsv5 = tgsv5_contract(w3=w3_submit)
    tgsv5_read = tgsv5_contract(w3=w3_read)

    paused = safe(tgsv5_read, "paused")
    authorized = safe(tgsv5_read, "authorized", JOEY_WALLET)
    print(f"  TGSv5 paused: {paused}")
    print(f"  TGSv5 authorized(Joey): {authorized}")

    if paused:
        print("[FAIL] TGSv5 is paused")
        sys.exit(1)
    if not authorized:
        print("[FAIL] Joey not authorized on TGSv5")
        sys.exit(1)

    # Current MV balance
    wm_c = erc20(WM)
    wm_before = safe(wm_c, "balanceOf", JOEY_WALLET) or 0
    pls_before = w3_read.eth.get_balance(JOEY_WALLET)

    print(f"\n  Current MV balance (Joey EOA): {wm_before / 1e18:.4f}")
    print(f"  Current PLS balance: {pls_before / 1e18:,.2f}")
    print(f"  Minting: {args.count} MV")

    # ── Gas estimation ────────────────────────────────────────────────────
    gas_price = w3_read.eth.gas_price
    print(f"\n  Gas price: {gas_price / 1e9:.2f} Gwei")

    try:
        gas_est = tgsv5_read.functions.mintWM(args.count).estimate_gas({"from": JOEY_WALLET})
        gas_cost_pls = gas_est * 1.3 * gas_price / 1e18
        print(f"  Estimated gas: {gas_est:,}")
        print(f"  Estimated cost: {gas_cost_pls:.4f} PLS")
        print(f"  Per-unit cost: {gas_cost_pls / args.count:.4f} PLS/MV")
    except Exception as exc:
        print(f"[FAIL] Gas estimation failed: {exc}")
        sys.exit(1)

    remaining = pls_before / 1e18 - gas_cost_pls
    print(f"  PLS remaining after: {remaining:,.2f}")
    if remaining < 45000:
        print("  WARNING: Low PLS after mint. Consider minting fewer MV.")

    # ── Execute mint ──────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  {'DRY RUN' if dry_run else 'BROADCASTING'}: mintWM({args.count})")
    print(f"{'─'*60}")

    receipt = send_tx(
        tgsv5.functions.mintWM(args.count),
        f"TGSv5.mintWM({args.count})",
        dry_run=dry_run,
    )

    if not dry_run and receipt:
        print(f"\n  TX: 0x{receipt['transactionHash'].hex()}")
        print(f"  Block: {receipt['blockNumber']}")
        print(f"  Gas used: {receipt['gasUsed']:,}")
        actual_cost = receipt['gasUsed'] * receipt.get('effectiveGasPrice', gas_price) / 1e18
        print(f"  Actual cost: {actual_cost:.4f} PLS")

    # Verify
    wm_after = safe(wm_c, "balanceOf", JOEY_WALLET) or 0
    print(f"\n  MV balance after: {wm_after / 1e18:.4f}")
    if not dry_run:
        gained = (wm_after - wm_before) / 1e18
        print(f"  MV gained: {gained:.4f}")
        if gained < args.count:
            print(f"  WARNING: Expected {args.count} MV, got {gained:.0f}")

    # ── Optional: Deposit into TGSV7 ─────────────────────────────────────
    if args.deposit_tgsv7 and wm_after > 0:
        if not TGSV7:
            print("\n[FAIL] TGSV7_ADDRESS not set in .env — cannot deposit")
            return

        deposit_amount = wm_after
        print(f"\n{'─'*60}")
        print(f"  Depositing {deposit_amount / 1e18:.4f} MV into TGSV7")
        print(f"{'─'*60}")

        # Approve
        wm_submit = w3_submit.eth.contract(
            address=wm_c.address, abi=wm_c.abi
        )
        approve_if_needed(
            wm_submit, TGSV7, deposit_amount,
            f"MV → TGSV7 ({deposit_amount / 1e18:.0f} MV)",
            dry_run=dry_run,
        )

        # Deposit
        tgsv7 = tgsv7_contract(w3=w3_submit)
        receipt2 = send_tx(
            tgsv7.functions.deposit(WM, deposit_amount),
            f"TGSV7.deposit(MV, {deposit_amount / 1e18:.0f})",
            dry_run=dry_run,
        )

        if not dry_run and receipt2:
            # Verify TGSV7 internal balance
            tgsv7_read = tgsv7_contract()
            mv_in_tgsv7 = safe(tgsv7_read, "bal", WM) or 0
            print(f"  MV in TGSV7: {mv_in_tgsv7 / 1e18:.4f}")

    print(f"\n{'='*60}")
    print(f"  BOOTSTRAP {'COMPLETE' if not dry_run else 'DRY RUN COMPLETE'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
