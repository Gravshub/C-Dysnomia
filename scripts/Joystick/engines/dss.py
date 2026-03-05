"""
dss.py — Engine 2: DSS chatAndClaimWithMultiplier → GIBS → PLS

Calls DysnomiaSelfSnipev4.chatAndClaimWithMultiplier() which mints
(1 + multiplier) GIBS tokens per call (currently 18 GIBS at multiplier=17).

Break-even: GIBS DEX price > gas_cost / 18 GIBS per call.
At current ~388 PLS gas/call → needs GIBS > 21.5 PLS to be profitable.

Prerequisites:
  - GIBS/WPLS PulseX V1 pair must exist (run scripts/tx_create_gibs_pair.py first)
  - GIBS DEX price must exceed break-even threshold

is_ready():  GIBS/WPLS pair exists AND GIBS price > break-even threshold
simulate():  gibs_price * gibs_per_call - gas_cost
execute():   chatAndClaimWithMultiplier(msg) → GIBS received → approve → swapExactTokensForETH
"""
import time
import logging

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, GIBS_LAU, WPLS, DSS, PULSEX_V1_FACTORY, PULSEX_V1_ROUTER, MAX_SLIPPAGE,
)
from ..core.chain import (
    erc20, factory_contract, pair_contract, router_contract, safe, w3_submit, DSS_ABI,
)
from ..core.executor import send_tx, approve_if_needed
from ..core.simulator import SimulationFailed, estimate_gas
from ..oracle.price import token_price_pls

log = logging.getLogger(__name__)

# Approximate gas for chatAndClaimWithMultiplier + approve + swap
DSS_GAS_ESTIMATE = 380_000


class DSSEngine(EngineBase):
    """
    Engine 2: Mint GIBS via DSS multiplier → sell on PulseX.
    Only active when GIBS has a DEX pair and price exceeds break-even.
    """
    name = "DSS"

    def _get_gibs_pair(self) -> str | None:
        """Return GIBS/WPLS pair address if it exists, else None."""
        factory = factory_contract(PULSEX_V1_FACTORY)
        pair_addr = safe(factory, "getPair", GIBS_LAU, WPLS)
        if not pair_addr or pair_addr == "0x" + "0" * 40:
            return None
        return pair_addr

    def _gibs_per_call(self) -> int:
        """Read current multiplier from DSS contract → return total GIBS per call."""
        dss_c = w3_submit.eth.contract(address=DSS, abi=DSS_ABI)
        mult = safe(dss_c, "multiplier") or 17
        return (mult + 1) * 10**18  # e.g. multiplier=17 → 18 GIBS

    def is_ready(self) -> bool:
        """GIBS/WPLS pair must exist and GIBS price must exceed break-even."""
        pair = self._get_gibs_pair()
        if not pair:
            log.debug("DSSEngine not ready: no GIBS/WPLS pair (run tx_create_gibs_pair.py)")
            return False

        gibs_per_call = self._gibs_per_call()
        gibs_price = token_price_pls(GIBS_LAU, 10**18)
        if not gibs_price:
            log.debug("DSSEngine not ready: GIBS price oracle failed")
            return False

        gas_price    = w3_submit.eth.gas_price
        gas_cost_wei = DSS_GAS_ESTIMATE * gas_price
        revenue_wei  = gibs_price * gibs_per_call // 10**18
        break_even   = gas_cost_wei / (gibs_per_call / 10**18)

        log.debug(
            "DSS: GIBS=%.4f PLS, per_call=%d GIBS, gas=%.4f PLS, break-even=%.2f PLS/GIBS",
            gibs_price / 1e18, gibs_per_call // 10**18,
            gas_cost_wei / 1e18, break_even / 1e18
        )

        return revenue_wei > gas_cost_wei

    def simulate(self) -> tuple[int, int]:
        """Return (expected revenue wei, gas cost wei) for one chatAndClaim call."""
        if not self._get_gibs_pair():
            raise SimulationFailed("No GIBS/WPLS pair — run scripts/tx_create_gibs_pair.py")

        gibs_per_call = self._gibs_per_call()
        gibs_price    = token_price_pls(GIBS_LAU, 10**18)
        if not gibs_price:
            raise SimulationFailed("GIBS price oracle failed")

        gas_price    = w3_submit.eth.gas_price
        gas_cost_wei = DSS_GAS_ESTIMATE * gas_price
        revenue_wei  = gibs_price * gibs_per_call // 10**18

        if revenue_wei <= gas_cost_wei:
            raise SimulationFailed(
                f"DSS unprofitable: revenue {revenue_wei/1e18:.4f} PLS "
                f"<= gas {gas_cost_wei/1e18:.4f} PLS"
            )
        return revenue_wei, gas_cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """chatAndClaimWithMultiplier → receive GIBS → swap to native PLS."""
        dss_c   = w3_submit.eth.contract(address=DSS,     abi=DSS_ABI)
        gibs_c  = w3_submit.eth.contract(address=GIBS_LAU, abi=erc20(GIBS_LAU)._abi)
        router  = router_contract(w3=w3_submit)
        deadline = int(time.time()) + 300

        try:
            revenue_wei, gas_cost_wei = self.simulate()
        except SimulationFailed as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))

        gibs_per_call = self._gibs_per_call()
        min_pls = int((revenue_wei * (1 - MAX_SLIPPAGE)))

        tx_hashes = []
        gas_spent = 0

        try:
            # Step 1: Mint GIBS via DSS
            block_num = w3_submit.eth.block_number
            msg = f"|>JOYSTICK<| block {block_num}"
            r = send_tx(
                dss_c.functions.chatAndClaimWithMultiplier(msg),
                "DSS chatAndClaimWithMultiplier",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Verify GIBS received
            received = safe(gibs_c, "balanceOf", JOEY_WALLET) or 0
            sell_amount = received if not dry_run else gibs_per_call
            if not dry_run and sell_amount == 0:
                raise AssertionError("chatAndClaimWithMultiplier returned 0 GIBS")

            # Step 2: Approve router for GIBS
            r = approve_if_needed(gibs_c, PULSEX_V1_ROUTER, sell_amount, "GIBS", dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 3: Swap GIBS → native PLS
            r = send_tx(
                router.functions.swapExactTokensForETH(
                    sell_amount, min_pls, [GIBS_LAU, WPLS], JOEY_WALLET, deadline
                ),
                "Swap GIBS → PLS",
                dry_run=dry_run,
                skip_simulate=True,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            log.info("DSS complete: minted %d GIBS → PLS", sell_amount // 10**18)
            return EngineResult(
                success=True,
                profit_wei=revenue_wei,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"DSS: {sell_amount // 10**18} GIBS",
            )

        except (SimulationFailed, AssertionError, Exception) as exc:
            log.error("DSSEngine execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )
