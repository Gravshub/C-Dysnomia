"""
lp_fees.py — LP fee accrual tracking for Joey's GIBS liquidity positions.

Motivation:
  The bot's per-cycle profit report counts only WPLS realized from sell legs
  and subtracts gas. It does NOT count fees passively earned by Joey's LP
  tokens when external actors (e.g., the chatAndClaim arb bot) route trades
  through Joey's pools. Analysis showed ~12 PLS of fees per external arb
  hit our pools, and those hits correlate tightly with E2 floor harvests.
  This module tracks that passive fee income.

Approach:
  Uniswap V2 fees are retained in pool reserves on every swap. A fixed LP
  share therefore sees its underlying (reserve0, reserve1) grow over time.
  The mint/burn-invariant indicator is:

      k_per_lp = sqrt(reserve0 * reserve1) / totalSupply

  This quantity is unchanged by addLiquidity/removeLiquidity (both sides
  and totalSupply grow proportionally) and monotonically increases as swaps
  pay fees into reserves. Baselining k_per_lp lets us measure fee growth
  across a period even when Joey is actively adding more LP via E2.

  For positions held continuously since baseline, fee growth ≈
      (k_per_lp_now / k_per_lp_baseline - 1) * position_value_baseline

  For LP added after baselining, we use the CURRENT lp_balance × fee growth
  as an upper bound, and MIN(baseline_lp, current_lp) × fee growth as a
  conservative lower bound. The true value is between these; we report both.

Scope of this module (MVP):
  - scan_joey_lp_positions() — read all known GIBS pairs via multicall
  - save_baseline() / load_baseline() — JSON persistence
  - compute_fee_accrual() — delta report vs baseline
  - format_report() — human-readable output for CLI

Not in scope here (handled by other modules):
  - Dashboard API route
  - Historical fee accrual curves (time-series)
  - Impermanent loss decomposition
  These consume the same scan_joey_lp_positions() function but extend it.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Module-level price cache with TTL. Prior versions used a mutable default
# argument which never expired — fine for a one-shot CLI run, stale for a
# long-running dashboard process.
_PRICE_CACHE: dict[str, tuple[float, float]] = {}  # token_addr_lc -> (pls_price, ts)
_PRICE_CACHE_TTL_SEC = 300

from web3 import Web3

from ..core.chain import erc20, multicall, pair_contract, safe, w3_read
from ..core.config import (
    GIBS_LAU,
    JOEY_WALLET,
    WPLS,
)
from ..core.log_names import get_logger

log = get_logger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
BASELINE_PATH = os.path.join(_DATA_DIR, "lp_baselines.json")
HISTORY_PATH = os.path.join(_DATA_DIR, "lp_fee_history.json")
PAIR_REGISTRY_PATH = os.path.join(_DATA_DIR, "pair_registry.json")


# ─── Data structures ─────────────────────────────────────────────────────────
@dataclass
class LPPosition:
    """One scanned LP position owned by Joey."""
    pair_addr: str
    symbol_a: str
    symbol_b: str
    token_a: str
    token_b: str
    factory: str                  # "V1" / "V2"
    lp_balance: int               # wei
    total_supply: int             # wei
    reserve_a: int                # wei (token_a reserve)
    reserve_b: int                # wei (token_b reserve)
    pooled_a: int                 # wei owned by Joey
    pooled_b: int                 # wei owned by Joey
    k_per_lp: float               # sqrt(r_a*r_b)/total_supply, as float
    share_pct: float              # Joey's % ownership of pool
    value_pls: float              # total position value in PLS at current prices
    price_a_pls: float            # token_a PLS price at scan time (0 if unknown)
    price_b_pls: float            # token_b PLS price at scan time (0 if unknown)
    snapshot_block: int
    snapshot_ts: str


@dataclass
class FeeDelta:
    """Fee accrual delta for one pair between baseline and current scan."""
    pair_addr: str
    label: str                    # e.g. "GIBS/WPLS"
    # k_per_lp growth (the fee-only signal, mint/burn invariant)
    k_growth_pct: float
    # PLS estimates
    fees_earned_pls_low: float    # lower bound (min lp balance × growth)
    fees_earned_pls_high: float   # upper bound (current lp balance × growth)
    # Position composition delta
    lp_delta: int                 # lp_wei delta (positive = added, negative = removed)
    value_delta_pls: float        # current value - baseline value at current prices
    # Impermanent loss hint: if value_delta - fees_earned differs from token-price-driven change
    # we'd isolate IL here. MVP leaves this as 0; handled in follow-up.
    il_pls: float = 0.0
    # Raw snapshots for debug
    baseline_k_per_lp: float = 0.0
    current_k_per_lp: float = 0.0
    baseline_lp_balance: int = 0
    current_lp_balance: int = 0
    baseline_block: int = 0
    current_block: int = 0
    baseline_ts: str = ""
    current_ts: str = ""


@dataclass
class FeeReport:
    """Aggregate report across all tracked pairs."""
    total_k_growth_pls_low: float
    total_k_growth_pls_high: float
    total_value_delta_pls: float
    per_pair: list[FeeDelta] = field(default_factory=list)
    baseline_ts: str = ""
    current_ts: str = ""
    blocks_elapsed: int = 0


# ─── Registry loading ────────────────────────────────────────────────────────
def load_gibs_pairs_from_registry() -> list[dict]:
    """
    Load all known GIBS pairs from the pair registry.
    Returns a list of dicts: {pair_address, token_a, token_b, symbol_a, symbol_b, factory}.
    """
    if not os.path.exists(PAIR_REGISTRY_PATH):
        log.warning("Pair registry not found at %s", PAIR_REGISTRY_PATH)
        return []

    with open(PAIR_REGISTRY_PATH) as f:
        reg = json.load(f)

    pairs = reg.get("pairs", {})
    gibs_addr = GIBS_LAU.lower()
    results = []
    for addr, entry in pairs.items():
        t_a = (entry.get("token_a", "") or "").lower()
        t_b = (entry.get("token_b", "") or "").lower()
        if gibs_addr not in (t_a, t_b):
            continue
        results.append({
            "pair_address": addr,
            "token_a": entry["token_a"],
            "token_b": entry["token_b"],
            "symbol_a": entry.get("symbol_a", "?"),
            "symbol_b": entry.get("symbol_b", "?"),
            "factory": entry.get("factory", "?"),
        })
    return results


def add_extra_pair(pairs: list[dict], pair_address: str, token_a: str, token_b: str,
                   symbol_a: str, symbol_b: str, factory: str = "V2") -> list[dict]:
    """Ensure a pair is in the list, append if missing. Used for manual additions
    when the registry is stale (e.g., newly-created pairs like GIBS/PRVX)."""
    if any(p["pair_address"].lower() == pair_address.lower() for p in pairs):
        return pairs
    pairs.append({
        "pair_address": pair_address,
        "token_a": token_a,
        "token_b": token_b,
        "symbol_a": symbol_a,
        "symbol_b": symbol_b,
        "factory": factory,
    })
    return pairs


# ─── Scanner ─────────────────────────────────────────────────────────────────
def _get_token_pls_price(token_addr: str) -> float:
    """
    Resolve a token's PLS price via direct /WPLS pair (V1 or V2) if available.
    Returns 0.0 if no route is found. Cached at module level with TTL so
    long-running processes (dashboard) refresh stale quotes.
    """
    if token_addr.lower() == WPLS.lower():
        return 1.0
    key = token_addr.lower()
    now = time.time()
    cached = _PRICE_CACHE.get(key)
    if cached is not None and (now - cached[1]) < _PRICE_CACHE_TTL_SEC:
        return cached[0]
    from ..oracle.price import get_amounts_out, get_amounts_out_v2
    try:
        one = 10 ** 18
        best = 0
        v1 = get_amounts_out(one, [Web3.to_checksum_address(token_addr),
                                    Web3.to_checksum_address(WPLS)])
        if v1 and v1[-1] > best:
            best = v1[-1]
        v2 = get_amounts_out_v2(one, [Web3.to_checksum_address(token_addr),
                                       Web3.to_checksum_address(WPLS)])
        if v2 and v2[-1] > best:
            best = v2[-1]
        price = best / 1e18
    except Exception as exc:
        log.debug("Price lookup failed for %s: %s", token_addr[:10], exc)
        price = 0.0
    _PRICE_CACHE[key] = (price, now)
    return price


def scan_joey_lp_positions(extra_pairs: Optional[list[dict]] = None) -> list[LPPosition]:
    """
    Scan all known GIBS LP pairs and return Joey's current positions.

    Batches balanceOf/totalSupply/getReserves via multicall3 for speed.
    Skips pairs where Joey has zero LP balance.

    Args:
        extra_pairs: optional additional pair specs to scan beyond what the
                     registry knows about. Used to inject GIBS/PRVX etc.
                     before the registry is refreshed.
    """
    pairs = load_gibs_pairs_from_registry()
    if extra_pairs:
        for ep in extra_pairs:
            pairs = add_extra_pair(
                pairs,
                ep["pair_address"], ep["token_a"], ep["token_b"],
                ep.get("symbol_a", "?"), ep.get("symbol_b", "?"),
                ep.get("factory", "V2"),
            )

    if not pairs:
        log.warning("No GIBS pairs found to scan")
        return []

    # Build multicall batch: for each pair, we need
    #   lp_balance = pair.balanceOf(JOEY)      (via ERC20 ABI — pair IS an LP token)
    #   total_supply = pair.totalSupply()      (via ERC20 ABI)
    #   reserves = pair.getReserves()          (via PAIR ABI)
    #   token0 = pair.token0()                 (via PAIR ABI)
    calls = []
    for p in pairs:
        pc_pair = pair_contract(p["pair_address"])   # getReserves, token0
        pc_erc  = erc20(p["pair_address"])           # balanceOf, totalSupply
        calls.append((pc_erc, "balanceOf", [JOEY_WALLET]))
        calls.append((pc_erc, "totalSupply", []))
        calls.append((pc_pair, "getReserves", []))
        calls.append((pc_pair, "token0", []))

    # Capture block BEFORE the multicall so the recorded snapshot_block is a
    # lower bound on when the reserves were valid. Reading it after leaves a
    # race where reserves could be from an earlier block than the recorded one.
    block = w3_read.eth.block_number
    ts = datetime.now(timezone.utc).isoformat()
    results = multicall(calls)
    positions: list[LPPosition] = []

    for i, p in enumerate(pairs):
        lp_bal = results[i * 4 + 0]
        total_supply = results[i * 4 + 1]
        reserves = results[i * 4 + 2]
        token0 = results[i * 4 + 3]

        if lp_bal is None or total_supply is None or reserves is None or token0 is None:
            log.debug("Pair %s: one or more reads failed — skipping",
                      p["pair_address"][:12])
            continue
        if lp_bal == 0 or total_supply == 0:
            continue

        r0, r1 = int(reserves[0]), int(reserves[1])
        # Normalize so that reserve_a corresponds to token_a in registry
        if token0.lower() == p["token_a"].lower():
            reserve_a, reserve_b = r0, r1
        else:
            reserve_a, reserve_b = r1, r0

        pooled_a = int(reserve_a) * int(lp_bal) // int(total_supply)
        pooled_b = int(reserve_b) * int(lp_bal) // int(total_supply)
        k_per_lp = math.sqrt(float(reserve_a) * float(reserve_b)) / float(total_supply)
        share_pct = (int(lp_bal) / int(total_supply)) * 100.0

        price_a = _get_token_pls_price(p["token_a"])
        price_b = _get_token_pls_price(p["token_b"])
        value_pls = (pooled_a / 1e18) * price_a + (pooled_b / 1e18) * price_b

        positions.append(LPPosition(
            pair_addr=p["pair_address"],
            symbol_a=p["symbol_a"],
            symbol_b=p["symbol_b"],
            token_a=p["token_a"],
            token_b=p["token_b"],
            factory=p["factory"],
            lp_balance=int(lp_bal),
            total_supply=int(total_supply),
            reserve_a=reserve_a,
            reserve_b=reserve_b,
            pooled_a=pooled_a,
            pooled_b=pooled_b,
            k_per_lp=k_per_lp,
            share_pct=share_pct,
            value_pls=value_pls,
            price_a_pls=price_a,
            price_b_pls=price_b,
            snapshot_block=block,
            snapshot_ts=ts,
        ))

    return positions


# ─── Baseline persistence ────────────────────────────────────────────────────
def _atomic_write_json(path: str, data: dict) -> None:
    """
    Atomic write via tempfile + rename. tempfile.mkstemp creates files
    with mode 600 regardless of umask — fine for one-user processes but
    breaks cross-user reads (e.g. bot writes as joey, dashboard reads as
    joystick). chmod to 0o664 before rename so the group can read/write.
    The parent dir should have setgid + joystick group so the new file
    inherits the right group.
    """
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_baseline(positions: list[LPPosition], path: str = BASELINE_PATH) -> None:
    """Serialize positions as the baseline snapshot."""
    baselines = {}
    for p in positions:
        baselines[p.pair_addr.lower()] = {
            "symbol_a": p.symbol_a,
            "symbol_b": p.symbol_b,
            "token_a": p.token_a,
            "token_b": p.token_b,
            "factory": p.factory,
            "lp_balance": str(p.lp_balance),
            "total_supply": str(p.total_supply),
            "reserve_a": str(p.reserve_a),
            "reserve_b": str(p.reserve_b),
            "pooled_a": str(p.pooled_a),
            "pooled_b": str(p.pooled_b),
            "k_per_lp": p.k_per_lp,
            "share_pct": p.share_pct,
            "value_pls": p.value_pls,
            "price_a_pls": p.price_a_pls,
            "price_b_pls": p.price_b_pls,
            "snapshot_block": p.snapshot_block,
            "snapshot_ts": p.snapshot_ts,
        }
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baselines": baselines,
    }
    _atomic_write_json(path, payload)
    log.info("Baseline saved: %d pairs → %s", len(baselines), path)


def load_baseline(path: str = BASELINE_PATH) -> dict | None:
    """Return the baselines dict keyed by lowercase pair address, or None."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        payload = json.load(f)
    return payload


# ─── Fee accrual computation ─────────────────────────────────────────────────
def compute_fee_accrual(baseline: dict, current: list[LPPosition]) -> FeeReport:
    """
    Compare current scan vs baseline and compute per-pair fee accrual.

    Math derivation:
      k_per_lp = sqrt(R_a × R_b) / total_supply is monotonic in swap fees and
      invariant under LP mint/burn. For a two-asset pool at price equilibrium
      (R_a × p_a ≈ R_b × p_b), the per-LP position value in PLS is:
          V / lp_bal = 2 × sqrt(p_a × p_b) × k_per_lp

      For a fixed lp_bal held across the interval, with ~stable prices:
          V_now / V_baseline = k_per_lp_now / k_per_lp_baseline
          fees_earned ≈ V_baseline × (k_per_lp_now / k_per_lp_baseline - 1)

      We define growth_ratio = k_per_lp_now / k_per_lp_baseline - 1, then:
          fees_low  = baseline_value × growth_ratio   (conservative: baseline
                      LP amount earned fees for the full interval; newly-added
                      LP earned less, so this undercounts slightly)
          fees_high = current_value × growth_ratio    (optimistic: all current
                      LP held since baseline, overcounts slightly if LP was
                      added mid-interval)

      True fees live between these bounds. The interval between them narrows
      as lp_Δ approaches zero.

      Prior versions had a spurious `× 2` factor — the 2 is already absorbed
      in V_baseline (from both-sides-of-pool summation); multiplying again
      double-counted.
    """
    if not baseline or "baselines" not in baseline:
        return FeeReport(0, 0, 0)

    bl_dict = baseline["baselines"]
    per_pair: list[FeeDelta] = []
    total_low = 0.0
    total_high = 0.0
    total_value_delta = 0.0
    baseline_ts = ""
    current_ts = ""
    min_bl_block = None
    max_cur_block = None

    for pos in current:
        key = pos.pair_addr.lower()
        bl = bl_dict.get(key)
        if not bl:
            continue  # new pair since baseline — no comparison possible

        bl_k = float(bl["k_per_lp"])
        bl_lp = int(bl["lp_balance"])
        bl_block = int(bl.get("snapshot_block", 0))
        bl_ts = bl.get("snapshot_ts", "")
        bl_value = float(bl.get("value_pls", 0))

        growth_ratio = (pos.k_per_lp / bl_k - 1.0) if bl_k > 0 else 0.0
        growth_pct = growth_ratio * 100.0

        # See compute_fee_accrual docstring for the derivation of these bounds.
        fees_low = bl_value * growth_ratio        # baseline LP × growth (conservative)
        fees_high = pos.value_pls * growth_ratio  # current LP × growth (optimistic)

        value_delta = pos.value_pls - bl_value
        label = f"{pos.symbol_a}/{pos.symbol_b}"

        per_pair.append(FeeDelta(
            pair_addr=pos.pair_addr,
            label=label,
            k_growth_pct=growth_pct,
            fees_earned_pls_low=fees_low,
            fees_earned_pls_high=fees_high,
            lp_delta=pos.lp_balance - bl_lp,
            value_delta_pls=value_delta,
            il_pls=0.0,  # not computed in MVP
            baseline_k_per_lp=bl_k,
            current_k_per_lp=pos.k_per_lp,
            baseline_lp_balance=bl_lp,
            current_lp_balance=pos.lp_balance,
            baseline_block=bl_block,
            current_block=pos.snapshot_block,
            baseline_ts=bl_ts,
            current_ts=pos.snapshot_ts,
        ))
        total_low += fees_low
        total_high += fees_high
        total_value_delta += value_delta
        baseline_ts = bl_ts or baseline_ts
        current_ts = pos.snapshot_ts or current_ts
        if min_bl_block is None or bl_block < min_bl_block:
            min_bl_block = bl_block
        if max_cur_block is None or pos.snapshot_block > max_cur_block:
            max_cur_block = pos.snapshot_block

    blocks_elapsed = (max_cur_block - min_bl_block) if (min_bl_block and max_cur_block) else 0
    return FeeReport(
        total_k_growth_pls_low=total_low,
        total_k_growth_pls_high=total_high,
        total_value_delta_pls=total_value_delta,
        per_pair=sorted(per_pair, key=lambda d: d.fees_earned_pls_high, reverse=True),
        baseline_ts=baseline_ts,
        current_ts=current_ts,
        blocks_elapsed=blocks_elapsed,
    )


# ─── Reporting ───────────────────────────────────────────────────────────────
def format_report(report: FeeReport, current_positions: list[LPPosition]) -> str:
    """Human-readable text output for CLI."""
    lines = []
    lines.append("═" * 88)
    lines.append("  LP FEE ACCRUAL REPORT")
    lines.append("═" * 88)
    lines.append(f"  Baseline:  {report.baseline_ts}")
    lines.append(f"  Current:   {report.current_ts}")
    lines.append(f"  Elapsed:   {report.blocks_elapsed:,} blocks")
    lines.append("")

    if not report.per_pair:
        lines.append("  (no pairs compared — baseline missing or no current positions)")
        lines.append("═" * 88)
        return "\n".join(lines)

    lines.append(f"  {'Pair':<18} {'k-growth':>10} {'fees_low':>12} {'fees_high':>12} "
                 f"{'Δvalue':>12} {'lp_Δ%':>8}")
    lines.append(f"  {'-'*18} {'-'*10} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
    for d in report.per_pair:
        lp_delta_pct = 0.0
        if d.baseline_lp_balance > 0:
            lp_delta_pct = (d.lp_delta / d.baseline_lp_balance) * 100
        lines.append(
            f"  {d.label:<18} "
            f"{d.k_growth_pct:>9.4f}% "
            f"{d.fees_earned_pls_low:>11,.2f} "
            f"{d.fees_earned_pls_high:>11,.2f} "
            f"{d.value_delta_pls:>+11,.2f} "
            f"{lp_delta_pct:>+7.2f}%"
        )
    lines.append(f"  {'-'*18} {'-'*10} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
    lines.append(
        f"  {'TOTAL':<18} "
        f"{'':>10} "
        f"{report.total_k_growth_pls_low:>11,.2f} "
        f"{report.total_k_growth_pls_high:>11,.2f} "
        f"{report.total_value_delta_pls:>+11,.2f}"
    )
    lines.append("")
    lines.append("  Notes:")
    lines.append("    • fees_low  = conservative (only baseline LP balance × k-growth)")
    lines.append("    • fees_high = optimistic  (current LP balance × k-growth)")
    lines.append("    • Δvalue    = (current position value) - (baseline value) at current prices")
    lines.append("                  Includes fees + impermanent loss / price movement.")
    lines.append("    • lp_Δ%     = LP token balance change (positive = accumulated more)")
    lines.append("═" * 88)
    return "\n".join(lines)


def format_positions_table(positions: list[LPPosition]) -> str:
    """Dump current positions as a table — used when no baseline exists yet."""
    lines = []
    lines.append("═" * 96)
    lines.append("  CURRENT GIBS LP POSITIONS (no baseline — snapshot only)")
    lines.append("═" * 96)
    lines.append(f"  {'Pair':<18} {'Factory':>7} {'Share':>8} "
                 f"{'pooled_a':>14} {'pooled_b':>14} {'value (PLS)':>14}")
    lines.append(f"  {'-'*18} {'-'*7} {'-'*8} {'-'*14} {'-'*14} {'-'*14}")
    total_value = 0.0
    for p in sorted(positions, key=lambda x: x.value_pls, reverse=True):
        lines.append(
            f"  {p.symbol_a + '/' + p.symbol_b:<18} "
            f"{p.factory:>7} "
            f"{p.share_pct:>7.2f}% "
            f"{p.pooled_a / 1e18:>14,.2f} "
            f"{p.pooled_b / 1e18:>14,.2f} "
            f"{p.value_pls:>14,.2f}"
        )
        total_value += p.value_pls
    lines.append(f"  {'-'*18} {'-'*7} {'-'*8} {'-'*14} {'-'*14} {'-'*14}")
    lines.append(f"  {'TOTAL':<18} {'':>7} {'':>8} {'':>14} {'':>14} {total_value:>14,.2f}")
    lines.append("═" * 96)
    return "\n".join(lines)
