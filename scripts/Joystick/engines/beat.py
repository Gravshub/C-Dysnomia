"""
beat.py — Engine 4: CHEON.Su() → META.Beat() → Territory metrics

Wraps the logic from scripts/tx_full_beat_flow.py.
Beat establishes territorial position (Dione, Charge, Deimos, Yeo) for GIBS QING.
When WORLD contract deploys, Beat output → WORLD.Code(lat, lon, QING) → VITUS rewards.

Until WORLD deploys, Beat runs periodically to:
  - Maintain active territory presence
  - Prime YUE bars (CHEON.Su) for better metrics
  - Build the game-layer position for future VITUS claiming

is_ready():  SHIO balances > 0 at GIBS_LAU (Fornax + Fomalhaute + CHO)
simulate():  META.Beat(GIBS_QING_WAAT).call() — verify no revert; gas estimate
execute():   [optional CHEON.Su()] → META.Beat(GIBS_QING_WAAT)

Beat is a "strategic" engine — it runs even at 0 direct profit to build position.
The bot treats it as lowest-priority when other engines have positive ROI.
"""
import logging

from ..core.log_names import get_logger

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, GIBS_LAU, GIBS_QING, GIBS_QING_WAAT,
    META, CHEON, FORNAX, FOMALHAUTE, CHO,
)
from ..core.chain import erc20, safe, w3_submit, META_ABI, CHEON_ABI
from ..core.executor import send_tx
from ..core.simulator import SimulationFailed, simulate, estimate_gas

log = get_logger(__name__)

# Minimum SHIO balance required (1 token / 1e18 units)
MIN_SHIO_WEI = 10**12  # 0.000001 — just above zero

# Strategic minimum profit: Beat always runs if no other engine has profit,
# but only if gas cost is "reasonable" (< this threshold)
BEAT_MAX_GAS_PLS = 3.0 * 10**18  # 3 PLS max gas to bother running Beat


class BeatEngine(EngineBase):
    """
    Engine 4: META.Beat() territory computation.
    Strategic engine — provides game-layer value even without direct PLS profit.
    """
    name = "Beat"
    MAX_FAILURES = 5  # More lenient — Beat is strategic, not profit-critical

    def __init__(self, with_cheon: bool = True):
        super().__init__()
        self.with_cheon = with_cheon  # Run CHEON.Su() before Beat (recommended for fresh state)

    def is_ready(self) -> bool:
        """Verify SHIO balances are present at GIBS_LAU (Beat prerequisite)."""
        fornax_c    = erc20(FORNAX)
        fomalhaute_c = erc20(FOMALHAUTE)
        cho_c       = erc20(CHO)

        f   = safe(fornax_c,    "balanceOf", GIBS_LAU) or 0
        fom = safe(fomalhaute_c,"balanceOf", GIBS_LAU) or 0
        cho = safe(cho_c,       "balanceOf", GIBS_LAU) or 0

        if f < MIN_SHIO_WEI:
            log.debug("BeatEngine not ready: Fornax at GIBS_LAU = 0 (run tx_acquire_shio_p2.py)")
            return False
        if fom < MIN_SHIO_WEI:
            log.debug("BeatEngine not ready: Fomalhaute at GIBS_LAU = 0")
            return False
        if cho < MIN_SHIO_WEI:
            log.debug("BeatEngine not ready: CHO at GIBS_LAU = 0")
            return False
        return True

    def simulate(self) -> tuple[int, int]:
        """
        Dry-run META.Beat to confirm it won't revert, then estimate gas.
        Returns (0, gas_cost_wei) — Beat has no direct PLS profit until WORLD deploys.
        Raises SimulationFailed if Beat would revert.
        """
        meta_c = w3_submit.eth.contract(address=META, abi=META_ABI)
        beat_fn = meta_c.functions.Beat(GIBS_QING_WAAT)

        # Free simulation — verifies Beat won't revert
        try:
            result = simulate(beat_fn)
            dione, charge, deimos, yeo = result
            log.info(
                "Beat dry-run: Dione=%s Charge=%s Deimos=%s Yeo=%s",
                dione, charge, deimos, yeo,
            )
        except SimulationFailed:
            # If direct Beat fails, try with CHEON.Su() first
            if self.with_cheon:
                log.info("Beat direct sim failed — Su() may fix it (will try in execute)")
            else:
                raise

        # Estimate gas (Beat alone, CHEON adds ~200-300K if used)
        gas_price = w3_submit.eth.gas_price
        try:
            gas_est = estimate_gas(beat_fn)
        except SimulationFailed:
            # Su() needed — estimate conservatively
            gas_est = 2_500_000
        gas_cost_wei = int(gas_est * gas_price * 1.3)

        if gas_cost_wei > BEAT_MAX_GAS_PLS:
            raise SimulationFailed(
                f"Beat gas cost {gas_cost_wei/1e18:.2f} PLS exceeds max {BEAT_MAX_GAS_PLS/1e18:.1f} PLS"
            )

        # Beat profit = 0 until WORLD contract deploys
        # Return gas as "profit" so scheduler doesn't skip it entirely
        # The bot.py orchestrator treats beat specially — runs when all other engines idle
        return 0, gas_cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """Execute CHEON.Su() (optional) → META.Beat()."""
        meta_c  = w3_submit.eth.contract(address=META,  abi=META_ABI)
        cheon_c = w3_submit.eth.contract(address=CHEON, abi=CHEON_ABI)

        tx_hashes = []
        gas_spent = 0

        try:
            # Optional: CHEON.Su() to prime YUE bars
            if self.with_cheon:
                r = send_tx(
                    cheon_c.functions.Su(GIBS_QING),
                    "CHEON.Su(GIBS_QING)",
                    dry_run=dry_run,
                )
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
                    log.info("Su() complete")

            # META.Beat(GIBS_QING_WAAT)
            r = send_tx(
                meta_c.functions.Beat(GIBS_QING_WAAT),
                "META.Beat(GIBS_QING_WAAT)",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
                log.info("Beat complete. Block: %d", r["blockNumber"])

            return EngineResult(
                success=True,
                profit_wei=0,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes="Beat: territory metrics updated",
            )

        except (SimulationFailed, AssertionError, Exception) as exc:
            log.error("BeatEngine execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )
