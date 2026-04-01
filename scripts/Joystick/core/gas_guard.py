"""
gas_guard.py — PLS gas buffer monitor and emergency token-sell refill.

The gas guard is checked at the START of every bot cycle.
If PLS drops below PLS_GAS_FLOOR (default 100K PLS), all engines pause
and emergency_refill() sells the cheapest-to-re-acquire token (GIBS) for PLS.

Target after refill: PLS_REPLENISH (default 200K PLS).
GIBS is the preferred sell token because it can be re-minted via DSS cheaply.
Fallback: sell AFFECTION if GIBS insufficient.
"""
import time
import logging

from .log_names import get_logger

from .config import (
    JOEY_WALLET, GIBS_LAU, AFFECTION, WPLS,
    PULSEX_V1_ROUTER, PULSEX_V2_ROUTER, PLS_GAS_FLOOR, PLS_REPLENISH, MAX_SLIPPAGE,
)
from .chain import erc20, router_contract, safe, ROUTER_ABI, w3_submit
from .wallet import pls_balance, fmt_pls, account
from .executor import send_tx, approve_if_needed
from .simulator import SimulationFailed

log = get_logger(__name__)


class GasGuard:
    """
    Monitors PLS balance and sells tokens to refill when needed.

    Usage:
        guard = GasGuard()
        if not guard.check():
            guard.emergency_refill()
    """

    def check(self) -> bool:
        """True if native PLS ≥ PLS_GAS_FLOOR."""
        bal = pls_balance()
        ok = bal >= PLS_GAS_FLOOR
        if not ok:
            log.warning(
                "🚨 GAS LOW: %s < floor %s",
                fmt_pls(bal), fmt_pls(PLS_GAS_FLOOR)
            )
        return ok

    def status(self) -> dict:
        """Return current PLS balance and guard thresholds."""
        bal = pls_balance()
        return {
            "pls_wei":     bal,
            "pls_human":   fmt_pls(bal),
            "floor_wei":   PLS_GAS_FLOOR,
            "replenish_wei": PLS_REPLENISH,
            "ok":          bal >= PLS_GAS_FLOOR,
        }

    def emergency_refill(self, *, dry_run: bool = False) -> bool:
        """
        Sell tokens to refill PLS to PLS_REPLENISH level.

        Strategy:
          1. Try GIBS → native PLS (cheapest to re-acquire via DSS)
          2. Fallback: AFFECTION → native PLS

        Returns True if refill succeeded, False if nothing to sell.
        """
        need_wei = PLS_REPLENISH - pls_balance()
        if need_wei <= 0:
            return True  # Already above target

        log.warning("Emergency refill needed: %s", fmt_pls(need_wei))

        # GIBS/WPLS is a V2 pair — use V2 router for GIBS sell
        router_v2 = w3_submit.eth.contract(address=PULSEX_V2_ROUTER, abi=ROUTER_ABI)
        router_v1 = router_contract(w3=w3_submit)
        deadline = int(time.time()) + 300

        # Try GIBS first (V2 pair)
        gibs = erc20(GIBS_LAU)
        gibs_bal = safe(gibs, "balanceOf", JOEY_WALLET) or 0

        if gibs_bal > 0:
            # Try V2 first, then V1 (matches AFF fallback pattern)
            gibs_router = router_v2
            gibs_router_addr = PULSEX_V2_ROUTER
            try:
                amounts = safe(gibs_router, "getAmountsOut", gibs_bal, [GIBS_LAU, WPLS])
                if not amounts or amounts[-1] == 0:
                    # No V2 liquidity — fall back to V1
                    gibs_router = router_v1
                    gibs_router_addr = PULSEX_V1_ROUTER
                    amounts = safe(gibs_router, "getAmountsOut", gibs_bal, [GIBS_LAU, WPLS])
            except Exception:
                gibs_router = router_v1
                gibs_router_addr = PULSEX_V1_ROUTER
                amounts = safe(gibs_router, "getAmountsOut", gibs_bal, [GIBS_LAU, WPLS])

            # Calculate how much GIBS to sell to receive need_wei PLS
            try:
                if amounts and amounts[-1] >= need_wei:
                    partial_amounts = safe(
                        gibs_router, "getAmountsIn", need_wei, [GIBS_LAU, WPLS]
                    )
                    sell_gibs = min(
                        partial_amounts[0] if partial_amounts else gibs_bal,
                        gibs_bal,
                    )
                else:
                    sell_gibs = gibs_bal  # Sell all
            except Exception:
                sell_gibs = gibs_bal

            min_pls = int(need_wei * (1 - MAX_SLIPPAGE))
            dex_label = "V2" if gibs_router_addr == PULSEX_V2_ROUTER else "V1"
            log.info("Selling %.4f GIBS for PLS (%s)", sell_gibs / 1e18, dex_label)

            try:
                approve_if_needed(gibs, gibs_router_addr, sell_gibs, "GIBS", dry_run=dry_run)
                send_tx(
                    gibs_router.functions.swapExactTokensForETH(
                        sell_gibs, min_pls, [GIBS_LAU, WPLS], JOEY_WALLET, deadline
                    ),
                    f"Emergency: GIBS → PLS ({dex_label})",
                    dry_run=dry_run,
                    skip_simulate=True,  # ETH-out functions need skip due to msg.value
                )
                log.info("Refill complete. PLS: %s", fmt_pls(pls_balance()))
                return True
            except (SimulationFailed, AssertionError) as exc:
                log.error("GIBS sell failed: %s — trying AFFECTION fallback", exc)

        # Fallback: sell AFFECTION (try V2 first, fall back to V1)
        aff = erc20(AFFECTION)
        aff_bal = safe(aff, "balanceOf", JOEY_WALLET) or 0

        if aff_bal > 0:
            # Try V2 first, then V1
            aff_router = router_v2
            aff_router_addr = PULSEX_V2_ROUTER
            try:
                amounts = safe(aff_router, "getAmountsOut", aff_bal, [AFFECTION, WPLS])
                if not amounts or amounts[-1] == 0:
                    # No V2 pair — fall back to V1
                    aff_router = router_v1
                    aff_router_addr = PULSEX_V1_ROUTER
                    amounts = safe(aff_router, "getAmountsOut", aff_bal, [AFFECTION, WPLS])
            except Exception:
                aff_router = router_v1
                aff_router_addr = PULSEX_V1_ROUTER
                amounts = safe(aff_router, "getAmountsOut", aff_bal, [AFFECTION, WPLS])

            try:
                if amounts and amounts[-1] >= need_wei:
                    partial = safe(aff_router, "getAmountsIn", need_wei, [AFFECTION, WPLS])
                    sell_aff = min(partial[0] if partial else aff_bal, aff_bal)
                else:
                    sell_aff = aff_bal
            except Exception:
                sell_aff = aff_bal

            min_pls = int(need_wei * (1 - MAX_SLIPPAGE))
            log.info("Selling %.4f AFFECTION for PLS (fallback)", sell_aff / 1e18)
            try:
                approve_if_needed(aff, aff_router_addr, sell_aff, "AFFECTION", dry_run=dry_run)
                send_tx(
                    aff_router.functions.swapExactTokensForETH(
                        sell_aff, min_pls, [AFFECTION, WPLS], JOEY_WALLET, deadline
                    ),
                    "Emergency: AFFECTION → PLS",
                    dry_run=dry_run,
                    skip_simulate=True,
                )
                log.info("Refill complete. PLS: %s", fmt_pls(pls_balance()))
                return True
            except (SimulationFailed, AssertionError) as exc:
                log.error("AFFECTION sell also failed: %s", exc)

        log.error("Emergency refill FAILED — no sellable tokens available")
        return False
