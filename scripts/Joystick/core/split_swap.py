"""
split_swap.py — Intelligent swap splitting based on pool impact.

Used by ALL engines (E1, E2, E6, E7, E8) to manage DEX price impact.
Splits large swaps across multiple pairs and/or blocks when impact
would exceed thresholds.

Rules:
  - MAX_IMPACT_PCT = 10.0 (never exceed 10% of pool reserves)
  - SPLIT_THRESHOLD = 3.33% (split if single-swap impact exceeds this)

Strategy:
  1. Single pair, impact < threshold → 1 swap, immediate
  2. Single pair, impact > threshold → N chunks, delay_blocks=1 between each
     CRITICAL: same-pool same-block splits give ZERO benefit.
     Sequential swaps in one block still move the AMM curve identically.
     Splitting only helps across DIFFERENT blocks (price can recover between).
  3. Multiple pairs available → distribute across pairs weighted by liquidity
     This DOES help in same block (independent AMM curves).
  4. Multiple pairs + still high per-pool impact → distribute AND delay.
"""
import logging
import math
from dataclasses import dataclass, field
from typing import Sequence

from ..oracle.profitability import uniswap_v2_out, price_impact_pct

log = logging.getLogger(__name__)

MAX_IMPACT_PCT = 10.0
SPLIT_THRESHOLD_PCT = 3.33


@dataclass
class SwapChunk:
    """One atomic swap operation within a SwapPlan."""
    pair_addr: str
    token_in: str
    token_out: str
    reserve_in: int
    reserve_out: int
    sub_amount: int
    expected_out: int
    impact_pct: float
    delay_blocks: int = 0       # 0 = execute immediately, 1+ = wait N blocks
    dex: int = 2                # 0=V1, 1=V2, 2=best


@dataclass
class SwapPlan:
    """Complete swap plan: ordered list of chunks."""
    chunks: list[SwapChunk] = field(default_factory=list)
    total_in: int = 0
    total_expected_out: int = 0
    max_impact_pct: float = 0.0
    needs_multi_block: bool = False

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def summary(self) -> str:
        if not self.chunks:
            return "SwapPlan: empty"
        pairs = len(set(c.pair_addr for c in self.chunks))
        blocks = max((c.delay_blocks for c in self.chunks), default=0) + 1
        return (
            f"SwapPlan: {self.chunk_count} chunks across {pairs} pair(s), "
            f"{blocks} block(s), total_in={self.total_in/1e18:.4f}, "
            f"expected_out={self.total_expected_out/1e18:.4f}, "
            f"max_impact={self.max_impact_pct:.2f}%"
        )


@dataclass
class PairInfo:
    """Pool data for swap planning."""
    pair_addr: str
    token_in: str
    token_out: str
    reserve_in: int
    reserve_out: int
    dex: int = 2    # 0=V1, 1=V2, 2=best


class SplitSwap:
    """
    Intelligent swap splitting based on pool impact.

    Usage:
        splitter = SplitSwap()
        plan = splitter.plan(amount_in, pairs)
        # Execute plan.chunks in order, respecting delay_blocks
    """

    def __init__(
        self,
        max_impact_pct: float = MAX_IMPACT_PCT,
        split_threshold_pct: float = SPLIT_THRESHOLD_PCT,
    ):
        self.max_impact_pct = max_impact_pct
        self.split_threshold_pct = split_threshold_pct

    def plan(
        self,
        amount_in: int,
        pairs: Sequence[PairInfo],
    ) -> SwapPlan:
        """
        Build a SwapPlan for the given amount across available pairs.

        Args:
            amount_in: Total input amount in wei
            pairs: Available pools (must have reserves populated)

        Returns:
            SwapPlan with ordered chunks
        """
        if amount_in <= 0 or not pairs:
            return SwapPlan()

        # Filter out zero-reserve pairs
        valid = [p for p in pairs if p.reserve_in > 0 and p.reserve_out > 0]
        if not valid:
            return SwapPlan()

        # Cap total input at max_impact across all pairs combined
        total_reserve_in = sum(p.reserve_in for p in valid)
        abs_max = int(total_reserve_in * self.max_impact_pct / 100.0)
        capped_amount = min(amount_in, abs_max)

        if capped_amount <= 0:
            log.warning("SplitSwap: amount exceeds all pool reserves — capped to 0")
            return SwapPlan()

        if len(valid) == 1:
            return self._plan_single_pair(capped_amount, valid[0])

        return self._plan_multi_pair(capped_amount, valid)

    def _plan_single_pair(self, amount: int, pair: PairInfo) -> SwapPlan:
        """Plan for single-pair scenario."""
        impact = price_impact_pct(amount, pair.reserve_in)

        if impact <= self.split_threshold_pct:
            # Single swap, no delay
            expected_out = uniswap_v2_out(amount, pair.reserve_in, pair.reserve_out)
            chunk = SwapChunk(
                pair_addr=pair.pair_addr,
                token_in=pair.token_in,
                token_out=pair.token_out,
                reserve_in=pair.reserve_in,
                reserve_out=pair.reserve_out,
                sub_amount=amount,
                expected_out=expected_out,
                impact_pct=impact,
                delay_blocks=0,
                dex=pair.dex,
            )
            return SwapPlan(
                chunks=[chunk],
                total_in=amount,
                total_expected_out=expected_out,
                max_impact_pct=impact,
                needs_multi_block=False,
            )

        # Split across blocks — each chunk targets split_threshold impact
        chunk_size = int(pair.reserve_in * self.split_threshold_pct / 100.0)
        if chunk_size <= 0:
            chunk_size = amount

        n_chunks = math.ceil(amount / chunk_size)
        n_chunks = min(n_chunks, 10)  # Cap at 10 blocks max
        chunk_size = amount // n_chunks
        remainder = amount - chunk_size * n_chunks

        chunks = []
        # Simulate sequentially — each chunk moves the AMM curve
        sim_r_in = pair.reserve_in
        sim_r_out = pair.reserve_out
        total_out = 0

        for i in range(n_chunks):
            sub = chunk_size + (remainder if i == n_chunks - 1 else 0)
            impact_i = price_impact_pct(sub, sim_r_in)
            out_i = uniswap_v2_out(sub, sim_r_in, sim_r_out)

            chunks.append(SwapChunk(
                pair_addr=pair.pair_addr,
                token_in=pair.token_in,
                token_out=pair.token_out,
                reserve_in=sim_r_in,
                reserve_out=sim_r_out,
                sub_amount=sub,
                expected_out=out_i,
                impact_pct=impact_i,
                delay_blocks=i,  # 0 for first, 1 for second, etc.
                dex=pair.dex,
            ))

            # Update simulated reserves
            sim_r_in += sub
            sim_r_out -= out_i
            total_out += out_i

        max_imp = max(c.impact_pct for c in chunks) if chunks else 0

        return SwapPlan(
            chunks=chunks,
            total_in=amount,
            total_expected_out=total_out,
            max_impact_pct=max_imp,
            needs_multi_block=len(chunks) > 1,
        )

    def _plan_multi_pair(self, amount: int, pairs: list[PairInfo]) -> SwapPlan:
        """Distribute across multiple pairs weighted by reserve liquidity."""
        total_reserve = sum(p.reserve_in for p in pairs)

        # Distribute proportional to each pair's share of total reserves
        allocations = []
        allocated = 0
        for i, pair in enumerate(pairs):
            if i == len(pairs) - 1:
                # Last pair gets remainder to avoid rounding loss
                alloc = amount - allocated
            else:
                alloc = int(amount * pair.reserve_in / total_reserve)
            allocated += alloc
            allocations.append((pair, alloc))

        chunks = []
        total_out = 0
        any_needs_delay = False

        for pair, alloc in allocations:
            if alloc <= 0:
                continue

            impact = price_impact_pct(alloc, pair.reserve_in)

            # If per-pool impact still exceeds threshold, sub-split across blocks
            if impact > self.split_threshold_pct:
                sub_plan = self._plan_single_pair(alloc, pair)
                for chunk in sub_plan.chunks:
                    chunks.append(chunk)
                    total_out += chunk.expected_out
                if sub_plan.needs_multi_block:
                    any_needs_delay = True
            else:
                out = uniswap_v2_out(alloc, pair.reserve_in, pair.reserve_out)
                chunks.append(SwapChunk(
                    pair_addr=pair.pair_addr,
                    token_in=pair.token_in,
                    token_out=pair.token_out,
                    reserve_in=pair.reserve_in,
                    reserve_out=pair.reserve_out,
                    sub_amount=alloc,
                    expected_out=out,
                    impact_pct=impact,
                    delay_blocks=0,
                    dex=pair.dex,
                ))
                total_out += out

        max_imp = max((c.impact_pct for c in chunks), default=0.0)

        return SwapPlan(
            chunks=chunks,
            total_in=amount,
            total_expected_out=total_out,
            max_impact_pct=max_imp,
            needs_multi_block=any_needs_delay,
        )
