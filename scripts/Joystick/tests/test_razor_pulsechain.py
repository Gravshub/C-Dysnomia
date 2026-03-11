#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time

from dotenv import load_dotenv

# Resolve project root and ensure PYTHONPATH includes Joystick parent
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_JOYSTICK_DIR = os.path.dirname(_SCRIPT_DIR)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_JOYSTICK_DIR))
sys.path.insert(0, os.path.dirname(_JOYSTICK_DIR))

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from Joystick.core.config import (
    JOEY_WALLET, AFFECTION, WPLS, TGSV8,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    SEED_LAUS, HUB_TOKENS,
)
from Joystick.core.chain import (
    erc20, safe, tgsv8_contract, factory_contract,
    snapshot_balances, rpc_health, w3_read, w3_submit,
)
from Joystick.core.simulator import SimulationFailed
from Joystick.core.wallet import account as wallet_account, next_nonce
from Joystick.oracle.scanner import scan_tokens
from Joystick.oracle.profitability import rank_opportunities
from Joystick.engines.arb import ArbEngine

log = logging.getLogger("razor_test")

# ── Output ────────────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(_JOYSTICK_DIR, "data", "events")
_RESULT_FILE = os.path.join(_DATA_DIR, "razor_test.json")


def _save_result(result: dict) -> None:
    os.makedirs(os.path.dirname(_RESULT_FILE), exist_ok=True)
    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(_RESULT_FILE, "a") as f:
        f.write(json.dumps(result, default=str) + "\n")


def _hr(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── Phase 0: Acquire AFFECTION via TGSv8 ─────────────────────────────────────

def phase0_acquire_affection(pls_amount: int = 500, dry_run: bool = True):
    """Swap PLS → AFFECTION via TGSv8.swapNativeForTokens(). Tokens land in
    TGSv8 working balance, then withdraw() to Joey's EOA."""
    _hr(f"Phase 0: Acquire AFFECTION via TGSv8 ({'DRY-RUN' if dry_run else 'LIVE'})")

    if not TGSV8:
        print("  SKIPPED: TGSv8 not configured")
        return

    if wallet_account is None:
        print("  SKIPPED: No wallet (read-only mode)")
        return

    tgs = tgsv8_contract()
    tgs_submit = tgsv8_contract(w3=w3_submit)
    amount_wei = int(pls_amount * 10**18)
    DEX_BEST = 2  # DEX enum: V1=0, V2=1, BEST=2

    # Pre-flight: check current AFFECTION balance
    aff_before = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
    print(f"  AFFECTION before:  {aff_before / 1e18:.4f}")
    print(f"  Swapping:          {pls_amount} PLS → AFFECTION via TGSv8")

    # Quote: how much AFFECTION for this PLS?
    from web3 import Web3
    router_addr = safe(tgs, "routerV2") or safe(tgs, "routerV1")
    if router_addr:
        from Joystick.core.chain import router_contract
        router = router_contract()
        try:
            path = [Web3.to_checksum_address(WPLS), Web3.to_checksum_address(AFFECTION)]
            amounts = router.functions.getAmountsOut(amount_wei, path).call()
            expected_aff = amounts[-1]
            print(f"  Expected output:   {expected_aff / 1e18:.4f} AFFECTION")
        except Exception as exc:
            print(f"  Quote failed: {exc}")
            expected_aff = 0
    else:
        expected_aff = 0

    if dry_run:
        print("  DRY-RUN: no TX sent")
        return

    # Step 1: swapNativeForTokens — sends PLS, gets AFFECTION into TGSv8
    print("\n  Step 1: TGSv8.swapNativeForTokens(AFFECTION, 0, BEST)")
    try:
        tx_fn = tgs_submit.functions.swapNativeForTokens(
            Web3.to_checksum_address(AFFECTION),
            0,       # minOut — accept any amount for small test
            DEX_BEST,
        )
        tx = tx_fn.build_transaction({
            "from": JOEY_WALLET,
            "value": amount_wei,
            "gas": 500_000,
            "gasPrice": w3_submit.eth.gas_price,
            "nonce": next_nonce(),
            "chainId": 369,
        })
        signed = wallet_account.sign_transaction(tx)
        tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  TX sent: {tx_hash.hex()}")
        receipt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print(f"  Status:  {'OK' if receipt['status'] == 1 else 'REVERTED'}")
        print(f"  Gas:     {receipt['gasUsed']} ({receipt['gasUsed'] * receipt['effectiveGasPrice'] / 1e18:.2f} PLS)")
    except Exception as exc:
        print(f"  FAILED: {exc}")
        return

    # Step 2: Check TGSv8 working balance
    tgs_aff_bal = safe(tgs, "bal", AFFECTION) or 0
    print(f"\n  TGSv8 AFFECTION bal: {tgs_aff_bal / 1e18:.4f}")

    if tgs_aff_bal == 0:
        print("  No AFFECTION in TGSv8 — nothing to withdraw")
        return

    # Step 3: Withdraw AFFECTION from TGSv8 to Joey
    print(f"  Step 2: TGSv8.withdraw(AFFECTION, {tgs_aff_bal / 1e18:.4f})")
    try:
        tx_fn = tgs_submit.functions.withdraw(
            Web3.to_checksum_address(AFFECTION),
            tgs_aff_bal,
        )
        tx = tx_fn.build_transaction({
            "from": JOEY_WALLET,
            "gas": 100_000,
            "gasPrice": w3_submit.eth.gas_price,
            "nonce": next_nonce(),
            "chainId": 369,
        })
        signed = wallet_account.sign_transaction(tx)
        tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  TX sent: {tx_hash.hex()}")
        receipt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print(f"  Status:  {'OK' if receipt['status'] == 1 else 'REVERTED'}")
    except Exception as exc:
        print(f"  FAILED: {exc}")
        return

    # Verify
    aff_after = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
    gained = (aff_after - aff_before) / 1e18
    print(f"\n  AFFECTION after:   {aff_after / 1e18:.4f}")
    print(f"  Gained:            {gained:.4f} AFFECTION")


# ── Phase 1: Health Check ────────────────────────────────────────────────────

def phase1_health():
    _hr("Phase 1: Health Check")

    # RPC health
    rpc_health()

    # Balances
    bals = snapshot_balances()
    pls = bals["pls"]
    aff = bals["affection"]
    print(f"  Joey PLS:        {pls / 1e18:>14.4f}")
    print(f"  Joey AFFECTION:  {aff / 1e18:>14.4f}")
    print(f"  Joey GIBS:       {bals['gibs'] / 1e18:>14.4f}")
    print(f"  Joey WM:         {bals['wm'] / 1e18:>14.4f}")

    # WPLS balance
    wpls_bal = safe(erc20(WPLS), "balanceOf", JOEY_WALLET) or 0
    print(f"  Joey WPLS:       {wpls_bal / 1e18:>14.4f}")

    # TGSv8 status
    if TGSV8:
        tgs = tgsv8_contract()
        paused = safe(tgs, "paused") or False
        owner = safe(tgs, "owner") or "?"
        authorized = safe(tgs, "authorized", JOEY_WALLET)
        tgs_wpls = safe(tgs, "bal", WPLS) or 0
        tgs_aff = safe(tgs, "bal", AFFECTION) or 0
        print(f"\n  TGSv8:           {TGSV8}")
        print(f"  TGSv8 paused:    {paused}")
        print(f"  TGSv8 owner:     {owner}")
        print(f"  TGSv8 auth:      {authorized}")
        print(f"  TGSv8 WPLS bal:  {tgs_wpls / 1e18:>14.4f}")
        print(f"  TGSv8 AFF bal:   {tgs_aff / 1e18:>14.4f}")
    else:
        print("\n  TGSv8: NOT CONFIGURED (set TGSV8_ADDRESS in .env)")

    # Gas price
    gas_price = w3_read.eth.gas_price
    print(f"\n  Gas price:       {gas_price / 1e9:.2f} Gwei")

    return bals


# ── Phase 2: TGSv8 Oracle Scan (V1/V2 spreads) ─────────────────────────────

def phase2_oracle_scan():
    _hr("Phase 2: TGSv8 Oracle Scan (V1 vs V2 spreads)")

    if not TGSV8:
        print("  SKIPPED: TGSv8 not configured")
        return []

    tgs = tgsv8_contract()

    # Delegate candidate discovery to engine (single source of truth)
    engine = ArbEngine()
    candidates = engine._cross_dex_candidates()

    print(f"  Found {len(candidates)} tokens with BOTH V1 and V2 pairs\n")

    # Scan spreads via TGSv8.getReservesBoth()
    spreads = []
    for token_addr, label in candidates:
        try:
            result = safe(tgs, "getReservesBoth", token_addr, WPLS)
            if not result:
                continue
            v1rA, v1rB, v2rA, v2rB = result
            if v1rA == 0 or v1rB == 0 or v2rA == 0 or v2rB == 0:
                continue

            v1_price = v1rB / v1rA
            v2_price = v2rB / v2rA
            spread_bps = abs(v1_price - v2_price) / min(v1_price, v2_price) * 10000

            direction = "V1<V2" if v1_price < v2_price else "V2<V1"

            spreads.append({
                "token": token_addr,
                "label": label,
                "v1_price": v1_price,
                "v2_price": v2_price,
                "spread_bps": spread_bps,
                "direction": direction,
                "v1_liq_wpls": v1rB,
                "v2_liq_wpls": v2rB,
                "v1rA": v1rA, "v1rB": v1rB,
                "v2rA": v2rA, "v2rB": v2rB,
            })
        except Exception:
            continue

    # Sort by spread descending
    spreads.sort(key=lambda x: x["spread_bps"], reverse=True)

    # Display top 20 with profit estimate
    gas_price = w3_read.eth.gas_price
    gas_cost = 350_000 * gas_price
    print(f"  Gas cost estimate: {gas_cost / 1e18:.2f} PLS")
    print()
    print(f"  {'Token':<20s} {'Spread':>8s} {'Dir':>6s} {'V1 WPLS':>14s} {'V2 WPLS':>14s} {'Net PLS':>12s}")
    print(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*14} {'-'*14} {'-'*12}")
    for s in spreads[:20]:
        # Estimate net profit: trade 5% of smaller pool
        smaller = min(s['v1_liq_wpls'], s['v2_liq_wpls'])
        trade = int(smaller * 5 // 100)
        v1rA = s.get('v1rA', 0)
        v1rB = s.get('v1rB', 0)
        v2rA = s.get('v2rA', 0)
        v2rB = s.get('v2rB', 0)
        net_str = "N/A"
        if v1rA and v1rB and v2rA and v2rB and trade > 0:
            if s['direction'] == 'V1<V2':
                buy_rI, buy_rO = v1rB, v1rA
                sell_rI, sell_rO = v2rA, v2rB
            else:
                buy_rI, buy_rO = v2rB, v2rA
                sell_rI, sell_rO = v1rA, v1rB
            tokens = (buy_rO * trade * 997) // (buy_rI * 1000 + trade * 997)
            wpls_back = (sell_rO * tokens * 997) // (sell_rI * 1000 + tokens * 997) if tokens > 0 else 0
            net = (wpls_back - trade - gas_cost)
            net_str = f"{net / 1e18:>12.2f}"
        print(
            f"  {s['label'][:20]:<20s} {s['spread_bps']:>7.0f}bp {s['direction']:>6s} "
            f"{s['v1_liq_wpls']/1e18:>14.2f} {s['v2_liq_wpls']/1e18:>14.2f} {net_str}"
        )

    actionable = [s for s in spreads if s["spread_bps"] >= 50]
    print(f"\n  Actionable (>=50bps): {len(actionable)} tokens")

    return spreads


# ── Phase 3: Mode 1 (Purchase) Simulation ────────────────────────────────────

def phase3_purchase_sim():
    _hr("Phase 3: Mode 1 (Purchase Arb) Simulation")

    gas_price = w3_read.eth.gas_price
    gas_cost_wei = 400_000 * gas_price

    try:
        tokens = scan_tokens()
        ranked = rank_opportunities(tokens, gas_cost_wei)
    except Exception as exc:
        print(f"  FAILED: {exc}")
        return []

    if not ranked:
        print("  No profitable Purchase arb opportunities found")
        return []

    print(f"  Found {len(ranked)} profitable opportunities\n")
    print(f"  {'Token':<20s} {'Profit PLS':>12s} {'Impact':>8s} {'Rate':>10s}")
    print(f"  {'-'*20} {'-'*12} {'-'*8} {'-'*10}")
    for r in ranked[:10]:
        print(
            f"  {r.get('label', r.get('symbol', '?'))[:20]:<20s} "
            f"{r['profit_wei']/1e18:>12.4f} "
            f"{r.get('impact_pct', 0):>7.1f}% "
            f"{r.get('rate', 0)/1e18:>10.4f}"
        )

    return ranked


# ── Phase 4: Mode 2 (CrossDex) Simulation ────────────────────────────────────

def phase4_cross_dex_sim():
    _hr("Phase 4: Mode 2 (CrossDex) Simulation")

    engine = ArbEngine()
    gas_price = w3_read.eth.gas_price

    try:
        opp = engine._simulate_cross_dex(gas_price)
    except Exception as exc:
        print(f"  FAILED: {exc}")
        return None

    if not opp:
        print("  No profitable CrossDex opportunities found")
        return None

    print(f"  TOP OPPORTUNITY:")
    print(f"    Token:       {opp['label']}")
    print(f"    Token addr:  {opp['token']}")
    print(f"    Spread:      {opp['spread_bps']:.0f} bps")
    print(f"    Trade:       {opp['trade_amount']/1e18:.4f} WPLS")
    print(f"    Buy DEX:     {'V1' if opp['buy_dex'] == 0 else 'V2'}")
    print(f"    Sell DEX:    {'V1' if opp['sell_dex'] == 0 else 'V2'}")
    print(f"    Tokens out:  {opp['tokens_bought']/1e18:.4f}")
    print(f"    WPLS back:   {opp['wpls_received']/1e18:.4f}")
    print(f"    Est profit:  {opp['profit_wei']/1e18:.4f} PLS")
    print(f"    Gas cost:    {opp['gas_wei']/1e18:.4f} PLS")

    return opp


# ── Phase 5: Full Engine Test ─────────────────────────────────────────────────

def phase5_engine_test(dry_run: bool = True):
    _hr(f"Phase 5: Full Engine Test ({'DRY-RUN' if dry_run else 'LIVE'})")

    engine = ArbEngine()
    print(f"  is_ready(): {engine.is_ready()}")

    if not engine.is_ready():
        print("  Engine not ready — skipping")
        return None

    try:
        profit, gas = engine.simulate()
        opp = engine._top_opportunity
        mode = opp.get("mode", "?") if opp else "?"
        print(f"  Top opportunity [{mode}]: profit={profit/1e18:.4f} PLS  gas={gas/1e18:.4f} PLS")
        print(f"  ROI: {engine.roi():.2f}x")

        if opp:
            print(f"\n  Details:")
            for k, v in opp.items():
                if k not in ("mode", "profit_wei", "gas_wei", "cycle"):
                    print(f"    {k}: {v}")

        result = engine.execute(dry_run=dry_run)
        print(f"\n  Result:")
        print(f"    success:    {result.success}")
        print(f"    profit_pls: {result.profit_pls:.4f}")
        print(f"    gas_pls:    {result.gas_pls:.4f}")
        print(f"    net_pls:    {result.net_pls:.4f}")
        print(f"    tx_hashes:  {result.tx_hashes}")
        print(f"    notes:      {result.notes}")

        return result

    except SimulationFailed as exc:
        print(f"  No profitable opportunity: {exc}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RAZOR Engine 1 — PulseChain mainnet test")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution (no TX)")
    parser.add_argument("--execute", action="store_true", help="Live execution (sends TX!)")
    parser.add_argument("--mode2-only", action="store_true", help="CrossDex scan only")
    parser.add_argument("--skip-scan", action="store_true", help="Skip token discovery (faster)")
    parser.add_argument("--acquire-aff", type=int, metavar="PLS",
                        help="Acquire AFFECTION by swapping PLS via TGSv8 (e.g. --acquire-aff 500)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    start = time.time()
    results = {}

    # Phase 0: Acquire AFFECTION (optional)
    if args.acquire_aff:
        is_live = args.execute
        phase0_acquire_affection(pls_amount=args.acquire_aff, dry_run=not is_live)

    # Phase 1: Health check (always)
    bals = phase1_health()
    results["balances"] = {k: v / 1e18 for k, v in bals.items()}

    if args.mode2_only:
        # Just CrossDex scan
        spreads = phase2_oracle_scan()
        results["spreads"] = len(spreads)
        opp = phase4_cross_dex_sim()
        results["cross_dex_opp"] = opp is not None
    else:
        # Full test
        spreads = phase2_oracle_scan()
        results["spreads"] = len(spreads)

        if not args.skip_scan:
            ranked = phase3_purchase_sim()
            results["purchase_opps"] = len(ranked)

        opp = phase4_cross_dex_sim()
        results["cross_dex_opp"] = opp is not None

        if args.dry_run or args.execute:
            result = phase5_engine_test(dry_run=not args.execute)
            if result:
                results["engine_result"] = {
                    "success": result.success,
                    "profit_pls": result.profit_pls,
                    "gas_pls": result.gas_pls,
                    "net_pls": result.net_pls,
                }

    elapsed = time.time() - start
    results["elapsed_sec"] = round(elapsed, 1)

    _hr("Summary")
    print(f"  Elapsed:          {elapsed:.1f}s")
    print(f"  Dual-DEX tokens:  {results.get('spreads', 0)}")
    print(f"  Purchase opps:    {results.get('purchase_opps', 'N/A')}")
    print(f"  CrossDex viable:  {results.get('cross_dex_opp', False)}")
    if "engine_result" in results:
        er = results["engine_result"]
        print(f"  Engine result:    {'OK' if er['success'] else 'FAIL'} "
              f"(net={er['net_pls']:.4f} PLS)")

    _save_result(results)
    print(f"\n  Results saved to {_RESULT_FILE}")


if __name__ == "__main__":
    main()


# ── Module Documentation ─────────────────────────────────────────────────────
#
# test_razor_pulsechain.py — Mainnet integration test for Engine 1 (RAZOR)
#
# Tests all three arb modes on live PulseChain (369):
#   Phase 1: TGSv8 health check + balance snapshot
#   Phase 2: Oracle scan — TGSv8.getReservesBoth() for V1/V2 spreads
#   Phase 3: Mode 1 (Purchase) simulation via scan_tokens + rank_opportunities
#   Phase 4: Mode 2 (CrossDex) simulation via _simulate_cross_dex()
#   Phase 5: Full engine simulate() + execute() (dry-run or live)
#
# CLI:
#   python scripts/Joystick/tests/test_razor_pulsechain.py              # read-only scan
#   python scripts/Joystick/tests/test_razor_pulsechain.py --dry-run    # simulate all modes
#   python scripts/Joystick/tests/test_razor_pulsechain.py --execute    # live execution
#   python scripts/Joystick/tests/test_razor_pulsechain.py --mode2-only # CrossDex scan only
#   python scripts/Joystick/tests/test_razor_pulsechain.py --skip-scan  # skip token discovery
#   python scripts/Joystick/tests/test_razor_pulsechain.py -v           # debug logging
# ─────────────────────────────────────────────────────────────────────────────
