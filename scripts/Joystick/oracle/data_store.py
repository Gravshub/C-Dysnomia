"""
data_store.py — Centralized JSON data access for all engines.

Lazy-loads and caches data files from scripts/Joystick/data/.
Provides typed lookup methods so engines never touch json.load() directly.
Follows Helios pattern: pre-cached JSON eliminates runtime RPC scanning.
"""
import json
import logging

from ..core.log_names import get_logger
import os
import time
from typing import Optional

from web3 import Web3

from ..core.config import WPLS, PULSEX_V1_FACTORY, PULSEX_V2_FACTORY

log = get_logger(__name__)

_JOYSTICK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_JOYSTICK_DIR, "data")

# Factory address → label mapping for pair lookups
_FACTORY_LABELS = {
    PULSEX_V1_FACTORY.lower(): "V1",
    PULSEX_V2_FACTORY.lower(): "V2",
}


class DataStore:
    """Singleton-ish lazy loader for all JSON data files."""

    _instance: Optional["DataStore"] = None

    def __init__(self):
        self._pair_graph = None
        self._pair_graph_ts: float = 0
        self._token_master: Optional[dict] = None
        self._recon: Optional[dict] = None
        self._recon_ts: float = 0
        self._v2_federal: Optional[list] = None
        self._contracts: Optional[dict] = None
        self._pulsex_dual: Optional[list] = None

    @classmethod
    def get(cls) -> "DataStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Pair Registry ────────────────────────────────────────────────

    def pair_graph(self, max_age: float = 300):
        """Load pair_registry.json as PairGraph. Returns None if missing/expired."""
        from .pair_discovery import PairGraph

        now = time.time()
        if self._pair_graph and (now - self._pair_graph_ts) < max_age:
            return self._pair_graph

        path = os.path.join(_DATA_DIR, "pair_registry.json")
        if not os.path.exists(path):
            log.debug("DataStore: pair_registry.json not found")
            return None

        try:
            with open(path) as f:
                data = json.load(f)
            graph = PairGraph.from_dict(data)
            self._pair_graph = graph
            self._pair_graph_ts = now
            log.debug("DataStore: pair_graph loaded — %d edges, %d tokens",
                       graph.edge_count, graph.token_count)
            return graph
        except Exception as exc:
            log.warning("DataStore: failed to load pair_registry.json: %s", exc)
            return None

    def lookup_pair(self, token_a: str, token_b: str, factory: str = "") -> Optional[str]:
        """Return pair address from cache, or None. No RPC call."""
        graph = self.pair_graph()
        if not graph:
            return None

        edge = graph.get_edge(token_a, token_b, factory=factory)
        if edge:
            return edge.pair_address
        return None

    def has_pair(self, token_a: str, token_b: str, factory: str = "") -> bool:
        """Check if a pair exists in the registry. No RPC call."""
        return self.lookup_pair(token_a, token_b, factory=factory) is not None

    def dual_dex_tokens(self, base_token: str = "") -> list[tuple[str, str, str, str]]:
        """
        Return tokens with pairs on BOTH V1 and V2 against base_token.
        Returns [(token_addr, symbol, v1_pair_addr, v2_pair_addr), ...]
        Replaces E1._cross_dex_candidates() RPC scanning entirely.
        """
        if not base_token:
            base_token = WPLS

        graph = self.pair_graph()
        if not graph:
            return []

        base_lc = base_token.lower()
        # Find all edges touching base_token
        edges = graph.edges.get(base_lc, [])
        if not edges:
            return []

        # Group by partner token and factory
        token_factories: dict[str, dict[str, str]] = {}  # token_lc → {factory → pair_addr}
        for edge in edges:
            partner = edge.token_b.lower() if edge.token_a.lower() == base_lc else edge.token_a.lower()
            token_factories.setdefault(partner, {})[edge.factory] = edge.pair_address

        results = []
        for tok_lc, fmap in token_factories.items():
            if "V1" in fmap and "V2" in fmap:
                sym = graph.symbol(tok_lc)
                results.append((
                    Web3.to_checksum_address(tok_lc),
                    sym,
                    fmap["V1"],
                    fmap["V2"],
                ))

        log.debug("DataStore: %d dual-DEX tokens against %s", len(results), base_token[:10])
        return results

    def pairs_for_token(self, token: str) -> list[dict]:
        """All pairs touching this token. Returns list of edge dicts."""
        graph = self.pair_graph()
        if not graph:
            return []

        edges = graph.edges.get(token.lower(), [])
        return [e.to_dict() for e in edges]

    # ── Token Master ─────────────────────────────────────────────────

    def _load_token_master(self) -> dict:
        if self._token_master is not None:
            return self._token_master

        path = os.path.join(_DATA_DIR, "token_master.json")
        if not os.path.exists(path):
            log.debug("DataStore: token_master.json not found")
            self._token_master = {}
            return self._token_master

        try:
            with open(path) as f:
                data = json.load(f)
            tokens = {}
            for addr, info in data.get("tokens", {}).items():
                tokens[addr.lower()] = info.get("symbol", "?")
            self._token_master = tokens
            log.debug("DataStore: loaded %d tokens from token_master.json", len(tokens))
            return tokens
        except Exception as exc:
            log.warning("DataStore: failed to load token_master.json: %s", exc)
            self._token_master = {}
            return self._token_master

    def token_symbol(self, address: str) -> str:
        """Lookup symbol from token_master.json. Returns address[:10] if unknown."""
        tokens = self._load_token_master()
        return tokens.get(address.lower(), address[:10])

    def all_tokens(self) -> dict[str, str]:
        """Full {lowercase_addr: symbol} dict from token_master."""
        return dict(self._load_token_master())

    # ── Recon Results ────────────────────────────────────────────────

    def recon_data(self, max_age: float = 3600) -> dict:
        """Load recon_results.json with TTL cache."""
        now = time.time()
        if self._recon is not None and (now - self._recon_ts) < max_age:
            return self._recon

        path = os.path.join(_DATA_DIR, "recon_results.json")
        if not os.path.exists(path):
            log.debug("DataStore: recon_results.json not found")
            return {}

        try:
            with open(path) as f:
                data = json.load(f)
            self._recon = data
            self._recon_ts = now
            results_count = len(data.get("results", {}))
            log.debug("DataStore: loaded recon_results.json (%d results)", results_count)
            return data
        except Exception as exc:
            log.warning("DataStore: failed to load recon_results.json: %s", exc)
            return {}

    # ── V2 Federal Tokens ────────────────────────────────────────────

    def v2_federal_tokens(self) -> list[dict]:
        """Load v2_federal_tokens.json (static, no TTL needed)."""
        if self._v2_federal is not None:
            return self._v2_federal

        path = os.path.join(_DATA_DIR, "v2_federal_tokens.json")
        if not os.path.exists(path):
            log.debug("DataStore: v2_federal_tokens.json not found")
            self._v2_federal = []
            return self._v2_federal

        try:
            with open(path) as f:
                data = json.load(f)
            self._v2_federal = data.get("tokens", [])
            log.debug("DataStore: loaded %d V2 federal tokens", len(self._v2_federal))
            return self._v2_federal
        except Exception as exc:
            log.warning("DataStore: failed to load v2_federal_tokens.json: %s", exc)
            self._v2_federal = []
            return self._v2_federal

    def debenture_tokens(self) -> list[dict]:
        """Filter v2_federal to Debenture=true only."""
        return [t for t in self.v2_federal_tokens() if t.get("debenture") is True]

    # ── PulseX Dual-DEX Token List ────────────────────────────────────

    def pulsex_dual_dex(self, min_spread_bps: float = 0, min_tvl_pls: float = 0) -> list[dict]:
        """
        Load pulsex_dual_dex_tokens.json — broader PulseX V1+V2 arb candidates.
        Returns list of token dicts, optionally filtered by min spread and TVL.
        Static file — no TTL needed (refreshed by manual recon runs).
        """
        if self._pulsex_dual is None:
            path = os.path.join(_DATA_DIR, "pulsex_dual_dex_tokens.json")
            if not os.path.exists(path):
                log.debug("DataStore: pulsex_dual_dex_tokens.json not found")
                self._pulsex_dual = []
            else:
                try:
                    with open(path) as f:
                        data = json.load(f)
                    self._pulsex_dual = data.get("tokens", [])
                    log.debug("DataStore: loaded %d pulsex dual-DEX tokens",
                              len(self._pulsex_dual))
                except Exception as exc:
                    log.warning("DataStore: failed to load pulsex_dual_dex_tokens.json: %s", exc)
                    self._pulsex_dual = []

        tokens = self._pulsex_dual
        if min_spread_bps > 0 or min_tvl_pls > 0:
            tokens = [
                t for t in tokens
                if t.get("spread_bps", 0) >= min_spread_bps
                and t.get("combined_wpls_pls", 0) >= min_tvl_pls
            ]
        return tokens

    # ── Cache Management ─────────────────────────────────────────────

    def invalidate(self, which: str = "all") -> None:
        """Force reload on next access. which: 'pairs', 'recon', 'tokens', 'v2fed', 'pulsex', 'all'."""
        if which in ("pairs", "all"):
            self._pair_graph = None
            self._pair_graph_ts = 0
        if which in ("recon", "all"):
            self._recon = None
            self._recon_ts = 0
        if which in ("tokens", "all"):
            self._token_master = None
        if which in ("v2fed", "all"):
            self._v2_federal = None
        if which in ("pulsex", "all"):
            self._pulsex_dual = None
        if which in ("all",):
            self._contracts = None
        log.debug("DataStore: invalidated cache '%s'", which)

    def refresh_pair_registry(self):
        """Force full pair discovery scan and update cache file."""
        from .pair_discovery import discover_pairs
        graph = discover_pairs()
        self._pair_graph = graph
        self._pair_graph_ts = time.time()
        return graph
