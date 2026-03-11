#!/usr/bin/env python3
"""
tgsv7_mint_test.py — Phase 2: V4 token creation test + gas baselines + LP ratio analysis.

Tests TGSV7's minting capability and measures gas costs to establish profitability baseline.

Usage:
    python scripts/Joystick/tools/tgsv7_mint_test.py --dry-run
    python scripts/Joystick/tools/tgsv7_mint_test.py --single --broadcast
    python scripts/Joystick/tools/tgsv7_mint_test.py --full --broadcast
    python scripts/Joystick/tools/tgsv7_mint_test.py --report
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
log = logging.getLogger("mint_test")

from web3 import Web3

from Joystick.core.config import JOEY_WALLET, AFFECTION, WM, WPLS, TGSV7, PULSEX_V1_FACTORY, PULSEX_V2_FACTORY
from Joystick.core.chain import (
    w3_read, w3_submit, erc20, safe, multicall,
    tgsv7_contract, factory_contract,
)
from Joystick.core.executor import send_tx, approve_if_needed
from Joystick.core import wallet
from Joystick.engines.token_factory import (
    parse_token_created, optimize_lp_ratio, print_ratio_analysis, LPStrategy,
)

ZERO = "0x" + "0" * 40


def preflight_check() -> bool:
    """Check prerequisites. Returns True if ready."""
    print("=" * 60)
    print("  MINT TEST PRE-FLIGHT")
    print("=" * 60)

    if not TGSV7:
        print("[FAIL] TGSV7_ADDRESS not set")
        return False

    tgsv7 = tgsv7_contract()

    # Check TGSV7 state
    paused = safe(tgsv7, "paused")
    authorized = safe(tgsv7, "authorized", JOEY_WALLET)
    if paused:
        print("[FAIL] TGSV7 is paused")
        return False
    if not authorized:
        print("[FAIL] Joey not authorized on TGSV7")
        return False
    print("[PASS] TGSV7 active and authorized")

    # Check MV in TGSV7
    mv_in_tgsv7 = safe(tgsv7, "bal", WM) or 0
    mv_in_joey = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
    total_mv = mv_in_tgsv7 + mv_in_joey
    print(f"  MV in TGSV7:    {mv_in_tgsv7 / 1e18:.4f}")
    print(f"  MV in Joey EOA: {mv_in_joey / 1e18:.4f}")

    if total_mv < int(1e18):
        print("[FAIL] Insufficient MV. Run Phase 0 bootstrap first:")
        print("  python scripts/Joystick/tools/tgsv7_bootstrap_mv.py --count 6 --broadcast --deposit-tgsv7")
        return False
    print(f"[PASS] MV available: {total_mv / 1e18:.4f}")

    # Check AFFECTION
    aff_in_tgsv7 = safe(tgsv7, "bal", AFFECTION) or 0
    aff_in_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
    print(f"  AFF in TGSV7:   {aff_in_tgsv7 / 1e18:.4f}")
    print(f"  AFF in Joey:    {aff_in_joey / 1e18:.4f}")

    # Gas
    gas_price = w3_read.eth.gas_price
    pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
    print(f"  Gas: {gas_price / 1e9:.2f} Gwei")
    print(f"  PLS: {pls_bal / 1e18:,.2f}")

    return True


def ensure_mv_in_tgsv7(amount: int, dry_run: bool) -> bool:
    """Deposit MV from Joey EOA into TGSV7 if needed."""
    tgsv7_read = tgsv7_contract()
    mv_bal = safe(tgsv7_read, "bal", WM) or 0
    if mv_bal >= amount:
        return True

    needed = amount - mv_bal
    mv_joey = safe(erc20(WM), "balanceOf", JOEY_WALLET) or 0
    if mv_joey < needed:
        print(f"[FAIL] Not enough MV in Joey EOA ({mv_joey / 1e18:.4f} < {needed / 1e18:.4f})")
        return False

    print(f"  Depositing {needed / 1e18:.4f} MV into TGSV7...")
    wm_submit = w3_submit.eth.contract(address=Web3.to_checksum_address(WM), abi=erc20(WM).abi)
    approve_if_needed(wm_submit, TGSV7, needed, f"MV → TGSV7", dry_run=dry_run)

    tgsv7_sub = tgsv7_contract(w3=w3_submit)
    send_tx(tgsv7_sub.functions.deposit(WM, needed), "TGSV7.deposit(MV)", dry_run=dry_run)
    return True


def ensure_aff_in_tgsv7(amount: int, dry_run: bool) -> bool:
    """Deposit AFFECTION from Joey EOA into TGSV7 if needed."""
    tgsv7_read = tgsv7_contract()
    aff_bal = safe(tgsv7_read, "bal", AFFECTION) or 0
    if aff_bal >= amount:
        return True

    needed = amount - aff_bal
    aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
    if aff_joey < needed:
        print(f"[FAIL] Not enough AFFECTION in Joey EOA ({aff_joey / 1e18:.4f} < {needed / 1e18:.4f})")
        return False

    print(f"  Depositing {needed / 1e18:.4f} AFFECTION into TGSV7...")
    aff_submit = w3_submit.eth.contract(address=Web3.to_checksum_address(AFFECTION), abi=erc20(AFFECTION).abi)
    approve_if_needed(aff_submit, TGSV7, needed, f"AFF → TGSV7", dry_run=dry_run)

    tgsv7_sub = tgsv7_contract(w3=w3_submit)
    send_tx(tgsv7_sub.functions.deposit(AFFECTION, needed), "TGSV7.deposit(AFF)", dry_run=dry_run)
    return True


def test_single_create(dry_run: bool) -> dict | None:
    """Step 1: Create a single V4 token."""
    print(f"\n{'─'*60}")
    print("  Step 1: Single createV4")
    print(f"{'─'*60}")

    tgsv7 = tgsv7_contract(w3=w3_submit)
    tgsv7_read = tgsv7_contract()

    name = "Joystick Alpha"
    symbol = "JALPHA"
    initial_mint = 1  # 1 MV cost
    parent = AFFECTION

    # Ensure MV deposited
    if not ensure_mv_in_tgsv7(int(initial_mint * 1e18), dry_run):
        return None

    print(f"  Name: {name}")
    print(f"  Symbol: {symbol}")
    print(f"  InitialMint: {initial_mint}")
    print(f"  Parent: AFFECTION")

    # Simulate
    try:
        sim_result = tgsv7_read.functions.createV4(name, symbol, initial_mint, parent).call(
            {"from": JOEY_WALLET}
        )
        print(f"  Simulation OK — predicted token: {sim_result}")
    except Exception as exc:
        print(f"[FAIL] Simulation failed: {exc}")
        return None

    # Gas estimate
    try:
        gas_est = tgsv7_read.functions.createV4(name, symbol, initial_mint, parent).estimate_gas(
            {"from": JOEY_WALLET}
        )
        gas_price = w3_read.eth.gas_price
        gas_cost = gas_est * 1.3 * gas_price / 1e18
        print(f"  Gas: {gas_est:,} ({gas_cost:.4f} PLS)")
    except Exception as exc:
        print(f"[FAIL] Gas estimation failed: {exc}")
        return None

    # Execute
    receipt = send_tx(
        tgsv7.functions.createV4(name, symbol, initial_mint, parent),
        f"createV4({symbol})",
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
    """Step 2: Query properties of newly created token."""
    print(f"\n{'─'*60}")
    print(f"  Step 2: Query token {token_addr[:10]}...")
    print(f"{'─'*60}")

    token = erc20(token_addr)

    # Basic ERC20 queries
    name = safe(token, "name")
    symbol = safe(token, "symbol")
    supply = safe(token, "totalSupply")
    tgsv7_bal = safe(token, "balanceOf", TGSV7)

    print(f"  Name:        {name}")
    print(f"  Symbol:      {symbol}")
    print(f"  TotalSupply: {(supply or 0) / 1e18:.4f}")
    print(f"  TGSV7 holds: {(tgsv7_bal or 0) / 1e18:.4f}")

    # Check debenture (mintable)
    tgsv7_read = tgsv7_contract()
    debenture = safe(tgsv7_read, "checkDebenture", token_addr)
    print(f"  Debenture:   {debenture}")

    # DEX pair check
    v1_factory = factory_contract(PULSEX_V1_FACTORY)
    v2_factory = factory_contract(PULSEX_V2_FACTORY)
    v1_pair = safe(v1_factory, "getPair", token_addr, WPLS)
    v2_pair = safe(v2_factory, "getPair", token_addr, WPLS)
    print(f"  V1 pair:     {v1_pair or 'None'}")
    print(f"  V2 pair:     {v2_pair or 'None'}")


def test_mint_tokens(token_addr: str, dry_run: bool) -> dict | None:
    """Step 3: Test mintTokens() with 1 AFFECTION as parent."""
    print(f"\n{'─'*60}")
    print(f"  Step 3: mintTokens({token_addr[:10]})")
    print(f"{'─'*60}")

    # Ensure AFFECTION in TGSV7
    mint_amount = int(1e18)  # 1 AFFECTION
    if not ensure_aff_in_tgsv7(mint_amount, dry_run):
        return None

    tgsv7 = tgsv7_contract(w3=w3_submit)
    tgsv7_read = tgsv7_contract()

    # Simulate
    try:
        sim = tgsv7_read.functions.mintTokens(token_addr, mint_amount).call(
            {"from": JOEY_WALLET}
        )
        print(f"  Simulation OK — received: {sim / 1e18 if isinstance(sim, int) else sim}")
    except Exception as exc:
        print(f"[FAIL] mintTokens simulation: {exc}")
        return None

    # Gas estimate
    try:
        gas_est = tgsv7_read.functions.mintTokens(token_addr, mint_amount).estimate_gas(
            {"from": JOEY_WALLET}
        )
        gas_price = w3_read.eth.gas_price
        gas_cost = gas_est * 1.3 * gas_price / 1e18
        print(f"  Gas: {gas_est:,} ({gas_cost:.4f} PLS)")
    except Exception as exc:
        print(f"[FAIL] Gas estimation: {exc}")
        return None

    receipt = send_tx(
        tgsv7.functions.mintTokens(token_addr, mint_amount),
        f"mintTokens({token_addr[:10]})",
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


def test_batch_create(dry_run: bool) -> list[dict]:
    """Step 4: Batch create 5 V4 tokens."""
    print(f"\n{'─'*60}")
    print("  Step 4: Batch create 5 V4 tokens")
    print(f"{'─'*60}")

    batch_names = [
        ("Joystick Beta",    "JBETA"),
        ("Joystick Gamma",   "JGAMMA"),
        ("Joystick Delta",   "JDELTA"),
        ("Joystick Epsilon", "JEPSI"),
        ("Joystick Zeta",    "JZETA"),
    ]

    # Ensure 5 MV in TGSV7
    if not ensure_mv_in_tgsv7(int(5e18), dry_run):
        return []

    tgsv7 = tgsv7_contract(w3=w3_submit)
    results = []

    for name, symbol in batch_names:
        print(f"\n  Creating {symbol}...")
        receipt = send_tx(
            tgsv7.functions.createV4(name, symbol, 1, AFFECTION),
            f"createV4({symbol})",
            dry_run=dry_run,
        )

        entry = {"name": name, "symbol": symbol}
        if receipt:
            token_addr = parse_token_created(receipt)
            gas_price = receipt.get("effectiveGasPrice", w3_read.eth.gas_price)
            actual = receipt["gasUsed"] * gas_price / 1e18
            entry["token_address"] = token_addr
            entry["gas_used"] = receipt["gasUsed"]
            entry["actual_cost_pls"] = actual
            entry["tx_hash"] = f"0x{receipt['transactionHash'].hex()}"
            print(f"  [PASS] {symbol} → {token_addr} (gas: {receipt['gasUsed']:,})")
        results.append(entry)

    return results


def profitability_report(single_result: dict | None, mint_result: dict | None, batch_results: list[dict]):
    """Step 5: Gas baseline + LP ratio analysis."""
    print(f"\n{'='*60}")
    print("  TGSV7 MINT GAS BASELINE")
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

    if batch_results:
        actual_results = [r for r in batch_results if "gas_used" in r]
        if actual_results:
            total_gas = sum(r["gas_used"] for r in actual_results)
            total_cost = sum(r["actual_cost_pls"] for r in actual_results)
            avg_gas = total_gas // len(actual_results)
            avg_cost = total_cost / len(actual_results)
            print(f"  Batch {len(actual_results)}x createV4: {total_gas:,} gas = {total_cost:.4f} PLS")
            print(f"  Avg per createV4:  {avg_gas:,} gas = {avg_cost:.4f} PLS")

    # LP Ratio Analysis for each created token
    print()
    all_tokens = []
    if single_result and single_result.get("token_address"):
        all_tokens.append(single_result["token_address"])
    for r in batch_results:
        if r.get("token_address"):
            all_tokens.append(r["token_address"])

    if all_tokens:
        pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
        create_cost = single_result.get("actual_cost_pls", single_result.get("gas_cost_pls", 50)) if single_result else 50
        # MV cost is effectively zero (minted via RHO for gas only)
        rho_gas_cost = 5.0  # approximate gas cost per mintWM(1) in PLS

        print(f"\n  LP Ratio Analysis (using first created token as example):")
        scenarios = optimize_lp_ratio(
            initial_mint=int(1000 * 1e18),  # analyze at 1000 tokens
            available_wpls=pls_bal,
            gas_cost_pls=create_cost,
            mv_cost_pls=rho_gas_cost,
        )
        print_ratio_analysis(scenarios)

    # Save baseline
    baseline = {
        "timestamp": int(time.time()),
        "gas_price_gwei": gas_price / 1e9,
        "single_create": single_result,
        "mint_tokens": mint_result,
        "batch_create": batch_results,
        "created_tokens": all_tokens,
    }

    data_dir = os.path.join(_PROJECT_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    baseline_path = os.path.join(data_dir, "mint_baseline.json")
    with open(baseline_path, "w") as f:
        json.dump(baseline, f, indent=2, default=str)
    print(f"\n  Baseline saved: {baseline_path}")


def report_only():
    """Load and display existing baseline without new TXs."""
    baseline_path = os.path.join(_PROJECT_ROOT, "data", "mint_baseline.json")
    if not os.path.exists(baseline_path):
        print("No baseline data found. Run --single or --full first.")
        return

    with open(baseline_path) as f:
        data = json.load(f)

    print("=" * 60)
    print("  SAVED MINT BASELINE")
    print("=" * 60)
    print(json.dumps(data, indent=2))


def main():
    parser = argparse.ArgumentParser(description="TGSV7 Mint Test")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    parser.add_argument("--broadcast", action="store_true", help="Send TXs on-chain")
    parser.add_argument("--single", action="store_true", help="Single createV4 test only")
    parser.add_argument("--full", action="store_true", help="Single + batch of 5")
    parser.add_argument("--report", action="store_true", help="Show saved baseline")
    args = parser.parse_args()

    if args.report:
        report_only()
        return

    if not args.dry_run and not args.broadcast:
        print("Specify --dry-run or --broadcast")
        sys.exit(1)

    dry_run = args.dry_run

    if not preflight_check():
        sys.exit(1)

    single_result = None
    mint_result = None
    batch_results = []

    # Step 1: Single createV4
    single_result = test_single_create(dry_run)
    if single_result is None:
        print("\n[FAIL] Single create failed — aborting")
        sys.exit(1)

    # Step 2: Query new token (only if we have an actual on-chain address)
    token_addr = single_result.get("token_address")
    if token_addr and token_addr != ZERO and not dry_run:
        query_new_token(token_addr)

        # Step 3: Test mintTokens
        mint_result = test_mint_tokens(token_addr, dry_run)
    elif dry_run:
        print(f"\n  [dry-run] Skipping Steps 2-3 — token not deployed on-chain")

    # Step 4: Batch create (only in --full mode)
    if args.full:
        batch_results = test_batch_create(dry_run)

    # Step 5: Profitability report
    profitability_report(single_result, mint_result, batch_results)

    print(f"\n{'='*60}")
    print(f"  MINT TEST {'COMPLETE' if not dry_run else 'DRY RUN COMPLETE'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
