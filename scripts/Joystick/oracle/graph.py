"""
graph.py — Directed weighted graph cycle finder for cross-pair DEX arbitrage.

Given a PairGraph (from pair_discovery.py), finds profitable arbitrage cycles:
  - Triangles: A → B → C → A (3 hops, 3 × 0.3% = 0.9% fee drag)
  - Quads:     A → B → C → D → A (4 hops, 1.2% fee drag, stretch goal)

Uses Uniswap v2 constant-product formula with 0.3% fee per hop for exact
profit computation. No log-space approximation — we need exact wei amounts.

Algorithm:
  1. Start from hub tokens (WPLS, AFFECTION, FED)
  2. BFS out 2 hops to find all reachable tokens
  3. For each pair of neighbors (B, C) of the hub:
     - If B↔C edge exists: hub→B→C→hub is a candidate triangle
  4. Score each candidate with exact multi-hop swap math
  5. Binary search for optimal input amount per cycle
  6. Rank by net profit (profit - gas estimate)

The math:
  For pool with reserves (R_in, R_out) and 0.3% fee:
    amount_out = (amount_in × 997 × R_out) / (R_in × 1000 + amount_in × 997)

  A triangle is profitable if:
    output_of_3_hops(input) > input (after fees on each hop)
"""
import logging

from ..core.log_names import get_logger
import math
from dataclasses import dataclass, field

from web3 import Web3

from ..core.config import (
    WPLS, AFFECTION, HUB_TOKENS,
    GRAPH_ARB_MIN_PROFIT_PLS, GRAPH_ARB_MAX_IMPACT_PCT,
)
from .pair_discovery import PairGraph, PoolEdge
from .price import simulate_swap_exact

log = get_logger(__name__)

# Gas estimate for a 3-hop swap via router (approve + multicall route)
TRIANGLE_GAS_ESTIMATE = 500_000
QUAD_GAS_ESTIMATE = 650_000


@dataclass
class ArbCycle:
    path: list[str]                # [tokenA, tokenB, tokenC, tokenA]
    pools: list[PoolEdge]          # which pool for each hop
    direction: str = "forward"     # "forward" or "reverse"
    optimal_input: int = 0         # in wei of path[0]
    expected_output: int = 0       # in wei of path[0]
    expected_profit: int = 0       # output - input, in wei
    expected_profit_pls: int = 0   # profit denominated in PLS (wei)
    gas_estimate: int = 0          # estimated gas cost in PLS (wei)
    net_profit_pls: int = 0        # profit - gas, in PLS (wei)
    score: float = 0.0             # net_profit / gas (ROI)
    pool_impacts: list[float] = field(default_factory=list)

    @property
    def path_symbols(self) -> str:
        syms = []
        for pool in self.pools:
            syms.append(pool.symbol_a if pool.token_a.lower() == self.path[len(syms)].lower() else pool.symbol_b)
        syms.append(syms[0])  # Close the loop
        return " → ".join(syms)

    def summary(self) -> str:
        return (
            f"{self.path_symbols} | "
            f"in={self.optimal_input / 1e18:.4f} "
            f"out={self.expected_output / 1e18:.4f} "
            f"profit={self.net_profit_pls / 1e18:.2f} PLS "
            f"(score={self.score:.2f})"
        )


# ── Core swap simulation ────────────────────────────────────────────────────

def _simulate_multihop(input_amount: int, pools: list[PoolEdge], path: list[str]) -> int:
    """
    Simulate a multi-hop swap through the given pools.
    path has N+1 entries for N pools: [tokenA, tokenB, tokenC, ..., tokenA]
    Returns the final output amount in wei of path[-1] (same token as path[0]).
    """
    amount = input_amount
    for i, pool in enumerate(pools):
        token_in = path[i].lower()
        # Determine which reserve is in/out based on direction
        if pool.token_a.lower() == token_in:
            r_in, r_out = pool.reserve_a, pool.reserve_b
        else:
            r_in, r_out = pool.reserve_b, pool.reserve_a

        if r_in == 0 or r_out == 0:
            return 0

        amount = simulate_swap_exact(amount, r_in, r_out)
        if amount == 0:
            return 0

    return amount


def _compute_impacts(input_amount: int, pools: list[PoolEdge], path: list[str]) -> list[float]:
    """Compute price impact % for each hop."""
    impacts = []
    amount = input_amount
    for i, pool in enumerate(pools):
        token_in = path[i].lower()
        if pool.token_a.lower() == token_in:
            r_in = pool.reserve_a
        else:
            r_in = pool.reserve_b
        impact = (amount / r_in * 100) if r_in > 0 else 100.0
        impacts.append(impact)
        # Simulate this hop to get the amount for the next
        if pool.token_a.lower() == token_in:
            amount = simulate_swap_exact(amount, pool.reserve_a, pool.reserve_b)
        else:
            amount = simulate_swap_exact(amount, pool.reserve_b, pool.reserve_a)
    return impacts


# ── Optimal input binary search ─────────────────────────────────────────────

def optimal_input_binary_search(
    pools: list[PoolEdge],
    path: list[str],
    max_impact_pct: float = GRAPH_ARB_MAX_IMPACT_PCT,
) -> int:
    """
    Binary search for the input amount that maximizes profit.
    Profit = output - input. We search for the peak.

    Constraints:
      - No hop can consume > max_impact_pct of its pool reserves
      - Input > 0

    Returns optimal input in wei (0 if no profitable input found).
    """
    # Determine max input from impact cap
    max_inputs = []
    for i, pool in enumerate(pools):
        token_in = path[i].lower()
        if pool.token_a.lower() == token_in:
            r_in = pool.reserve_a
        else:
            r_in = pool.reserve_b
        if r_in > 0:
            max_inputs.append(int(r_in * max_impact_pct / 100))
        else:
            return 0

    if not max_inputs:
        return 0

    max_input = min(max_inputs)
    if max_input == 0:
        return 0

    # Binary search for peak profit
    # Profit function is concave (increases then decreases) due to AMM math
    lo, hi = 1, max_input
    best_input = 0
    best_profit = 0

    # Coarse scan first (10 points)
    for frac in range(1, 11):
        test_input = max_input * frac // 10
        if test_input == 0:
            continue
        output = _simulate_multihop(test_input, pools, path)
        profit = output - test_input
        if profit > best_profit:
            best_profit = profit
            best_input = test_input
            lo = max(1, max_input * (frac - 1) // 10)
            hi = min(max_input, max_input * (frac + 1) // 10)

    if best_profit <= 0:
        return 0

    # Fine binary search in the narrowed range
    for _ in range(64):  # 64 iterations = plenty of precision
        if hi - lo < 1000:  # 1000 wei precision is enough
            break
        mid1 = lo + (hi - lo) // 3
        mid2 = hi - (hi - lo) // 3

        out1 = _simulate_multihop(mid1, pools, path)
        out2 = _simulate_multihop(mid2, pools, path)
        profit1 = out1 - mid1
        profit2 = out2 - mid2

        if profit1 < profit2:
            lo = mid1
            if profit2 > best_profit:
                best_profit = profit2
                best_input = mid2
        else:
            hi = mid2
            if profit1 > best_profit:
                best_profit = profit1
                best_input = mid1

    return best_input if best_profit > 0 else 0


# ── Cycle scoring ────────────────────────────────────────────────────────────

def score_cycle(
    path: list[str],
    pools: list[PoolEdge],
    gas_price_wei: int,
    wpls_price_map: dict[str, int] | None = None,
) -> ArbCycle | None:
    """
    Score a candidate cycle with optimal input sizing.

    Args:
        path: [tokenA, tokenB, tokenC, tokenA] — closed loop
        pools: Pool for each hop (len = len(path) - 1)
        gas_price_wei: current gas price in wei
        wpls_price_map: {token_addr_lower: wpls_per_token_wei} for PLS conversion

    Returns ArbCycle if profitable, None otherwise.
    """
    if len(pools) != len(path) - 1:
        return None

    # Find optimal input
    opt_input = optimal_input_binary_search(pools, path)
    if opt_input == 0:
        return None

    output = _simulate_multihop(opt_input, pools, path)
    profit = output - opt_input
    if profit <= 0:
        return None

    # Convert profit to PLS terms
    start_token = path[0].lower()
    gas_est_units = TRIANGLE_GAS_ESTIMATE if len(pools) == 3 else QUAD_GAS_ESTIMATE
    gas_cost_pls = gas_est_units * gas_price_wei

    if start_token == WPLS.lower():
        profit_pls = profit
    elif wpls_price_map and start_token in wpls_price_map:
        # profit is in start_token units; convert to PLS
        price = wpls_price_map[start_token]
        if price > 0:
            profit_pls = profit * price // (10**18)
        else:
            profit_pls = 0
    else:
        # If we can't price it, skip
        return None

    net_profit = profit_pls - gas_cost_pls
    if net_profit <= 0:
        return None

    impacts = _compute_impacts(opt_input, pools, path)

    # Check impact cap
    if any(imp > GRAPH_ARB_MAX_IMPACT_PCT for imp in impacts):
        return None

    score = net_profit / gas_cost_pls if gas_cost_pls > 0 else 0.0

    return ArbCycle(
        path=path,
        pools=pools,
        direction="forward",
        optimal_input=opt_input,
        expected_output=output,
        expected_profit=profit,
        expected_profit_pls=profit_pls,
        gas_estimate=gas_cost_pls,
        net_profit_pls=net_profit,
        score=score,
        pool_impacts=impacts,
    )


# ── Triangle finder ──────────────────────────────────────────────────────────

def find_triangles(
    graph: PairGraph,
    start_token: str,
    gas_price_wei: int = 0,
    min_profit_pls: int = 0,
    wpls_price_map: dict[str, int] | None = None,
) -> list[ArbCycle]:
    """
    Find all profitable triangle arb cycles starting from `start_token`.

    Algorithm:
      For each pair of neighbors (B, C) of start_token:
        If B↔C edge exists:
          Score: start→B→C→start
          Score: start→C→B→start (reverse direction)
          For each hop, try both V1 and V2 pools and pick the best combo.

    Returns list of profitable ArbCycles sorted by net_profit_pls descending.
    """
    if gas_price_wei == 0:
        from ..core.chain import w3_read
        gas_price_wei = w3_read.eth.gas_price

    if min_profit_pls == 0:
        min_profit_pls = GRAPH_ARB_MIN_PROFIT_PLS

    min_profit_wei = min_profit_pls * 10**18
    start_lc = start_token.lower()
    neighbors = graph.neighbors(start_token)

    if len(neighbors) < 2:
        log.debug("Start token %s has < 2 neighbors — no triangles possible", graph.symbol(start_token))
        return []

    log.info("Scanning triangles from %s (%d neighbors)...", graph.symbol(start_token), len(neighbors))

    candidates = []
    checked = set()

    for i, b in enumerate(neighbors):
        for c in neighbors[i + 1:]:
            # Check if B↔C edge exists
            bc_edges = graph.get_all_edges(b, c)
            if not bc_edges:
                continue

            # Avoid duplicate checks
            pair_key = tuple(sorted([b, c]))
            if pair_key in checked:
                continue
            checked.add(pair_key)

            # For each direction: start→B→C→start and start→C→B→start
            for direction, (mid1, mid2) in [("fwd", (b, c)), ("rev", (c, b))]:
                # Get all pool options per hop
                hop1_edges = graph.get_all_edges(start_lc, mid1)
                hop2_edges = graph.get_all_edges(mid1, mid2)
                hop3_edges = graph.get_all_edges(mid2, start_lc)

                if not hop1_edges or not hop2_edges or not hop3_edges:
                    continue

                # Try all combinations of V1/V2 per hop, pick best
                best_cycle = None
                for e1 in hop1_edges:
                    for e2 in hop2_edges:
                        for e3 in hop3_edges:
                            path = [start_lc, mid1, mid2, start_lc]
                            cycle = score_cycle(
                                path, [e1, e2, e3],
                                gas_price_wei, wpls_price_map,
                            )
                            if cycle and (best_cycle is None or cycle.net_profit_pls > best_cycle.net_profit_pls):
                                best_cycle = cycle

                if best_cycle and best_cycle.net_profit_pls >= min_profit_wei:
                    best_cycle.direction = direction
                    candidates.append(best_cycle)

    candidates.sort(key=lambda c: c.net_profit_pls, reverse=True)
    log.info("Found %d profitable triangles from %s", len(candidates), graph.symbol(start_token))
    return candidates


def find_quads(
    graph: PairGraph,
    start_token: str,
    gas_price_wei: int = 0,
    min_profit_pls: int = 5000,
    wpls_price_map: dict[str, int] | None = None,
) -> list[ArbCycle]:
    """
    Find profitable 4-hop arbitrage cycles.
    start → B → C → D → start

    More expensive (1.2% total fees) so higher min profit threshold.
    Only scans tokens reachable in 2 hops from start.
    """
    if gas_price_wei == 0:
        from ..core.chain import w3_read
        gas_price_wei = w3_read.eth.gas_price

    min_profit_wei = min_profit_pls * 10**18
    start_lc = start_token.lower()
    neighbors = graph.neighbors(start_token)

    if len(neighbors) < 2:
        return []

    # BFS 2 hops: find all tokens reachable in exactly 2 hops
    hop2_tokens: dict[str, list[str]] = {}  # token → [intermediate tokens to reach it]
    for b in neighbors:
        for d in graph.neighbors(b):
            if d == start_lc or d == b:
                continue
            hop2_tokens.setdefault(d, []).append(b)

    log.info("Scanning quads from %s (%d 2-hop tokens)...", graph.symbol(start_token), len(hop2_tokens))

    candidates = []
    checked = set()

    for b in neighbors:
        b_neighbors = graph.neighbors(b)
        for c in b_neighbors:
            if c == start_lc or c == b:
                continue
            c_neighbors = graph.neighbors(c)
            for d in c_neighbors:
                if d == start_lc or d == b or d == c:
                    continue
                # Check if D→start edge exists
                ds_edges = graph.get_all_edges(d, start_lc)
                if not ds_edges:
                    continue

                quad_key = tuple(sorted([b, c, d]))
                if quad_key in checked:
                    continue
                checked.add(quad_key)

                # Get edges for each hop
                e1s = graph.get_all_edges(start_lc, b)
                e2s = graph.get_all_edges(b, c)
                e3s = graph.get_all_edges(c, d)
                e4s = ds_edges

                if not e1s or not e2s or not e3s or not e4s:
                    continue

                # Pick best pool per hop (greedy — skip full combinatorial for quads)
                path = [start_lc, b, c, d, start_lc]
                # Use first available pool per hop (simplification)
                cycle = score_cycle(
                    path, [e1s[0], e2s[0], e3s[0], e4s[0]],
                    gas_price_wei, wpls_price_map,
                )
                if cycle and cycle.net_profit_pls >= min_profit_wei:
                    candidates.append(cycle)

    candidates.sort(key=lambda c: c.net_profit_pls, reverse=True)
    log.info("Found %d profitable quads from %s", len(candidates), graph.symbol(start_token))
    return candidates


# ── Multi-hub scanner ────────────────────────────────────────────────────────

def scan_all_triangles(
    graph: PairGraph,
    hub_tokens: list[str] | None = None,
    gas_price_wei: int = 0,
    min_profit_pls: int = 0,
) -> list[ArbCycle]:
    """
    Scan triangles from multiple hub tokens and deduplicate.
    Returns combined list sorted by net_profit_pls descending.
    """
    if hub_tokens is None:
        # Use WPLS, AFFECTION, and FED as primary triangle hubs
        hub_tokens = HUB_TOKENS[:3]

    all_cycles = []
    seen_paths = set()

    for hub in hub_tokens:
        cycles = find_triangles(graph, hub, gas_price_wei, min_profit_pls)
        for cycle in cycles:
            # Deduplicate: normalize path as sorted pool addresses
            pool_key = tuple(sorted(p.pair_address.lower() for p in cycle.pools))
            if pool_key not in seen_paths:
                seen_paths.add(pool_key)
                all_cycles.append(cycle)

    all_cycles.sort(key=lambda c: c.net_profit_pls, reverse=True)
    return all_cycles


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    parser = argparse.ArgumentParser(description="Graph Arb — Triangle/Quad cycle finder")
    parser.add_argument("--hub", default=WPLS, help="Start token for triangle scan")
    parser.add_argument("--min-profit", type=int, default=1000, help="Min profit in PLS")
    parser.add_argument("--quads", action="store_true", help="Also scan for quads")
    parser.add_argument("--top", type=int, default=10, help="Show top N cycles")
    args = parser.parse_args()

    from .pair_discovery import load_pair_graph, discover_pairs, refresh_reserves, reserves_stale

    graph = load_pair_graph()
    if not graph:
        print("No cached pair graph — running discovery (this takes a few minutes)...")
        graph = discover_pairs()
    elif reserves_stale(graph):
        print("Refreshing stale reserves...")
        refresh_reserves(graph)

    print(f"\nGraph: {graph.edge_count} pairs, {graph.token_count} tokens")

    from ..core.chain import w3_read
    gas_price = w3_read.eth.gas_price
    print(f"Gas price: {gas_price / 1e9:.2f} Gwei")

    # Scan triangles from primary hubs
    triangles = scan_all_triangles(graph, gas_price_wei=gas_price, min_profit_pls=args.min_profit)

    print(f"\n{'='*80}")
    print(f"PROFITABLE TRIANGLES: {len(triangles)}")
    print(f"{'='*80}")
    for i, cycle in enumerate(triangles[:args.top]):
        print(f"\n#{i+1}: {cycle.summary()}")
        print(f"      Pools: {' | '.join(f'[{p.factory}] {p.symbol_a}/{p.symbol_b}' for p in cycle.pools)}")
        print(f"      Impacts: {', '.join(f'{imp:.2f}%' for imp in cycle.pool_impacts)}")

    if args.quads:
        quads = find_quads(graph, WPLS, gas_price, args.min_profit * 5)
        print(f"\n{'='*80}")
        print(f"PROFITABLE QUADS: {len(quads)}")
        print(f"{'='*80}")
        for i, cycle in enumerate(quads[:args.top]):
            print(f"\n#{i+1}: {cycle.summary()}")
