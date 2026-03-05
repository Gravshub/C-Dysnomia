#!/usr/bin/env python3
"""
tgsv8_mint_test.py — V4 token creation test via TGSv8 + gas baselines.

Tests TGSv8's minting capability using its integrated mintWM() for MV bootstrap.

Usage:
    python scripts/Joystick/tools/tgsv8_mint_test.py --dry-run
    python scripts/Joystick/tools/tgsv8_mint_test.py --single --broadcast
    python scripts/Joystick/tools/tgsv8_mint_test.py --full --broadcast
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
log = logging.getLogger("tgsv8_mint_test")

from web3 import Web3

from Joystick.core.config import (
    JOEY_WALLET, AFFECTION, WM, WPLS, TGSV8,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
)
from Joystick.core.chain import (
    w3_read, w3_submit, erc20, safe, multicall,
    tgsv8_contract, factory_contract,
)
from Joystick.core.executor import send_tx, approve_if_needed
from Joystick.core import wallet
from Joystick.engines.token_factory import parse_token_created

ZERO = "0x" + "0" * 40


def preflight_check() -> bool:
    """Check prerequisites."""
    print("=" * 60)
    print("  TGSV8 MINT TEST PRE-FLIGHT")
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

    # Check MV in TGSv8
    mv_in_tgsv8 = safe(tgsv8, "bal", WM) or 0
    mv_in_joey = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
    total_mv = mv_in_tgsv8 + mv_in_joey
    print(f"  MV in TGSv8:    {mv_in_tgsv8 / 1e18:.4f}")
    print(f"  MV in Joey EOA: {mv_in_joey / 1e18:.4f}")

    if total_mv < int(1e18):
        print("[INFO] Insufficient MV — will mint via TGSv8.mintWM() during test")
    else:
        print(f"[PASS] MV available: {total_mv / 1e18:.4f}")

    # Check AFFECTION
    aff_in_tgsv8 = safe(tgsv8, "bal", AFFECTION) or 0
    aff_in_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
    print(f"  AFF in TGSv8:   {aff_in_tgsv8 / 1e18:.4f}")
    print(f"  AFF in Joey:    {aff_in_joey / 1e18:.4f}")

    gas_price = w3_read.eth.gas_price
    pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
    print(f"  Gas: {gas_price / 1e9:.2f} Gwei")
    print(f"  PLS: {pls_bal / 1e18:,.2f}")

    return True


def ensure_mv_in_tgsv8(amount: int, dry_run: bool) -> bool:
    """Ensure MV is in TGSv8's working balance. Uses mintWM() if needed."""
    tgsv8_read = tgsv8_contract()
    mv_bal = safe(tgsv8_read, "bal", WM) or 0
    if mv_bal >= amount:
        return True

    # Check if Joey EOA has enough to deposit
    mv_joey = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
    needed = amount - mv_bal

    if mv_joey >= needed:
        # Deposit from Joey EOA
        print(f"  Depositing {needed / 1e18:.4f} MV into TGSv8...")
        wm_submit = w3_submit.eth.contract(address=Web3.to_checksum_address(WM), abi=erc20(WM).abi)
        approve_if_needed(wm_submit, TGSV8, needed, "MV → TGSv8", dry_run=dry_run)
        tgsv8_sub = tgsv8_contract(w3=w3_submit)
        send_tx(tgsv8_sub.functions.deposit(WM, needed), "TGSv8.deposit(MV)", dry_run=dry_run)
        return True

    # Need to mint WM first — use TGSv8.mintWM()
    # WM.RHO() mints to tx.origin (Joey), then we deposit into TGSv8
    mint_count = max(1, int((needed + int(1e18) - 1) // int(1e18)))  # ceil division
    mint_count = min(mint_count, 10)  # cap at 10
    print(f"  Minting {mint_count} WM via TGSv8.mintWM()...")
    tgsv8_sub = tgsv8_contract(w3=w3_submit)
    send_tx(tgsv8_sub.functions.mintWM(mint_count), f"TGSv8.mintWM({mint_count})", dry_run=dry_run)

    # Now deposit the freshly minted WM
    # Re-check Joey's WM balance
    if not dry_run:
        mv_joey = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
        if mv_joey >= needed:
            print(f"  Depositing {needed / 1e18:.4f} MV into TGSv8...")
            wm_submit = w3_submit.eth.contract(address=Web3.to_checksum_address(WM), abi=erc20(WM).abi)
            approve_if_needed(wm_submit, TGSV8, needed, "MV → TGSv8", dry_run=dry_run)
            send_tx(tgsv8_sub.functions.deposit(WM, needed), "TGSv8.deposit(MV)", dry_run=dry_run)
        else:
            print(f"[FAIL] After mintWM, Joey has {mv_joey / 1e18:.4f} MV — not enough")
            return False

    return True


def ensure_aff_in_tgsv8(amount: int, dry_run: bool) -> bool:
    """Deposit AFFECTION from Joey EOA into TGSv8 if needed."""
    tgsv8_read = tgsv8_contract()
    aff_bal = safe(tgsv8_read, "bal", AFFECTION) or 0
    if aff_bal >= amount:
        return True

    needed = amount - aff_bal
    aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
    if aff_joey < needed:
        print(f"[FAIL] Not enough AFFECTION in Joey EOA ({aff_joey / 1e18:.4f} < {needed / 1e18:.4f})")
        return False

    print(f"  Depositing {needed / 1e18:.4f} AFFECTION into TGSv8...")
    aff_submit = w3_submit.eth.contract(address=Web3.to_checksum_address(AFFECTION), abi=erc20(AFFECTION).abi)
    approve_if_needed(aff_submit, TGSV8, needed, "AFF → TGSv8", dry_run=dry_run)
    tgsv8_sub = tgsv8_contract(w3=w3_submit)
    send_tx(tgsv8_sub.functions.deposit(AFFECTION, needed), "TGSv8.deposit(AFF)", dry_run=dry_run)
    return True


def test_single_create(dry_run: bool) -> dict | None:
    """Create a single V4 token via TGSv8."""
    print(f"\n{'─'*60}")
    print("  Step 1: Single createV4 via TGSv8")
    print(f"{'─'*60}")

    tgsv8 = tgsv8_contract(w3=w3_submit)
    tgsv8_read = tgsv8_contract()

    name = "Joystick V8 Alpha"
    symbol = "JV8A"
    initial_mint = 1
    parent = AFFECTION

    if not ensure_mv_in_tgsv8(int(initial_mint * 1e18), dry_run):
        return None

    print(f"  Name: {name}")
    print(f"  Symbol: {symbol}")
    print(f"  InitialMint: {initial_mint}")
    print(f"  Parent: AFFECTION")

    # Simulate
    try:
        sim_result = tgsv8_read.functions.createV4(name, symbol, initial_mint, parent).call(
            {"from": JOEY_WALLET}
        )
        print(f"  Simulation OK — predicted token: {sim_result}")
    except Exception as exc:
        print(f"[FAIL] Simulation failed: {exc}")
        return None

    # Gas estimate
    try:
        gas_est = tgsv8_read.functions.createV4(name, symbol, initial_mint, parent).estimate_gas(
            {"from": JOEY_WALLET}
        )
        gas_price = w3_read.eth.gas_price
        gas_cost = gas_est * 1.3 * gas_price / 1e18
        print(f"  Gas: {gas_est:,} ({gas_cost:.4f} PLS)")
    except Exception as exc:
        print(f"[FAIL] Gas estimation failed: {exc}")
        return None

    receipt = send_tx(
        tgsv8.functions.createV4(name, symbol, initial_mint, parent),
        f"TGSv8.createV4({symbol})",
        dry_run=dry_run,
    )

    result = {
        "name": name,
        "symbol": symbol,
        "initial_mint": initial_mint,
        "gas_estimate": gas_est,
        "gas_cost_pls": gas_cost,
    }

    if receipt:
        token_addr = parse_token_created(receipt)
        result["token_address"] = token_addr
        result["gas_used"] = receipt["gasUsed"]
        result["block"] = receipt["blockNumber"]
        result["tx_hash"] = f"0x{receipt['transactionHash'].hex()}"
        actual_cost = receipt["gasUsed"] * receipt.get("effectiveGasPrice", gas_price) / 1e18
        result["actual_cost_pls"] = actual_cost

        print(f"\n  [PASS] Token created: {token_addr}")
        print(f"  Block: {receipt['blockNumber']}")
        print(f"  Gas used: {receipt['gasUsed']:,} ({actual_cost:.4f} PLS)")
    elif dry_run:
        result["token_address"] = sim_result
        print(f"\n  [dry-run] Would create token at {sim_result}")

    return result


def query_new_token(token_addr: str):
    """Query properties of newly created token."""
    print(f"\n{'─'*60}")
    print(f"  Step 2: Query token {token_addr[:10]}...")
    print(f"{'─'*60}")

    token = erc20(token_addr)

    name = safe(token, "name")
    symbol = safe(token, "symbol")
    supply = safe(token, "totalSupply")
    tgsv8_bal = safe(token, "balanceOf", TGSV8)

    print(f"  Name:        {name}")
    print(f"  Symbol:      {symbol}")
    print(f"  TotalSupply: {(supply or 0) / 1e18:.4f}")
    print(f"  TGSv8 holds: {(tgsv8_bal or 0) / 1e18:.4f}")

    tgsv8_read = tgsv8_contract()
    debenture = safe(tgsv8_read, "checkDebenture", token_addr)
    print(f"  Debenture:   {debenture}")

    v1_factory = factory_contract(PULSEX_V1_FACTORY)
    v2_factory = factory_contract(PULSEX_V2_FACTORY)
    v1_pair = safe(v1_factory, "getPair", token_addr, WPLS)
    v2_pair = safe(v2_factory, "getPair", token_addr, WPLS)
    print(f"  V1 pair:     {v1_pair or 'None'}")
    print(f"  V2 pair:     {v2_pair or 'None'}")


def test_mint_tokens(token_addr: str, dry_run: bool) -> dict | None:
    """Test mintTokens() with 1 AFFECTION as parent."""
    print(f"\n{'─'*60}")
    print(f"  Step 3: TGSv8.mintTokens({token_addr[:10]})")
    print(f"{'─'*60}")

    mint_amount = int(1e18)
    if not ensure_aff_in_tgsv8(mint_amount, dry_run):
        return None

    tgsv8 = tgsv8_contract(w3=w3_submit)
    tgsv8_read = tgsv8_contract()

    try:
        sim = tgsv8_read.functions.mintTokens(token_addr, mint_amount).call(
            {"from": JOEY_WALLET}
        )
        print(f"  Simulation OK — received: {sim / 1e18 if isinstance(sim, int) else sim}")
    except Exception as exc:
        print(f"[FAIL] mintTokens simulation: {exc}")
        return None

    try:
        gas_est = tgsv8_read.functions.mintTokens(token_addr, mint_amount).estimate_gas(
            {"from": JOEY_WALLET}
        )
        gas_price = w3_read.eth.gas_price
        gas_cost = gas_est * 1.3 * gas_price / 1e18
        print(f"  Gas: {gas_est:,} ({gas_cost:.4f} PLS)")
    except Exception as exc:
        print(f"[FAIL] Gas estimation: {exc}")
        return None

    receipt = send_tx(
        tgsv8.functions.mintTokens(token_addr, mint_amount),
        f"TGSv8.mintTokens({token_addr[:10]})",
        dry_run=dry_run,
    )

    result = {"gas_estimate": gas_est, "gas_cost_pls": gas_cost}
    if receipt:
        result["gas_used"] = receipt["gasUsed"]
        result["tx_hash"] = f"0x{receipt['transactionHash'].hex()}"
        actual = receipt["gasUsed"] * receipt.get("effectiveGasPrice", gas_price) / 1e18
        result["actual_cost_pls"] = actual
        print(f"  [PASS] Gas used: {receipt['gasUsed']:,} ({actual:.4f} PLS)")
    return result


def profitability_report(single_result: dict | None, mint_result: dict | None):
    """Gas baseline summary."""
    print(f"\n{'='*60}")
    print("  TGSV8 MINT GAS BASELINE")
    print(f"{'='*60}")

    gas_price = w3_read.eth.gas_price
    print(f"  Gas price: {gas_price / 1e9:.2f} Gwei")

    if single_result:
        gas_key = "gas_used" if "gas_used" in single_result else "gas_estimate"
        cost_key = "actual_cost_pls" if "actual_cost_pls" in single_result else "gas_cost_pls"
        print(f"  Single createV4:   {single_result[gas_key]:,} gas = {single_result[cost_key]:.4f} PLS")

    if mint_result:
        gas_key = "gas_used" if "gas_used" in mint_result else "gas_estimate"
        cost_key = "actual_cost_pls" if "actual_cost_pls" in mint_result else "gas_cost_pls"
        print(f"  Single mintTokens: {mint_result[gas_key]:,} gas = {mint_result[cost_key]:.4f} PLS")

    baseline = {
        "timestamp": int(time.time()),
        "tgsv8_address": TGSV8,
        "gas_price_gwei": gas_price / 1e9,
        "single_create": single_result,
        "mint_tokens": mint_result,
    }

    data_dir = os.path.join(_PROJECT_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    baseline_path = os.path.join(data_dir, "tgsv8_mint_baseline.json")
    with open(baseline_path, "w") as f:
        json.dump(baseline, f, indent=2, default=str)
    print(f"\n  Baseline saved: {baseline_path}")


def main():
    parser = argparse.ArgumentParser(description="TGSv8 Mint Test")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    parser.add_argument("--broadcast", action="store_true", help="Send TXs on-chain")
    parser.add_argument("--single", action="store_true", help="Single createV4 test only")
    parser.add_argument("--full", action="store_true", help="Single + mintTokens")
    args = parser.parse_args()

    if not args.dry_run and not args.broadcast:
        print("Specify --dry-run or --broadcast")
        sys.exit(1)

    dry_run = args.dry_run

    if not preflight_check():
        sys.exit(1)

    single_result = test_single_create(dry_run)
    if single_result is None:
        print("\n[FAIL] Single create failed — aborting")
        sys.exit(1)

    mint_result = None
    token_addr = single_result.get("token_address")
    if token_addr and token_addr != ZERO and not dry_run:
        query_new_token(token_addr)
        if args.full:
            mint_result = test_mint_tokens(token_addr, dry_run)

    profitability_report(single_result, mint_result)

    print(f"\n{'='*60}")
    print(f"  TGSV8 MINT TEST {'COMPLETE' if not dry_run else 'DRY RUN COMPLETE'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
