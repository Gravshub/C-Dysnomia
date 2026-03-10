"""
pair_discovery.py — DEX pool graph builder via Multicall3 batched factory queries.

Discovers ALL token-token DEX pairs across PulseX V1 and V2 factories using
a tiered approach:

  Tier 1: Hub tokens × all known tokens (catches 95%+ of liquidity)
  Tier 2: Cross-token pairs between tokens found in Tier 1

Pair addresses are stable (cached long-term); reserves are volatile (short TTL).
Cache split: pair_registry.json (stable) + pair_reserves.json (volatile).

This module feeds oracle/graph.py for triangle/cycle arb discovery.
Does NOT import from scanner.py — parallel discovery system for different arb modes.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from web3 import Web3

from ..core.config import (
    WPLS, AFFECTION, HUB_TOKENS,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    MULTICALL3, GRAPH_CACHE_TTL, RESERVE_CACHE_TTL,
)
from ..core.chain import w3_read, safe, factory_contract

log = logging.getLogger(__name__)

_JOYSTICK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_JOYSTICK_DIR, "data")
REGISTRY_CACHE = os.path.join(_DATA_DIR, "pair_registry.json")
RESERVES_CACHE = os.path.join(_DATA_DIR, "pair_reserves.json")
TOKEN_MASTER = os.path.join(_DATA_DIR, "token_master.json")

ZERO_ADDR = "0x" + "0" * 40
BATCH_SIZE = 200

# ABI fragments for raw encoding (avoid contract object overhead in batches)
GET_PAIR_SIG = Web3.keccak(text="getPair(address,address)")[:4]
GET_RESERVES_SIG = Web3.keccak(text="getReserves()")[:4]
TOKEN0_SIG = Web3.keccak(text="token0()")[:4]

MULTICALL3_ABI = [{
    "inputs": [{"components": [
        {"name": "target", "type": "address"},
        {"name": "allowFailure", "type": "bool"},
        {"name": "callData", "type": "bytes"}
    ], "name": "calls", "type": "tuple[]"}],
    "name": "aggregate3",
    "outputs": [{"components": [
        {"name": "success", "type": "bool"},
        {"name": "returnData", "type": "bytes"}
    ], "name": "returnData", "type": "tuple[]"}],
    "stateMutability": "view",
    "type": "function"
}]


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class PoolEdge:
    pair_address: str
    token_a: str
    token_b: str
    symbol_a: str
    symbol_b: str
    factory: str          # "V1" or "V2"
    reserve_a: int = 0    # in wei
    reserve_b: int = 0    # in wei
    last_updated: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PoolEdge":
        return cls(**d)


class PairGraph:
    """Adjacency graph of DEX pool edges, keyed by token address."""

    def __init__(self):
        self.edges: dict[str, list[PoolEdge]] = {}   # token_addr -> [edges touching it]
        self.pairs: dict[str, PoolEdge] = {}          # pair_addr -> edge
        self._token_symbols: dict[str, str] = {}      # addr -> symbol
        self.registry_ts: float = 0.0                  # when pair registry was built
        self.reserves_ts: float = 0.0                  # when reserves were last refreshed

    def add_edge(self, edge: PoolEdge) -> None:
        key_a = edge.token_a.lower()
        key_b = edge.token_b.lower()
        self.edges.setdefault(key_a, []).append(edge)
        self.edges.setdefault(key_b, []).append(edge)
        self.pairs[edge.pair_address.lower()] = edge
        if edge.symbol_a:
            self._token_symbols[key_a] = edge.symbol_a
        if edge.symbol_b:
            self._token_symbols[key_b] = edge.symbol_b

    def neighbors(self, token: str) -> list[str]:
        """All tokens directly connected to `token` via any pool."""
        token_lc = token.lower()
        seen = set()
        for edge in self.edges.get(token_lc, []):
            other = edge.token_b.lower() if edge.token_a.lower() == token_lc else edge.token_a.lower()
            seen.add(other)
        return list(seen)

    def get_edge(self, token_a: str, token_b: str, factory: str = "") -> Optional[PoolEdge]:
        """Get a specific edge between two tokens, optionally filtered by factory."""
        a_lc, b_lc = token_a.lower(), token_b.lower()
        for edge in self.edges.get(a_lc, []):
            ea, eb = edge.token_a.lower(), edge.token_b.lower()
            if (ea == a_lc and eb == b_lc) or (ea == b_lc and eb == a_lc):
                if not factory or edge.factory == factory:
                    return edge
        return None

    def get_all_edges(self, token_a: str, token_b: str) -> list[PoolEdge]:
        """Get ALL edges between two tokens (may span V1 and V2)."""
        a_lc, b_lc = token_a.lower(), token_b.lower()
        result = []
        for edge in self.edges.get(a_lc, []):
            ea, eb = edge.token_a.lower(), edge.token_b.lower()
            if (ea == a_lc and eb == b_lc) or (ea == b_lc and eb == a_lc):
                result.append(edge)
        return result

    def tokens_with_min_pairs(self, n: int) -> list[str]:
        """Tokens that appear in at least `n` distinct pairs."""
        return [tok for tok, edges in self.edges.items() if len(edges) >= n]

    def symbol(self, token: str) -> str:
        return self._token_symbols.get(token.lower(), token[:10])

    @property
    def edge_count(self) -> int:
        return len(self.pairs)

    @property
    def token_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict:
        return {
            "registry_ts": self.registry_ts,
            "reserves_ts": self.reserves_ts,
            "symbols": self._token_symbols,
            "pairs": {k: v.to_dict() for k, v in self.pairs.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PairGraph":
        graph = cls()
        graph.registry_ts = d.get("registry_ts", 0)
        graph.reserves_ts = d.get("reserves_ts", 0)
        graph._token_symbols = d.get("symbols", {})
        for pair_addr, edge_dict in d.get("pairs", {}).items():
            edge = PoolEdge.from_dict(edge_dict)
            graph.pairs[pair_addr.lower()] = edge
            key_a = edge.token_a.lower()
            key_b = edge.token_b.lower()
            graph.edges.setdefault(key_a, []).append(edge)
            graph.edges.setdefault(key_b, []).append(edge)
        return graph


# ── Multicall3 helpers ───────────────────────────────────────────────────────

def _mc3(calls: list[tuple[str, bytes]]) -> list[tuple[bool, bytes]]:
    """
    Execute batched calls via Multicall3.aggregate3.
    Input: [(target_addr, calldata), ...]
    Output: [(success, returnData), ...]
    """
    mc = w3_read.eth.contract(address=MULTICALL3, abi=MULTICALL3_ABI)
    results_all = []
    for i in range(0, len(calls), BATCH_SIZE):
        batch = calls[i:i + BATCH_SIZE]
        encoded = [
            (Web3.to_checksum_address(addr), True, data)
            for addr, data in batch
        ]
        try:
            raw = mc.functions.aggregate3(encoded).call()
            results_all.extend(raw)
        except Exception as exc:
            log.warning("Multicall3 batch %d failed: %s", i // BATCH_SIZE, exc)
            results_all.extend([(False, b"")] * len(batch))
    return results_all


def _encode_get_pair(token_a: str, token_b: str) -> bytes:
    """Encode factory.getPair(tokenA, tokenB) calldata."""
    a_bytes = bytes.fromhex(token_a[2:].lower().zfill(64))
    b_bytes = bytes.fromhex(token_b[2:].lower().zfill(64))
    # ABI encode: selector + address padded to 32 bytes each
    return (
        GET_PAIR_SIG
        + bytes(12) + bytes.fromhex(token_a[2:].lower())
        + bytes(12) + bytes.fromhex(token_b[2:].lower())
    )


def _decode_address(data: bytes) -> str:
    """Decode an ABI-encoded address from returnData."""
    if len(data) < 32:
        return ZERO_ADDR
    addr_bytes = data[12:32]
    return Web3.to_checksum_address("0x" + addr_bytes.hex())


def _encode_get_reserves() -> bytes:
    return GET_RESERVES_SIG


def _decode_reserves(data: bytes) -> tuple[int, int, int]:
    """Decode getReserves() → (reserve0, reserve1, blockTimestampLast)."""
    if len(data) < 96:
        return (0, 0, 0)
    r0 = int.from_bytes(data[0:32], "big")
    r1 = int.from_bytes(data[32:64], "big")
    ts = int.from_bytes(data[64:96], "big")
    return (r0, r1, ts)


def _encode_token0() -> bytes:
    return TOKEN0_SIG


# ── Token master loader ─────────────────────────────────────────────────────

def _load_all_tokens() -> dict[str, str]:
    """Load token_master.json → {lowercase_addr: symbol}."""
    if not os.path.exists(TOKEN_MASTER):
        log.warning("token_master.json not found — using hub tokens only")
        return {}
    try:
        with open(TOKEN_MASTER) as f:
            data = json.load(f)
        tokens = {}
        for addr, info in data.get("tokens", {}).items():
            cs = Web3.to_checksum_address(info["address"])
            tokens[cs.lower()] = info.get("symbol", "?")
        log.debug("Loaded %d tokens from token_master.json", len(tokens))
        return tokens
    except Exception as exc:
        log.warning("Failed to load token_master.json: %s", exc)
        return {}


# ── Tier 1: Hub × All Tokens ────────────────────────────────────────────────

def _discover_hub_pairs(
    hub_tokens: list[str],
    all_tokens: dict[str, str],
    factory_addr: str,
    factory_label: str,
) -> list[tuple[str, str, str, str, str, str]]:
    """
    Batch-query factory.getPair(hub, token) for all hub × token combinations.
    Returns: [(pair_addr, tokenA, tokenB, symbolA, symbolB, factory_label), ...]
    """
    # Build call list: every hub × every token
    queries = []  # (hub, token, hub_sym, token_sym)
    hub_set = {h.lower() for h in hub_tokens}
    hub_syms = {}
    for h in hub_tokens:
        # Look up symbol from all_tokens or use address prefix
        hub_syms[h.lower()] = all_tokens.get(h.lower(), h[:10])

    for hub in hub_tokens:
        for tok_addr_lc, tok_sym in all_tokens.items():
            tok_addr = Web3.to_checksum_address(tok_addr_lc)
            if tok_addr.lower() == hub.lower():
                continue
            queries.append((hub, tok_addr, hub_syms[hub.lower()], tok_sym))

    if not queries:
        return []

    log.info("Tier 1 [%s]: %d getPair queries (%d hubs × %d tokens)",
             factory_label, len(queries), len(hub_tokens), len(all_tokens))

    # Encode multicall
    calls = [(factory_addr, _encode_get_pair(q[0], q[1])) for q in queries]
    results = _mc3(calls)

    found = []
    for (hub, tok, hub_sym, tok_sym), (success, data) in zip(queries, results):
        if not success or not data:
            continue
        pair_addr = _decode_address(data)
        if pair_addr == ZERO_ADDR:
            continue
        found.append((pair_addr, hub, tok, hub_sym, tok_sym, factory_label))

    log.info("Tier 1 [%s]: found %d pairs", factory_label, len(found))
    return found


# ── Tier 2: Cross-Token Pairs ───────────────────────────────────────────────

def _discover_cross_pairs(
    paired_tokens: set[str],
    all_tokens: dict[str, str],
    factory_addr: str,
    factory_label: str,
    existing_pairs: set[str],
) -> list[tuple[str, str, str, str, str, str]]:
    """
    For tokens that have at least one hub pair, check pairs against each other.
    Catches GIBS/FED style pairs where neither is a hub.
    """
    tokens_list = sorted(paired_tokens)
    queries = []
    for i, a in enumerate(tokens_list):
        for b in tokens_list[i + 1:]:
            # Skip if we already know this pair
            pair_key = tuple(sorted([a.lower(), b.lower()]))
            if f"{pair_key[0]}:{pair_key[1]}:{factory_label}" in existing_pairs:
                continue
            sym_a = all_tokens.get(a.lower(), a[:10])
            sym_b = all_tokens.get(b.lower(), b[:10])
            queries.append((Web3.to_checksum_address(a), Web3.to_checksum_address(b), sym_a, sym_b))

    if not queries:
        return []

    # Cap at 5000 queries to stay reasonable
    if len(queries) > 5000:
        log.info("Tier 2 [%s]: capping cross-pair queries from %d to 5000", factory_label, len(queries))
        queries = queries[:5000]

    log.info("Tier 2 [%s]: %d cross-pair getPair queries", factory_label, len(queries))

    calls = [(factory_addr, _encode_get_pair(q[0], q[1])) for q in queries]
    results = _mc3(calls)

    found = []
    for (a, b, sym_a, sym_b), (success, data) in zip(queries, results):
        if not success or not data:
            continue
        pair_addr = _decode_address(data)
        if pair_addr == ZERO_ADDR:
            continue
        found.append((pair_addr, a, b, sym_a, sym_b, factory_label))

    log.info("Tier 2 [%s]: found %d cross-pairs", factory_label, len(found))
    return found


# ── Reserve reading ──────────────────────────────────────────────────────────

def _batch_read_token0(pair_addrs: list[str]) -> dict[str, str]:
    """Batch-read token0() for all pairs to determine reserve order."""
    calls = [(addr, _encode_token0()) for addr in pair_addrs]
    results = _mc3(calls)
    out = {}
    for addr, (success, data) in zip(pair_addrs, results):
        if success and data and len(data) >= 32:
            out[addr.lower()] = _decode_address(data).lower()
    return out


def batch_get_reserves(graph: PairGraph) -> None:
    """
    Read getReserves() for all pairs in the graph via Multicall3.
    Updates edge reserve_a/reserve_b in-place.
    """
    pair_addrs = list(graph.pairs.keys())
    if not pair_addrs:
        return

    # First, read token0 for all pairs (to know reserve order)
    token0_map = _batch_read_token0([Web3.to_checksum_address(a) for a in pair_addrs])

    # Then batch getReserves
    calls = [(Web3.to_checksum_address(a), _encode_get_reserves()) for a in pair_addrs]
    results = _mc3(calls)

    now = time.time()
    updated = 0
    for addr_lc, (success, data) in zip(pair_addrs, results):
        if not success or not data:
            continue
        edge = graph.pairs.get(addr_lc)
        if not edge:
            continue
        r0, r1, _ = _decode_reserves(data)
        if r0 == 0 and r1 == 0:
            continue

        # Determine which reserve corresponds to token_a vs token_b
        t0 = token0_map.get(addr_lc, "")
        if t0 == edge.token_a.lower():
            edge.reserve_a, edge.reserve_b = r0, r1
        elif t0 == edge.token_b.lower():
            edge.reserve_a, edge.reserve_b = r1, r0
        else:
            # Fallback: assume sorted order matches
            edge.reserve_a, edge.reserve_b = r0, r1

        edge.last_updated = now
        updated += 1

    graph.reserves_ts = now
    log.info("Reserves updated: %d/%d pairs", updated, len(pair_addrs))


# ── Cache management ─────────────────────────────────────────────────────────

def save_pair_graph(graph: PairGraph) -> None:
    """Persist the pair graph to disk."""
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(REGISTRY_CACHE, "w") as f:
            json.dump(graph.to_dict(), f)
        log.debug("Pair graph saved: %d edges", graph.edge_count)
    except Exception as exc:
        log.warning("Failed to save pair graph: %s", exc)


def load_pair_graph() -> Optional[PairGraph]:
    """Load pair graph from cache if still valid."""
    if not os.path.exists(REGISTRY_CACHE):
        return None
    try:
        with open(REGISTRY_CACHE) as f:
            data = json.load(f)
        graph = PairGraph.from_dict(data)
        age = time.time() - graph.registry_ts
        if age > GRAPH_CACHE_TTL:
            log.debug("Pair registry cache expired (age %.0fs > TTL %ds)", age, GRAPH_CACHE_TTL)
            return None
        log.info("Pair graph cache hit: %d edges, %d tokens, age %.0fs",
                 graph.edge_count, graph.token_count, age)
        return graph
    except Exception as exc:
        log.warning("Failed to load pair graph cache: %s", exc)
        return None


def reserves_stale(graph: PairGraph) -> bool:
    """True if reserves need refreshing."""
    return (time.time() - graph.reserves_ts) > RESERVE_CACHE_TTL


# ── Main discovery entry point ───────────────────────────────────────────────

def discover_pairs(
    hub_tokens: Optional[list[str]] = None,
    all_tokens: Optional[dict[str, str]] = None,
) -> PairGraph:
    """
    Full pair discovery: Tier 1 (hub scan) + Tier 2 (cross-token).
    Returns a PairGraph with edges and reserves populated.
    """
    if hub_tokens is None:
        hub_tokens = HUB_TOKENS
    if all_tokens is None:
        all_tokens = _load_all_tokens()
        # Ensure hub tokens are in the list
        for h in hub_tokens:
            if h.lower() not in all_tokens:
                all_tokens[h.lower()] = h[:10]

    graph = PairGraph()
    factories = [
        (PULSEX_V1_FACTORY, "V1"),
        (PULSEX_V2_FACTORY, "V2"),
    ]

    all_found = []
    for factory_addr, factory_label in factories:
        found = _discover_hub_pairs(hub_tokens, all_tokens, factory_addr, factory_label)
        all_found.extend(found)

    # Track which tokens have at least one pair
    paired_tokens: set[str] = set()
    existing_pair_keys: set[str] = set()

    for pair_addr, tok_a, tok_b, sym_a, sym_b, factory_label in all_found:
        edge = PoolEdge(
            pair_address=Web3.to_checksum_address(pair_addr),
            token_a=Web3.to_checksum_address(tok_a),
            token_b=Web3.to_checksum_address(tok_b),
            symbol_a=sym_a,
            symbol_b=sym_b,
            factory=factory_label,
        )
        graph.add_edge(edge)
        paired_tokens.add(tok_a.lower())
        paired_tokens.add(tok_b.lower())
        pair_key = tuple(sorted([tok_a.lower(), tok_b.lower()]))
        existing_pair_keys.add(f"{pair_key[0]}:{pair_key[1]}:{factory_label}")

    # Tier 2: cross-token pairs
    if len(paired_tokens) > 2:
        for factory_addr, factory_label in factories:
            cross = _discover_cross_pairs(
                paired_tokens, all_tokens, factory_addr, factory_label, existing_pair_keys,
            )
            for pair_addr, tok_a, tok_b, sym_a, sym_b, fl in cross:
                edge = PoolEdge(
                    pair_address=Web3.to_checksum_address(pair_addr),
                    token_a=Web3.to_checksum_address(tok_a),
                    token_b=Web3.to_checksum_address(tok_b),
                    symbol_a=sym_a,
                    symbol_b=sym_b,
                    factory=fl,
                )
                graph.add_edge(edge)

    graph.registry_ts = time.time()

    # Read reserves for all discovered pairs
    batch_get_reserves(graph)

    # Filter dust pairs (< 1 PLS equivalent liquidity)
    _filter_dust(graph)

    save_pair_graph(graph)

    log.info("Discovery complete: %d pairs, %d tokens", graph.edge_count, graph.token_count)
    return graph


def refresh_reserves(graph: PairGraph) -> PairGraph:
    """Re-read reserves for all pairs in an existing graph."""
    batch_get_reserves(graph)
    save_pair_graph(graph)
    return graph


def _filter_dust(graph: PairGraph) -> None:
    """Remove pairs where both reserves are zero (dust/dead pools)."""
    dead = [
        addr for addr, edge in graph.pairs.items()
        if edge.reserve_a == 0 and edge.reserve_b == 0
    ]
    for addr in dead:
        edge = graph.pairs.pop(addr)
        # Remove from adjacency lists
        for tok in [edge.token_a.lower(), edge.token_b.lower()]:
            if tok in graph.edges:
                graph.edges[tok] = [e for e in graph.edges[tok] if e.pair_address.lower() != addr]
                if not graph.edges[tok]:
                    del graph.edges[tok]
    if dead:
        log.debug("Filtered %d dead pairs (zero reserves)", len(dead))


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    parser = argparse.ArgumentParser(description="Pair Discovery — DEX pool graph builder")
    parser.add_argument("--force", action="store_true", help="Bypass cache")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics")
    args = parser.parse_args()

    if not args.force:
        cached = load_pair_graph()
        if cached:
            if reserves_stale(cached):
                log.info("Reserves stale — refreshing...")
                refresh_reserves(cached)
            graph = cached
        else:
            graph = discover_pairs()
    else:
        graph = discover_pairs()

    print(f"\nPair Graph: {graph.edge_count} pairs, {graph.token_count} tokens")

    if args.stats:
        # Show top tokens by pair count
        token_pairs = [(tok, len(edges)) for tok, edges in graph.edges.items()]
        token_pairs.sort(key=lambda x: x[1], reverse=True)
        print("\nTop tokens by pair count:")
        for tok, count in token_pairs[:20]:
            sym = graph.symbol(tok)
            print(f"  {sym:12s} ({tok[:10]}...): {count} pairs")

        # Show some edges with reserves
        print("\nSample edges with reserves:")
        for i, (addr, edge) in enumerate(graph.pairs.items()):
            if i >= 20:
                break
            if edge.reserve_a > 0:
                print(f"  [{edge.factory}] {edge.symbol_a}/{edge.symbol_b}: "
                      f"r_a={edge.reserve_a / 1e18:.4f} r_b={edge.reserve_b / 1e18:.4f}")
