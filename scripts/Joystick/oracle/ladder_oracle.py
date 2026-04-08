"""
ladder_oracle.py — Pure-read oracle for LADDER mode in E2 CEREAL.

Reads live reserves from GIBS/WPLS V2 and GIBS/FED V2 pairs,
computes price gap between them, and recommends displacement parameters.
No TXs, no side effects. Called from DSSEngine.simulate().
"""
from dataclasses import dataclass

from ..core.log_names import get_logger
from ..core.config import (
    GIBS_LAU, WPLS, FED, GIBS_WPLS_V2_PAIR,
    PULSEX_V2_FACTORY, HARVEST_MINT_COUNT,
)
from ..core.chain import pair_contract, safe

log = get_logger(__name__)

# ── Constants (tunable after live calibration) ────────────────────────────
ARB_MIN_PROFIT_PLS = 300      # conservative — real bots may fire at less
BREAK_EVEN_GIBS_PLS = 21.5    # E2 DSS profitability floor
LADDER_CEILING_PLS = 43.0     # 2x break-even — above this, HARVEST wins

# Realizable-arb model (replaces naïve `300 / TVL` threshold).
# An external arb bot won't engage unless the max realizable profit across
# our thinner pool exceeds their gas floor + minimum profit target.
# ~400 PLS is an empirical floor on PulseChain for a 3-hop atomic arb.
BOT_GAS_FLOOR_PLS = 400

# Known pair addresses
GIBS_FED_V2_PAIR = "0xA2a7a2153136b6ee075335b979fb6ac033412e4d"


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


def _get_fed_pls_price() -> float | None:
    """
    Get FED price in PLS by reading the FED/WPLS pair on V2.
    Falls back to V1 if V2 pair doesn't exist.
    Returns PLS-per-FED (float), or None on failure.
    """
    from web3 import Web3
    from ..oracle.price import get_amounts_out_v2, get_amounts_out

    # Try V2 first
    result = get_amounts_out_v2(10**18, [
        Web3.to_checksum_address(FED),
        Web3.to_checksum_address(WPLS),
    ])
    if result and result[-1] > 0:
        return result[-1] / 1e18

    # Fallback to V1
    result = get_amounts_out(10**18, [
        Web3.to_checksum_address(FED),
        Web3.to_checksum_address(WPLS),
    ])
    if result and result[-1] > 0:
        return result[-1] / 1e18

    return None


def get_ladder_signal() -> LadderSignal:
    """
    Read live reserves from GIBS/WPLS and GIBS/FED pairs.
    Compute price gap and return displacement recommendation.
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

    # ── Read GIBS/FED reserves + FED/PLS price ──
    gap_pct = 0.0
    gibs_r_fed = 0
    gfp = _get_pair_reserves_normalized(GIBS_FED_V2_PAIR, GIBS_LAU)
    fed_pls_price = _get_fed_pls_price()

    if gfp and gfp[0] > 0 and fed_pls_price and fed_pls_price > 0:
        gibs_r_fed, fed_r = gfp
        fed_implied_pls = (fed_r / gibs_r_fed) * fed_pls_price
        gap_pct = abs(gibs_price_pls - fed_implied_pls) / gibs_price_pls * 100
    else:
        log.warning("LADDER oracle: FED pair read failed, using gap=0")

    # ── Realizable-arb gate (replaces naïve arb_threshold_pct firing rule) ──
    # An external arb bot can only extract profit bounded by the thinner pool's
    # GIBS side. Without enough depth, a gap is structurally unclosable and
    # LADDER displacements just leak gas.
    thin_gibs_wei = min(gibs_r, gibs_r_fed) if gibs_r_fed > 0 else 0
    thin_side_tvl_pls = (thin_gibs_wei / 1e18) * gibs_price_pls
    # Empirical calibration: at thin_side_tvl ≈ 125K PLS and gap=5.75%, the
    # max realizable 3-hop arb profit is ~44 PLS (measured on-chain). Profit
    # scales ~linearly with thin-side TVL and ~quadratically with gap_pct for
    # small gaps. Collapse to:  realizable ≈ thin_tvl × gap^2 × k
    # where k ≈ 0.1 calibrates to (125000 × 0.0575^2 × 0.1) ≈ 41 PLS ✓
    realizable_pls = thin_side_tvl_pls * ((gap_pct / 100) ** 2) * 0.1 if gap_pct > 0 else 0

    # Legacy threshold kept for telemetry/display only — no longer gates firing
    arb_threshold_pct = (ARB_MIN_PROFIT_PLS / tvl_pls) * 100 if tvl_pls > 0 else 999.0

    # ── Decision tree ──
    gibs_pls_human = gibs_price_pls  # already in PLS/GIBS (wei ratio)

    if gibs_pls_human < BREAK_EVEN_GIBS_PLS:
        return LadderSignal(
            should_ladder=False, mode="BELOW_BREAKEVEN",
            gibs_price_pls=gibs_pls_human, gap_pct=gap_pct,
            arb_threshold_pct=arb_threshold_pct, displacement_gibs=0,
            mint_count=0, lp_bps=3000, burn_bps=0, tvl_pls=tvl_pls,
            notes=f"GIBS {gibs_pls_human:.1f} PLS < break-even {BREAK_EVEN_GIBS_PLS}",
        )

    # Depth gate: if no external arb bot could profit after gas, don't ladder.
    # This replaces the old `gap > (300/TVL)` trigger which fired on any gap.
    if realizable_pls < BOT_GAS_FLOOR_PLS:
        return LadderSignal(
            should_ladder=False, mode="HARVEST_ONLY",
            gibs_price_pls=gibs_pls_human, gap_pct=gap_pct,
            arb_threshold_pct=arb_threshold_pct, displacement_gibs=0,
            mint_count=0, lp_bps=3000, burn_bps=0, tvl_pls=tvl_pls,
            notes=(
                f"Realizable arb {realizable_pls:.0f} PLS < bot gas floor "
                f"{BOT_GAS_FLOOR_PLS} PLS (thin TVL {thin_side_tvl_pls:,.0f}, gap {gap_pct:.2f}%) "
                f"— no ladder"
            ),
        )

    if gibs_pls_human > LADDER_CEILING_PLS and realizable_pls < BOT_GAS_FLOOR_PLS * 2:
        return LadderSignal(
            should_ladder=False, mode="HARVEST_ONLY",
            gibs_price_pls=gibs_pls_human, gap_pct=gap_pct,
            arb_threshold_pct=arb_threshold_pct, displacement_gibs=0,
            mint_count=0, lp_bps=3000, burn_bps=0, tvl_pls=tvl_pls,
            notes=(
                f"GIBS {gibs_pls_human:.1f} > ceiling {LADDER_CEILING_PLS} and "
                f"realizable {realizable_pls:.0f} PLS < 2× gas floor — HARVEST richer"
            ),
        )

    # ── LADDER_LITE: depth sufficient, gap already hot, small nudge ──
    if realizable_pls >= BOT_GAS_FLOOR_PLS * 1.5:
        displacement_gibs = (ARB_MIN_PROFIT_PLS * 0.75) / gibs_pls_human
        lp_bps = 3000
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
                f"Realizable {realizable_pls:.0f} PLS ≥ 1.5× gas floor, "
                f"gap {gap_pct:.2f}% — LITE nudge {displacement_gibs:.1f} GIBS"
            ),
        )

    # ── LADDER: depth sufficient but gap flat — wake bots up ──
    displacement_gibs = (ARB_MIN_PROFIT_PLS * 1.5) / gibs_pls_human
    lp_bps = 3000
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
            f"Realizable {realizable_pls:.0f} PLS borderline "
            f"(gap {gap_pct:.2f}%) — FULL ladder {displacement_gibs:.1f} GIBS"
        ),
    )
