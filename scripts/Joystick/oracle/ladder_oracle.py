"""
ladder_oracle.py — Pure-read oracle for LADDER mode in E2 CEREAL.

Reads live reserves from GIBS/WPLS V2 and multiple reference pairs
(GIBS/FED, GIBS/AFF), computes the best price gap, and recommends
displacement parameters. No TXs, no side effects.
Called from DSSEngine.simulate().
"""
from dataclasses import dataclass

from ..core.log_names import get_logger
from ..core.config import (
    GIBS_LAU, WPLS, FED, AFFECTION, GIBS_WPLS_V2_PAIR,
    PULSEX_V2_FACTORY, HARVEST_MINT_COUNT,
)
from ..core.chain import pair_contract, safe

log = get_logger(__name__)

# ── Constants (tunable after live calibration) ────────────────────────────
ARB_MIN_PROFIT_PLS = 300      # conservative — real bots may fire at less
BREAK_EVEN_GIBS_PLS = 21.5    # E2 DSS profitability floor
LADDER_CEILING_PLS = 43.0     # 2x break-even — above this, HARVEST wins

# Gap-based gating.  When any reference pair shows a gap > LADDER_GAP_MIN_PCT,
# LADDER fires.  The old realizable-arb model (TVL × gap² × k) was too
# conservative for thin pools — it prevented LADDER from ever running on
# GIBS/AFF (~30K TVL).  Gap-based gating lets the ladder create displacement
# that arb bots correct, building ascending LP floors at each price level.
LADDER_GAP_MIN_PCT = 2.0       # minimum gap % for LADDER to fire
LADDER_LITE_GAP_PCT = 5.0      # gap % threshold for LADDER_LITE (lighter touch)

# Known pair addresses
GIBS_FED_V2_PAIR = "0xA2a7a2153136b6ee075335b979fb6ac033412e4d"
GIBS_AFF_V2_PAIR = "0x1E2fAeF811b8eA8dC5E0dEEe2c3b0E355A7d7EA0"


@dataclass
class LadderSignal:
    should_ladder: bool
    mode: str                    # "BELOW_BREAKEVEN" | "HARVEST_ONLY" | "LADDER" | "LADDER_LITE" | "NO_DATA"
    gibs_price_pls: float        # current GIBS price in PLS (from WPLS pair)
    gap_pct: float               # % price spread between WPLS pair and FED pair
    arb_threshold_pct: float     # minimum gap needed for arb bots to fire
    displacement_gibs: float     # recommended GIBS sell amount
    mint_count: int              # recommended mintCount for Hub calls
    lp_bps: int                  # recommended lpBps (basis points to LP first)
    burn_bps: int                # recommended burnBps (basis points of LP to burn)
    tvl_pls: float               # total TVL of reference pair in PLS
    notes: str                   # human-readable explanation of decision


def _get_pair_reserves_normalized(pair_addr: str, token_a: str) -> tuple[int, int] | None:
    """
    Read reserves from a V2 pair and return (reserve_token_a, reserve_other).
    Returns None on failure.
    """
    from web3 import Web3
    pc = pair_contract(Web3.to_checksum_address(pair_addr))
    reserves = safe(pc, "getReserves")
    if not reserves:
        return None
    token0 = safe(pc, "token0")
    if not token0:
        return None
    r0, r1 = reserves[0], reserves[1]
    if token0.lower() == token_a.lower():
        return r0, r1
    return r1, r0


def _get_token_pls_price(token: str) -> float | None:
    """
    Get token price in PLS via DEX router (V2 then V1 fallback).
    Returns PLS-per-token (float), or None on failure.
    """
    from web3 import Web3
    from ..oracle.price import get_amounts_out_v2, get_amounts_out

    token_cs = Web3.to_checksum_address(token)
    wpls_cs = Web3.to_checksum_address(WPLS)

    result = get_amounts_out_v2(10**18, [token_cs, wpls_cs])
    if result and result[-1] > 0:
        return result[-1] / 1e18

    result = get_amounts_out(10**18, [token_cs, wpls_cs])
    if result and result[-1] > 0:
        return result[-1] / 1e18

    return None


def _compute_ref_pair_gap(
    pair_addr: str,
    other_token: str,
    gibs_price_pls: float,
) -> tuple[float, int, float]:
    """
    Compute gap between GIBS/WPLS price and a reference pair's implied price.
    Returns (gap_pct, gibs_reserve_wei, realizable_pls).
    """
    gp = _get_pair_reserves_normalized(pair_addr, GIBS_LAU)
    if not gp or gp[0] == 0:
        return 0.0, 0, 0.0

    gibs_r_ref, other_r = gp
    other_pls = _get_token_pls_price(other_token)
    if not other_pls or other_pls <= 0:
        return 0.0, 0, 0.0

    implied_pls = (other_r / gibs_r_ref) * other_pls
    gap = abs(gibs_price_pls - implied_pls) / gibs_price_pls * 100

    # Realizable profit: thin_tvl × gap² × k
    thin_tvl = (gibs_r_ref / 1e18) * gibs_price_pls
    realizable = thin_tvl * ((gap / 100) ** 2) * 0.1 if gap > 0 else 0.0

    return gap, gibs_r_ref, realizable


def get_ladder_signal() -> LadderSignal:
    """
    Read live reserves from GIBS/WPLS and reference pairs (FED, AFF).
    Use the best (largest realizable) gap to drive displacement recommendation.
    """
    # ── Read GIBS/WPLS reserves ──
    gwp = _get_pair_reserves_normalized(GIBS_WPLS_V2_PAIR, GIBS_LAU)
    if not gwp or gwp[0] == 0:
        return LadderSignal(
            should_ladder=False, mode="NO_DATA", gibs_price_pls=0,
            gap_pct=0, arb_threshold_pct=0, displacement_gibs=0,
            mint_count=0, lp_bps=3000, burn_bps=0, tvl_pls=0,
            notes="Failed to read GIBS/WPLS reserves",
        )

    gibs_r, wpls_r = gwp
    gibs_price_pls = wpls_r / gibs_r  # PLS per GIBS (in wei-ratio)
    tvl_pls = (wpls_r * 2) / 1e18     # total TVL ≈ 2× WPLS side

    # ── Scan reference pairs for best gap ──
    ref_pairs = [
        (GIBS_FED_V2_PAIR, FED, "FED"),
        (GIBS_AFF_V2_PAIR, AFFECTION, "AFF"),
    ]

    best_gap_pct = 0.0
    best_realizable = 0.0
    best_ref_name = "none"
    total_realizable = 0.0
    thin_gibs_wei_best = 0

    for pair_addr, other_token, ref_name in ref_pairs:
        gap, gibs_r_ref, realizable = _compute_ref_pair_gap(
            pair_addr, other_token, gibs_price_pls,
        )
        total_realizable += realizable
        if realizable > best_realizable:
            best_gap_pct = gap
            best_realizable = realizable
            best_ref_name = ref_name
            thin_gibs_wei_best = gibs_r_ref
        log.debug("LADDER oracle: %s gap=%.2f%% realizable=%.0f PLS",
                  ref_name, gap, realizable)

    gap_pct = best_gap_pct
    # Aggregate: arb bots can route through ANY reference pair,
    # so total realizable across all pairs is the combined opportunity.
    realizable_pls = total_realizable
    thin_side_tvl_pls = (thin_gibs_wei_best / 1e18) * gibs_price_pls

    log.info("LADDER oracle: best_ref=%s gap=%.2f%% realizable=%.0f PLS (total=%.0f)",
             best_ref_name, gap_pct, best_realizable, total_realizable)

    # Legacy threshold kept for telemetry/display only
    arb_threshold_pct = (ARB_MIN_PROFIT_PLS / tvl_pls) * 100 if tvl_pls > 0 else 999.0

    # ── Decision tree (gap-based gating) ──
    gibs_pls_human = gibs_price_pls  # already in PLS/GIBS (wei ratio)

    if gibs_pls_human < BREAK_EVEN_GIBS_PLS:
        return LadderSignal(
            should_ladder=False, mode="BELOW_BREAKEVEN",
            gibs_price_pls=gibs_pls_human, gap_pct=gap_pct,
            arb_threshold_pct=arb_threshold_pct, displacement_gibs=0,
            mint_count=0, lp_bps=3000, burn_bps=0, tvl_pls=tvl_pls,
            notes=f"GIBS {gibs_pls_human:.1f} PLS < break-even {BREAK_EVEN_GIBS_PLS}",
        )

    # Gap gate: need at least LADDER_GAP_MIN_PCT on any reference pair
    if gap_pct < LADDER_GAP_MIN_PCT:
        return LadderSignal(
            should_ladder=False, mode="HARVEST_ONLY",
            gibs_price_pls=gibs_pls_human, gap_pct=gap_pct,
            arb_threshold_pct=arb_threshold_pct, displacement_gibs=0,
            mint_count=0, lp_bps=3000, burn_bps=0, tvl_pls=tvl_pls,
            notes=(
                f"Best gap {gap_pct:.2f}% ({best_ref_name}) < min {LADDER_GAP_MIN_PCT}% "
                f"— no ladder"
            ),
        )

    # ── LADDER_LITE: gap is wide, light touch to nudge arb bots ──
    # 80% LP / 20% sell — maximize floor-building for ascending steps.
    if gap_pct >= LADDER_LITE_GAP_PCT:
        displacement_gibs = (ARB_MIN_PROFIT_PLS * 0.75) / gibs_pls_human
        lp_bps = 8000
        burn_bps = 0  # user policy: accumulate LP, do not burn
        mint_count = min(max(int(displacement_gibs / (1 - lp_bps / 10000) + 0.999), 1), HARVEST_MINT_COUNT)
        return LadderSignal(
            should_ladder=True, mode="LADDER_LITE",
            gibs_price_pls=gibs_pls_human, gap_pct=gap_pct,
            arb_threshold_pct=arb_threshold_pct,
            displacement_gibs=displacement_gibs,
            mint_count=mint_count, lp_bps=lp_bps, burn_bps=burn_bps,
            tvl_pls=tvl_pls,
            notes=(
                f"Gap {gap_pct:.2f}% ({best_ref_name}) ≥ {LADDER_LITE_GAP_PCT}% "
                f"— LITE nudge {displacement_gibs:.1f} GIBS, 80% LP"
            ),
        )

    # ── LADDER: gap above minimum — build floor + create displacement ──
    # 70% LP / 30% sell — build floor at each price level,
    # arb bots recover the small displacement → ascending steps.
    displacement_gibs = (ARB_MIN_PROFIT_PLS * 1.5) / gibs_pls_human
    lp_bps = 7000
    burn_bps = 0  # user policy: accumulate LP, do not burn
    mint_count = min(max(int(displacement_gibs / (1 - lp_bps / 10000) + 0.999), 1), HARVEST_MINT_COUNT)
    return LadderSignal(
        should_ladder=True, mode="LADDER",
        gibs_price_pls=gibs_pls_human, gap_pct=gap_pct,
        arb_threshold_pct=arb_threshold_pct,
        displacement_gibs=displacement_gibs,
        mint_count=mint_count, lp_bps=lp_bps, burn_bps=burn_bps,
        tvl_pls=tvl_pls,
        notes=(
            f"Gap {gap_pct:.2f}% ({best_ref_name}) ≥ {LADDER_GAP_MIN_PCT}% "
            f"— FULL ladder {displacement_gibs:.1f} GIBS, 70% LP"
        ),
    )
