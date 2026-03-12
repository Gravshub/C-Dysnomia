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

from .config import (
    JOEY_WALLET, GIBS_LAU, AFFECTION, WPLS,
    PULSEX_V1_ROUTER, PLS_GAS_FLOOR, PLS_REPLENISH, MAX_SLIPPAGE,
)
from .chain import erc20, router_contract, safe
from .wallet import pls_balance, fmt_pls, account
from .executor import send_tx, approve_if_needed
from .simulator import SimulationFailed

log = logging.getLogger(__name__)


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
                "GAS LOW: %s < floor %s",
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

        router = router_contract(w3=None)
        deadline = int(time.time()) + 300

        # Try GIBS first
        gibs = erc20(GIBS_LAU)
        gibs_bal = safe(gibs, "balanceOf", JOEY_WALLET) or 0

        if gibs_bal > 0:
            # Calculate how much GIBS to sell to receive need_wei PLS
            try:
                amounts = safe(router, "getAmountsOut", gibs_bal, [GIBS_LAU, WPLS])
                if amounts and amounts[-1] >= need_wei:
                    # Partial sell — use getAmountsIn to find exact GIBS needed
                    partial_amounts = safe(
                        router, "getAmountsIn", need_wei, [GIBS_LAU, WPLS]
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
            log.info("Selling %.4f GIBS for PLS", sell_gibs / 1e18)

            try:
                approve_if_needed(gibs, PULSEX_V1_ROUTER, sell_gibs, "GIBS", dry_run=dry_run)
                send_tx(
                    router.functions.swapExactTokensForETH(
                        sell_gibs, min_pls, [GIBS_LAU, WPLS], JOEY_WALLET, deadline
                    ),
                    "Emergency: GIBS → PLS",
                    dry_run=dry_run,
                    skip_simulate=True,  # ETH-out functions need skip due to msg.value
                )
                log.info("Refill complete. PLS: %s", fmt_pls(pls_balance()))
                return True
            except (SimulationFailed, AssertionError) as exc:
                log.error("GIBS sell failed: %s — trying AFFECTION fallback", exc)

        # Fallback: sell AFFECTION
        aff = erc20(AFFECTION)
        aff_bal = safe(aff, "balanceOf", JOEY_WALLET) or 0

        if aff_bal > 0:
            # Calculate partial sell amount
            try:
                amounts = safe(router, "getAmountsOut", aff_bal, [AFFECTION, WPLS])
                if amounts and amounts[-1] >= need_wei:
                    partial = safe(router, "getAmountsIn", need_wei, [AFFECTION, WPLS])
                    sell_aff = min(partial[0] if partial else aff_bal, aff_bal)
                else:
                    sell_aff = aff_bal
            except Exception:
                sell_aff = aff_bal

            min_pls = int(need_wei * (1 - MAX_SLIPPAGE))
            log.info("Selling %.4f AFFECTION for PLS (fallback)", sell_aff / 1e18)
            try:
                approve_if_needed(aff, PULSEX_V1_ROUTER, sell_aff, "AFFECTION", dry_run=dry_run)
                send_tx(
                    router.functions.swapExactTokensForETH(
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
