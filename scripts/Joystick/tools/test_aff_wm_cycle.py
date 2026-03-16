"""
test_aff_wm_cycle.py — Standalone diagnostic for the dual-mode AFFECTION + WM engine.

Usage:
  python -m scripts.Joystick.tools.test_aff_wm_cycle              # price all routes
  python -m scripts.Joystick.tools.test_aff_wm_cycle --execute     # run one test cycle

Prices all 5 AFFECTION BuyWith routes + WM minting, prints economics table,
and optionally executes a forced diagnostic cycle with budget guardrails.

Env:
  DYSNOMIA_PRIVATE_KEY   Joey's wallet key (required for --execute)
  TGSV8_ADDRESS          TGSv8 contract address
"""
import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

# Setup logging before imports that use it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("test_aff_wm")

from ..core.config import (
    JOEY_WALLET, AFFECTION, WM, WPLS,
    AFF_G5, AFF_PI, AFF_MATH, AFF_FA, AFF_FAUNG,
    MULTI_AFFECTION,
)
from ..core.chain import w3_read, snapshot_balances, safe, erc20
from ..core.wallet import fmt_pls, pls_balance
from ..core.event_logger import events as _events
from ..engines.token_factory import (
    TokenFactoryEngine, _AFF_ROUTE_DEFS,
)
from ..oracle.price import get_amounts_out, get_amounts_out_v2


def print_economics_table(engine: TokenFactoryEngine) -> None:
    """Price all routes and print a formatted economics table."""
    print(f"\n{'='*90}")
    print(f"  AFFECTION + WM Dual-Mode Route Economics")
    print(f"{'='*90}")

    gas_price = w3_read.eth.gas_price
    print(f"  Gas price: {gas_price / 1e9:.0f} Gwei")
    print(f"  Block: {w3_read.eth.block_number}")
    print()

    # AFF price
    aff_pls_v1 = get_amounts_out(10**18, [AFFECTION, WPLS])
    aff_pls_v2 = get_amounts_out_v2(10**18, [AFFECTION, WPLS])
    aff_price = max(
        (aff_pls_v1[-1] if aff_pls_v1 else 0),
        (aff_pls_v2[-1] if aff_pls_v2 else 0),
    )
    print(f"  AFF/PLS price: {aff_price / 1e18:.2f} PLS per AFF")

    # WM price
    wm_pls_v1 = get_amounts_out(10**18, [WM, WPLS])
    wm_pls_v2 = get_amounts_out_v2(10**18, [WM, WPLS])
    wm_price = max(
        (wm_pls_v1[-1] if wm_pls_v1 else 0),
        (wm_pls_v2[-1] if wm_pls_v2 else 0),
    )
    print(f"  WM/PLS price:  {wm_price / 1e18:.2f} PLS per WM")
    print()

    # Payment token prices
    print(f"  {'Token':<8} {'Address':<44} {'PLS/token':>12} {'Have':>12}")
    print(f"  {'-'*76}")
    for rdef in _AFF_ROUTE_DEFS:
        price = get_amounts_out(10**18, [rdef["addr"], WPLS])
        price_v2 = get_amounts_out_v2(10**18, [rdef["addr"], WPLS])
        best = max(
            (price[-1] if price else 0),
            (price_v2[-1] if price_v2 else 0),
        )
        bal = safe(erc20(rdef["addr"]), "balanceOf", JOEY_WALLET) or 0
        print(f"  {rdef['name']:<8} {rdef['addr']:<44} {best / 1e18:>12.4f} {bal / 1e18:>12.4f}")
    print()

    # Full route economics (10 loops = test size)
    test_loops = engine.TEST_AFF_LOOPS
    print(f"  Route Economics ({test_loops} loops = {test_loops * 3} AFF output):")
    print(f"  {'Route':<8} {'PayCost':>12} {'AFF Val':>12} {'Gas':>10} "
          f"{'TotalCost':>12} {'Net':>12} {'ROI':>8}")
    print(f"  {'-'*76}")

    routes = engine._evaluate_all_aff_routes(test_loops, gas_price)
    for r in routes:
        marker = "+" if r.profitable else "-"
        print(f"  {r.name:<8} {r.payment_cost_pls / 1e18:>12.1f} "
              f"{r.aff_value_pls / 1e18:>12.1f} {r.gas_cost_pls / 1e18:>10.1f} "
              f"{r.total_cost_pls / 1e18:>12.1f} {r.net_profit_pls / 1e18:>+12.1f} "
              f"{r.roi_pct:>7.1f}% {marker}")

    if not routes:
        print("  (no routes available)")

    # WM economics
    print()
    wm_route = engine._evaluate_wm_mint(engine.TEST_WM_COUNT, gas_price)
    if wm_route:
        marker = "+" if wm_route.profitable else "-"
        print(f"  WM mintWM({wm_route.count}): value={wm_route.wm_value_pls / 1e18:.1f} PLS, "
              f"gas={wm_route.gas_cost_pls / 1e18:.1f} PLS, "
              f"net={wm_route.net_profit_pls / 1e18:+.1f} PLS "
              f"({wm_route.roi_pct:.1f}% ROI) {marker}")
    else:
        print("  WM: not available (TGSV8 not set)")

    print(f"\n{'='*90}")

    # Best route summary
    if routes:
        best = routes[0]
        if best.profitable:
            print(f"\n  BEST ROUTE: {best.name} — PROFITABLE at {best.roi_pct:.1f}% ROI")
            print(f"  Net: {best.net_profit_pls / 1e18:+.1f} PLS per cycle")
        else:
            print(f"\n  BEST ROUTE: {best.name} — NOT profitable ({best.roi_pct:.1f}% ROI)")
            # Calculate breakeven
            needed_aff_price = best.total_cost_pls / best.aff_output_wei * 1e18
            print(f"  Need AFF at {needed_aff_price / 1e18:.2f} PLS "
                  f"(currently {aff_price / 1e18:.2f} PLS)")
            shortfall_pct = ((needed_aff_price - aff_price) / aff_price * 100
                             if aff_price > 0 else 0)
            print(f"  AFF needs to rise {shortfall_pct:.0f}% for {best.name} route profitability")
    print()


def run_test_cycle(engine: TokenFactoryEngine, dry_run: bool = False) -> None:
    """Execute one forced diagnostic cycle."""
    print(f"\n{'='*60}")
    print(f"  FORCED DIAGNOSTIC CYCLE")
    print(f"{'='*60}")

    # Reset nonce to chain state before sending TXs
    from ..core.wallet import reset_nonce
    reset_nonce()

    # Wallet balance
    snap = snapshot_balances()
    print(f"  PLS:  {snap['pls'] / 1e18:,.1f}")
    print(f"  AFF:  {snap['affection'] / 1e18:.4f}")
    print(f"  WM:   {snap['wm'] / 1e18:.4f}")
    print()

    # Enable force-test mode
    engine.FORCE_TEST = True

    if not engine.is_ready():
        print("  Engine NOT READY — check TGSV8/Multi AFFECTION availability")
        return

    print("  Running simulate()...")
    try:
        profit, gas = engine.simulate()
        print(f"  Simulate OK: profit={profit / 1e18:.1f} PLS, gas={gas / 1e18:.1f} PLS")
    except Exception as e:
        print(f"  Simulate failed: {e}")
        return

    print()
    if dry_run:
        print("  [DRY-RUN MODE — no TXs will be sent]")
    else:
        print("  EXECUTING — this will send real transactions!")

    print()
    result = engine.execute(dry_run=dry_run)
    _events.log_engine_result("TokenFactory", result)

    print(f"\n  {'='*50}")
    print(f"  Result: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"  Profit: {result.profit_pls:.4f} PLS")
    print(f"  Gas:    {result.gas_pls:.4f} PLS")
    print(f"  Net:    {result.net_pls:.4f} PLS")
    print(f"  TXs:    {len(result.tx_hashes)}")
    for tx in result.tx_hashes:
        print(f"    {tx}")
    print(f"  Notes:  {result.notes}")
    print(f"  {'='*50}\n")

    # Post-execution balances
    if not dry_run:
        snap_after = snapshot_balances()
        print(f"  Post-execution balances:")
        print(f"    PLS:  {snap_after['pls'] / 1e18:,.1f} "
              f"(delta: {(snap_after['pls'] - snap['pls']) / 1e18:+,.1f})")
        print(f"    AFF:  {snap_after['affection'] / 1e18:.4f} "
              f"(delta: {(snap_after['affection'] - snap['affection']) / 1e18:+.4f})")
        print(f"    WM:   {snap_after['wm'] / 1e18:.4f} "
              f"(delta: {(snap_after['wm'] - snap['wm']) / 1e18:+.4f})")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AFFECTION + WM Dual-Mode Mint Engine Diagnostic"
    )
    parser.add_argument("--execute", action="store_true",
                        help="Run one forced diagnostic cycle (sends real TXs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Execute in dry-run mode (simulate only)")
    args = parser.parse_args()

    engine = TokenFactoryEngine()

    # Always print economics table
    print_economics_table(engine)

    if args.execute or args.dry_run:
        run_test_cycle(engine, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
