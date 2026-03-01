"""
arb.py — Engine 1: LAU/Atropa Purchase → DEX Arbitrage

Wraps logic from scripts/scan_lau_arb.py (discovery) and scripts/tx_lau_arb.py (execution).

Flow per cycle:
  1. scan_tokens() — get ranked list of arb-eligible tokens (cached, TTL 1hr)
  2. rank_opportunities() — filter by profitability using exact Uniswap v2 formula
  3. Execute top opportunity: approve → Purchase(token) → approve(router) → swapExactTokensForETH

is_ready():  AFFECTION balance ≥ 1 AFFECTION (need payment capital)
simulate():  Scan + rank; return (top_profit_wei, estimated_gas_wei)
execute():   4-TX arb sequence on best opportunity
"""
import time
import logging

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, AFFECTION, WPLS, PULSEX_V1_ROUTER, MAX_SLIPPAGE,
)
from ..core.chain import erc20, purchasable, router_contract, safe, w3_submit
from ..core.executor import send_tx, approve_if_needed
from ..core.simulator import SimulationFailed, estimate_gas
from ..oracle.scanner import scan_tokens
from ..oracle.profitability import rank_opportunities

log = logging.getLogger(__name__)

# Approximate gas for the 4-TX arb sequence (approve×2 + purchase + swap)
# Used for profitability pre-check before a real estimate_gas() call
ARB_GAS_ESTIMATE = 400_000  # conservative (real is ~250-350K total)


class ArbEngine(EngineBase):
    """
    Engine 1: Purchase DYSNOMIA tokens at fixed market rate → sell on PulseX.
    Covers all 272 QING assets (AFFECTION routes) and Atropa tokens (pDAI routes).
    """
    name = "Arb"

    def __init__(self):
        super().__init__()
        self._top_opportunity: dict | None = None

    def is_ready(self) -> bool:
        """Need at least 1 AFFECTION (or pDAI) to buy anything."""
        aff = erc20(AFFECTION)
        bal = safe(aff, "balanceOf", JOEY_WALLET) or 0
        if bal >= 10**18:
            return True
        log.debug("ArbEngine not ready: AFFECTION balance %.4f < 1", bal / 1e18)
        return False

    def simulate(self) -> tuple[int, int]:
        """
        Scan all tokens, rank by profitability, cache top opportunity.
        Returns (expected_profit_wei, expected_gas_wei).
        Raises SimulationFailed if no profitable opportunity found.
        """
        from ..core.chain import w3_read
        gas_price = w3_read.eth.gas_price
        gas_cost_wei = ARB_GAS_ESTIMATE * gas_price

        tokens = scan_tokens()
        ranked = rank_opportunities(tokens, gas_cost_wei)

        if not ranked:
            raise SimulationFailed("No profitable arb opportunities in scan")

        top = ranked[0]
        self._top_opportunity = top

        log.info(
            "ArbEngine top: %s (%s) — profit %.4f PLS (impact %.1f%%)",
            top["label"], top["symbol"],
            top["profit_wei"] / 1e18,
            top["impact_pct"],
        )

        return top["profit_wei"], gas_cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """Execute the top arb opportunity found in simulate()."""
        # Re-run simulate if no cached opportunity
        if self._top_opportunity is None:
            try:
                self.simulate()
            except SimulationFailed as exc:
                return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))

        opp = self._top_opportunity
        self._top_opportunity = None  # Consume — force re-scan next cycle

        token_addr   = opp["address"]
        payment_addr = opp["payment"]
        token_amount = opp["token_amount"]
        expected_pls = opp["dex_out_wei"]
        token_sym    = opp.get("symbol", "?")

        router = router_contract(w3=w3_submit)
        token_c   = w3_submit.eth.contract(address=token_addr,   abi=purchasable(token_addr)._abi)
        payment_c = w3_submit.eth.contract(address=payment_addr, abi=erc20(payment_addr)._abi)
        token_erc = w3_submit.eth.contract(address=token_addr,   abi=erc20(token_addr)._abi)

        deadline = int(time.time()) + 300
        min_pls  = int(expected_pls * (1 - MAX_SLIPPAGE))

        payment_cost = token_amount * opp["rate"] // 10**18
        tx_hashes = []
        gas_spent = 0

        try:
            log.info("Arb: %s — buying %s %s for %.4f payment tokens",
                     opp["label"], token_amount / 1e18, token_sym, payment_cost / 1e18)

            # Step 1: Approve payment token to target contract
            r = approve_if_needed(payment_c, token_addr, payment_cost, payment_addr, dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 2: Purchase tokens at fixed market rate
            r = send_tx(
                token_c.functions.Purchase(payment_addr, token_amount),
                f"Purchase {token_sym}",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Verify we received tokens
            received = safe(token_erc, "balanceOf", JOEY_WALLET) or 0
            if not dry_run and received == 0:
                raise AssertionError(f"Purchase returned 0 {token_sym}")

            # Step 3: Approve router to spend received tokens
            sell_amount = received if not dry_run else token_amount
            r = approve_if_needed(token_erc, PULSEX_V1_ROUTER, sell_amount, token_sym, dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 4: Swap tokens → native PLS
            r = send_tx(
                router.functions.swapExactTokensForETH(
                    sell_amount, min_pls, [token_addr, WPLS], JOEY_WALLET, deadline
                ),
                f"Swap {token_sym} → PLS",
                dry_run=dry_run,
                skip_simulate=True,  # ETH-out needs skip due to native value
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            log.info("Arb complete: %s. TXs: %d", token_sym, len(tx_hashes))
            return EngineResult(
                success=True,
                profit_wei=expected_pls,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"Arb: {opp['label']} ({token_sym})",
            )

        except (SimulationFailed, AssertionError, Exception) as exc:
            log.error("ArbEngine execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )


if __name__ == "__main__":
    import argparse, logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description="Arb Engine standalone test")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-scan", action="store_true")
    args = parser.parse_args()

    if args.force_scan:
        from ..oracle.scanner import invalidate_cache
        invalidate_cache()

    engine = ArbEngine()
    print(f"Ready: {engine.is_ready()}")
    try:
        profit, gas = engine.simulate()
        print(f"Top opportunity: profit={profit/1e18:.4f} PLS  gas={gas/1e18:.4f} PLS")
        print(f"ROI: {engine.roi():.2f}x")
        if args.dry_run:
            result = engine.execute(dry_run=True)
            print(f"Dry-run result: {result}")
    except SimulationFailed as e:
        print(f"No opportunity: {e}")
