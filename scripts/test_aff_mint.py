"""
test_aff_mint.py — AFFECTION Generate() mainnet test.

Exercises the full TokenFactory AFF path:
  1. Environment & wallet check
  2. Multi AFFECTION contract connectivity
  3. _evaluate_aff_generate() profitability (read-only)
  4. Dry-run execute
  5. LIVE single-TX execution (multiGenerate → swap AFF→WPLS)

Usage:
  python scripts/test_aff_mint.py              # evaluate + dry-run only
  python scripts/test_aff_mint.py --live       # execute live TX
  python scripts/test_aff_mint.py --batch N    # override batch size
"""
import argparse
import logging
import os
import sys
import time

# Ensure .env is loaded before any Joystick imports
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Set up logging before imports that trigger RPC connections
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("test_aff_mint")

# ── Joystick imports ──────────────────────────────────────────────────────
from scripts.Joystick.core.config import (
    JOEY_WALLET, AFFECTION, WPLS, MULTI_AFFECTION,
    PULSEX_V1_ROUTER, PULSEX_V2_ROUTER,
    GAS_PRICE_CEIL, GAS_MULT, MAX_SLIPPAGE,
)
from scripts.Joystick.core.chain import (
    w3_read, w3_submit, erc20, safe,
    multi_affection_contract, ROUTER_ABI,
)
from scripts.Joystick.core import wallet
from scripts.Joystick.oracle.price import (
    get_amounts_out, get_amounts_out_v2, get_reserves,
)
from scripts.Joystick.engines.token_factory import TokenFactoryEngine


def fmt(wei: int) -> str:
    return f"{wei / 1e18:,.4f}"


def run_test(live: bool = False, batch_override: int | None = None):
    log.info("=" * 70)
    log.info("  AFFECTION Generate() Mainnet Test")
    log.info("=" * 70)

    # ── Step 1: Environment ──────────────────────────────────────────────
    log.info("\n── Step 1: Environment Check ──")
    log.info("  Wallet:          %s", JOEY_WALLET)
    log.info("  AFFECTION:       %s", AFFECTION)
    log.info("  MULTI_AFFECTION: %s", MULTI_AFFECTION)

    # Wallet
    try:
        acct = wallet._load_account()
        log.info("  Wallet loaded:   %s ✓", acct.address)
    except Exception as e:
        log.error("  Wallet load FAILED: %s", e)
        return

    # PLS balance
    pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
    log.info("  PLS balance:     %s PLS", fmt(pls_bal))

    # AFF balance
    aff_c = erc20(AFFECTION)
    aff_bal = safe(aff_c, "balanceOf", JOEY_WALLET) or 0
    log.info("  AFF balance:     %s AFF", fmt(aff_bal))

    # Gas price
    gas_price = w3_read.eth.gas_price
    gas_gwei = gas_price / 1e9
    log.info("  Gas price:       %.2f Gwei (%s Impulses)", gas_gwei, gas_price)
    log.info("  Gas ceiling:     %.0f Gwei", GAS_PRICE_CEIL / 1e9)

    # ── Step 2: Contract connectivity ────────────────────────────────────
    log.info("\n── Step 2: Contract Connectivity ──")
    try:
        multi = multi_affection_contract()
        log.info("  Multi AFFECTION loaded at %s ✓", multi.address)
    except Exception as e:
        log.error("  Multi AFFECTION load FAILED: %s", e)
        return

    # Verify contract has code (not an EOA)
    code = w3_read.eth.get_code(MULTI_AFFECTION)
    log.info("  Contract code:   %d bytes %s", len(code), "✓" if len(code) > 2 else "✗ EMPTY")
    if len(code) <= 2:
        log.error("  No code at Multi AFFECTION address — wrong address?")
        return

    # ── Step 3: DEX Price Discovery ──────────────────────────────────────
    log.info("\n── Step 3: DEX Price Discovery ──")
    test_amount = 1 * 10**18  # 1 AFF

    v1_out = get_amounts_out(test_amount, [AFFECTION, WPLS])
    v2_out = get_amounts_out_v2(test_amount, [AFFECTION, WPLS])

    v1_price = v1_out[-1] / 1e18 if v1_out else 0
    v2_price = v2_out[-1] / 1e18 if v2_out else 0
    log.info("  AFF/WPLS V1:     %.4f PLS/AFF %s", v1_price, "✓" if v1_price > 0 else "✗ no pair")
    log.info("  AFF/WPLS V2:     %.4f PLS/AFF %s", v2_price, "✓" if v2_price > 0 else "✗ no pair")

    # Pool reserves
    for label in ("V2", "V1"):
        reserves = get_reserves(AFFECTION, WPLS, label)
        if reserves:
            log.info("  %s reserves:    AFF=%s  WPLS=%s", label, fmt(reserves[0]), fmt(reserves[1]))

    # ── Step 4: Gas Estimation ───────────────────────────────────────────
    log.info("\n── Step 4: Gas Estimation (eth_estimateGas) ──")
    batch = batch_override or 100
    aff_minted = batch * 3

    for test_batch in [1, 5, 10, 25, 50, 100]:
        if batch_override and test_batch != batch_override:
            continue
        try:
            gas_est = multi.functions.multiGenerate(test_batch).estimate_gas(
                {"from": JOEY_WALLET}
            )
            gas_cost_pls = gas_est * gas_price / 1e18
            minted = test_batch * 3
            cost_per_aff = gas_cost_pls / minted if minted > 0 else 0
            best_price = max(v1_price, v2_price)
            gross_value = minted * best_price
            net_profit = gross_value - gas_cost_pls
            roi = (net_profit / gas_cost_pls * 100) if gas_cost_pls > 0 else 0
            log.info(
                "  N=%-3d  gas=%-10d  cost=%-10.2f PLS  mint=%-4d AFF  "
                "cost/AFF=%-8.2f  value=%-10.2f  net=%-10.2f  ROI=%.0f%%",
                test_batch, gas_est, gas_cost_pls, minted,
                cost_per_aff, gross_value, net_profit, roi,
            )
        except Exception as e:
            log.warning("  N=%-3d  FAILED: %s", test_batch, e)

    # ── Step 5: Engine Evaluation ────────────────────────────────────────
    log.info("\n── Step 5: TokenFactory Engine Evaluation ──")
    engine = TokenFactoryEngine()
    if batch_override:
        engine.AFF_DEFAULT_BATCH = batch_override

    log.info("  is_ready(): %s", engine.is_ready())

    aff_eval = engine._evaluate_aff_generate()
    if aff_eval:
        log.info("  ✓ AFF Generate PROFITABLE")
        log.info("    Batch:       %d", aff_eval["batch"])
        log.info("    AFF minted:  %d", aff_eval["aff_minted"])
        log.info("    Gas cost:    %s PLS", fmt(aff_eval["gas_cost_wei"]))
        log.info("    Gross output:%s PLS", fmt(aff_eval["gross_output_wei"]))
        log.info("    Net profit:  %s PLS", fmt(aff_eval["net_profit_wei"]))
        log.info("    ROI:         %.1f%%", aff_eval["roi_pct"])
        log.info("    Sell DEX:    %s", aff_eval["sell_dex"])
    else:
        log.warning("  ✗ AFF Generate not profitable at current conditions")

    # ── Step 6: Dry-run ──────────────────────────────────────────────────
    log.info("\n── Step 6: Dry-Run Execute ──")
    try:
        profit, gas = engine.simulate()
        log.info("  simulate() → profit=%s PLS, gas=%s PLS", fmt(profit), fmt(gas))
    except Exception as e:
        log.error("  simulate() FAILED: %s", e)

    result = engine.execute(dry_run=True)
    log.info("  execute(dry_run=True):")
    log.info("    success:  %s", result.success)
    log.info("    profit:   %s PLS", fmt(result.profit_wei))
    log.info("    gas:      %s PLS", fmt(result.gas_wei))
    log.info("    notes:    %s", result.notes)

    if not live:
        log.info("\n── Done (dry-run only). Pass --live to execute on-chain. ──")
        return

    # ── Step 7: LIVE execution ───────────────────────────────────────────
    if not aff_eval:
        log.error("\n  Cannot execute live — evaluation returned not profitable.")
        return

    log.info("\n── Step 7: LIVE Execution ──")
    log.info("  ⚠ Sending real transactions on PulseChain mainnet")
    log.info("  Batch: %d → %d AFF → swap on %s",
             aff_eval["batch"], aff_eval["aff_minted"], aff_eval["sell_dex"])
    log.info("  Expected net profit: %s PLS (%.0f%% ROI)",
             fmt(aff_eval["net_profit_wei"]), aff_eval["roi_pct"])

    # Reset nonce for fresh state
    wallet.reset_nonce()
    nonce = wallet.peek_nonce()
    log.info("  Nonce: %d", nonce)

    # Record balances before
    pls_before = w3_read.eth.get_balance(JOEY_WALLET)
    aff_before = safe(aff_c, "balanceOf", JOEY_WALLET) or 0

    t0 = time.time()
    result = engine.execute(dry_run=False)
    elapsed = time.time() - t0

    # Record balances after
    pls_after = w3_read.eth.get_balance(JOEY_WALLET)
    aff_after = safe(aff_c, "balanceOf", JOEY_WALLET) or 0

    log.info("\n── Results ──")
    log.info("  Success:       %s", result.success)
    log.info("  TX hashes:     %s", result.tx_hashes)
    log.info("  Reported profit: %s PLS", fmt(result.profit_wei))
    log.info("  Reported gas:    %s PLS", fmt(result.gas_wei))
    log.info("  Notes:         %s", result.notes)
    log.info("  Elapsed:       %.1fs", elapsed)
    log.info("")
    log.info("  PLS before:    %s", fmt(pls_before))
    log.info("  PLS after:     %s", fmt(pls_after))
    log.info("  PLS delta:     %s PLS", fmt(pls_after - pls_before))
    log.info("")
    log.info("  AFF before:    %s", fmt(aff_before))
    log.info("  AFF after:     %s", fmt(aff_after))
    log.info("  AFF delta:     %s AFF", fmt(aff_after - aff_before))

    if result.success:
        realized = pls_after - pls_before
        log.info("\n  ✓ REALIZED PLS PROFIT: %s PLS", fmt(realized))
    else:
        log.error("\n  ✗ Execution failed: %s", result.notes)

    log.info("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AFFECTION Generate() mainnet test")
    parser.add_argument("--live", action="store_true", help="Execute live on-chain TX")
    parser.add_argument("--batch", type=int, default=None, help="Override batch size (default: 100)")
    args = parser.parse_args()
    run_test(live=args.live, batch_override=args.batch)
