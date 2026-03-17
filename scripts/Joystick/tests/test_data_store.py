"""
test_data_store.py — Unit tests for oracle/data_store.py

Tests DataStore against the real JSON data files in scripts/Joystick/data/.
These tests do NOT require Anvil — they only read cached JSON files.
"""
import os
import sys
import pytest

# Ensure repo root is on path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Set minimal env vars to allow import (no RPC needed for these tests)
os.environ.setdefault("PULSECHAIN_RPC", "https://rpc.pulsechain.com")
os.environ.setdefault("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
os.environ.setdefault("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
os.environ.setdefault("DYSNOMIA_PRIVATE_KEY", "0x" + "00" * 32)

from scripts.Joystick.oracle.data_store import DataStore
from scripts.Joystick.core.config import GIBS_LAU, WPLS

# Data directory for file existence checks
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


class TestDataStore:
    """Unit tests for the DataStore singleton."""

    def setup_method(self):
        """Reset singleton before each test."""
        DataStore._instance = None

    def test_singleton(self):
        """get() returns the same instance."""
        a = DataStore.get()
        b = DataStore.get()
        assert a is b

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pair_registry.json")),
        reason="pair_registry.json not found",
    )
    def test_pair_graph_loads(self):
        """pair_graph() loads from pair_registry.json."""
        store = DataStore.get()
        graph = store.pair_graph()
        assert graph is not None
        assert graph.edge_count > 0
        assert graph.token_count > 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pair_registry.json")),
        reason="pair_registry.json not found",
    )
    def test_lookup_pair_gibs_wpls(self):
        """lookup_pair(GIBS_LAU, WPLS) returns the known pair address (V2)."""
        store = DataStore.get()
        # GIBS/WPLS is on V2 — no factory filter needed
        pair = store.lookup_pair(GIBS_LAU, WPLS)
        assert pair is not None
        assert pair.startswith("0x")
        assert len(pair) == 42

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pair_registry.json")),
        reason="pair_registry.json not found",
    )
    def test_has_pair_true(self):
        """has_pair() returns True for known GIBS/WPLS pair."""
        store = DataStore.get()
        assert store.has_pair(GIBS_LAU, WPLS) is True

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pair_registry.json")),
        reason="pair_registry.json not found",
    )
    def test_has_pair_false_nonsense(self):
        """has_pair() returns False for nonsense addresses."""
        store = DataStore.get()
        fake_a = "0x" + "11" * 20
        fake_b = "0x" + "22" * 20
        assert store.has_pair(fake_a, fake_b) is False

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pair_registry.json")),
        reason="pair_registry.json not found",
    )
    def test_dual_dex_tokens(self):
        """dual_dex_tokens() returns tokens with pairs on both V1 and V2."""
        store = DataStore.get()
        dual = store.dual_dex_tokens(base_token=WPLS)
        assert isinstance(dual, list)
        # We expect at least some dual-DEX tokens from the 1,276 pair registry
        if dual:
            addr, sym, v1_pair, v2_pair = dual[0]
            assert addr.startswith("0x")
            assert v1_pair.startswith("0x")
            assert v2_pair.startswith("0x")
            assert isinstance(sym, str)

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pair_registry.json")),
        reason="pair_registry.json not found",
    )
    def test_pairs_for_token(self):
        """pairs_for_token() returns edges for WPLS."""
        store = DataStore.get()
        pairs = store.pairs_for_token(WPLS)
        assert isinstance(pairs, list)
        assert len(pairs) > 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "token_master.json")),
        reason="token_master.json not found",
    )
    def test_token_symbol(self):
        """token_symbol() returns a symbol for known tokens."""
        store = DataStore.get()
        sym = store.token_symbol(WPLS)
        assert isinstance(sym, str)
        assert len(sym) > 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "token_master.json")),
        reason="token_master.json not found",
    )
    def test_all_tokens(self):
        """all_tokens() returns a dict with 700+ entries."""
        store = DataStore.get()
        tokens = store.all_tokens()
        assert isinstance(tokens, dict)
        assert len(tokens) > 700

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "recon_results.json")),
        reason="recon_results.json not found",
    )
    def test_recon_data_loads(self):
        """recon_data() loads the recon file."""
        store = DataStore.get()
        recon = store.recon_data()
        assert isinstance(recon, dict)
        assert "results" in recon
        assert len(recon["results"]) > 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "v2_federal_tokens.json")),
        reason="v2_federal_tokens.json not found",
    )
    def test_v2_federal_tokens(self):
        """v2_federal_tokens() returns 14 tokens."""
        store = DataStore.get()
        tokens = store.v2_federal_tokens()
        assert isinstance(tokens, list)
        assert len(tokens) == 14

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "v2_federal_tokens.json")),
        reason="v2_federal_tokens.json not found",
    )
    def test_debenture_tokens(self):
        """debenture_tokens() returns only Debenture=true tokens."""
        store = DataStore.get()
        deb = store.debenture_tokens()
        assert isinstance(deb, list)
        for tok in deb:
            assert tok.get("debenture") is True

    def test_invalidate_forces_reload(self):
        """invalidate() resets internal caches."""
        store = DataStore.get()
        # Load something first
        store._token_master = {"test": "data"}
        store._recon = {"test": "data"}
        store._v2_federal = [{"test": "data"}]

        store.invalidate("all")

        assert store._token_master is None
        assert store._recon is None
        assert store._v2_federal is None
        assert store._pair_graph is None

    def test_invalidate_selective(self):
        """invalidate('pairs') only resets pair graph."""
        store = DataStore.get()
        store._token_master = {"test": "data"}
        store._pair_graph = "dummy"
        store._pair_graph_ts = 999

        store.invalidate("pairs")

        assert store._pair_graph is None
        assert store._pair_graph_ts == 0
        assert store._token_master == {"test": "data"}  # untouched

    def test_missing_file_returns_empty(self):
        """DataStore handles missing files gracefully."""
        store = DataStore.get()
        # Force a non-existent path scenario by invalidating and using empty
        store._v2_federal = None

        # Even if file doesn't exist, should not crash
        tokens = store.v2_federal_tokens()
        assert isinstance(tokens, list)

    def test_lookup_pair_empty_graph(self):
        """lookup_pair returns None when no graph is loaded."""
        store = DataStore.get()
        store._pair_graph = None
        # If pair_registry.json exists, pair_graph() will load it
        # So test with nonsense addresses instead
        result = store.lookup_pair("0x" + "aa" * 20, "0x" + "bb" * 20)
        # Either None (no graph) or None (not found) — both acceptable
        assert result is None

    # ── PulseX Dual-DEX Token List ────────────────────────────────────

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pulsex_dual_dex_tokens.json")),
        reason="pulsex_dual_dex_tokens.json not found",
    )
    def test_pulsex_dual_dex_loads(self):
        """Verify pulsex_dual_dex_tokens.json loads and filters correctly."""
        store = DataStore.get()
        all_tokens = store.pulsex_dual_dex()
        assert len(all_tokens) > 0, "pulsex_dual_dex should have tokens"

        # Filter by TVL
        big = store.pulsex_dual_dex(min_tvl_pls=1_000_000)
        assert len(big) < len(all_tokens)

        # Verify structure
        tok = all_tokens[0]
        assert "address" in tok
        assert "v1_pair" in tok
        assert "v2_pair" in tok
        assert "spread_bps" in tok

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pulsex_dual_dex_tokens.json")),
        reason="pulsex_dual_dex_tokens.json not found",
    )
    def test_pulsex_dual_dex_spread_filter(self):
        """Verify spread filter reduces the result set."""
        store = DataStore.get()
        all_tokens = store.pulsex_dual_dex()
        filtered = store.pulsex_dual_dex(min_spread_bps=100)
        assert len(filtered) <= len(all_tokens)

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(_DATA_DIR, "pulsex_dual_dex_tokens.json")),
        reason="pulsex_dual_dex_tokens.json not found",
    )
    def test_pulsex_dual_dex_cached(self):
        """Verify pulsex_dual_dex caches after first load."""
        store = DataStore.get()
        _ = store.pulsex_dual_dex()
        assert store._pulsex_dual is not None
        cached_ref = store._pulsex_dual
        _ = store.pulsex_dual_dex()
        assert store._pulsex_dual is cached_ref  # same object

    def test_invalidate_pulsex(self):
        """invalidate('pulsex') resets pulsex cache."""
        store = DataStore.get()
        store._pulsex_dual = [{"test": "data"}]
        store.invalidate("pulsex")
        assert store._pulsex_dual is None

    def test_invalidate_all_includes_pulsex(self):
        """invalidate('all') also resets pulsex cache."""
        store = DataStore.get()
        store._pulsex_dual = [{"test": "data"}]
        store.invalidate("all")
        assert store._pulsex_dual is None
