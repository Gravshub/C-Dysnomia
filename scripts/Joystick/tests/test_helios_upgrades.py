"""
Tests for the 5 Helios PingPong intelligence upgrades:
  1. SupplyOracle — supply inflation tracking
  2. E6 TreasurySniperEngine — cross-treasury sell routing
  3. E7 SpineRunnerEngine — dynamic spine pair discovery
  4. GasOracle — mempool gas price sampling
  5. Auto-ABI — BlockScout fetch + load_contract_dynamic

Pure unit tests — no chain interaction, no Anvil required.

Run:
  PYTHONPATH=/opt/joystick/repo python -m pytest scripts/Joystick/tests/test_helios_upgrades.py -v
  # or standalone:
  python scripts/Joystick/tests/test_helios_upgrades.py
"""
import sys
import os
import json
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
from decimal import Decimal

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Environment setup before imports (same pattern as test_engines_5_6.py)
os.environ.setdefault("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
os.environ.setdefault("PULSECHAIN_RPC", "http://127.0.0.1:8545")
os.environ.setdefault("PULSECHAIN_READ_RPC", "http://127.0.0.1:8545")
os.environ.pop("DYSNOMIA_PRIVATE_KEY", None)

if "scripts.Joystick.core.wallet" in sys.modules:
    del sys.modules["scripts.Joystick.core.wallet"]
if "scripts.Joystick.core.executor" in sys.modules:
    del sys.modules["scripts.Joystick.core.executor"]

from scripts.Joystick.oracle.supply_oracle import SupplyOracle
from scripts.Joystick.engines.treasury_sniper import TreasurySniperEngine, TreasuryTarget
from scripts.Joystick.engines.spine_runner import SpineRunnerEngine, Spine
from scripts.Joystick.core.gas_oracle import GasOracle
from scripts.Joystick.engines.base import EngineResult

# Addresses used throughout tests
ADDR_A = "0x" + "aa" * 20
ADDR_B = "0x" + "bb" * 20
ADDR_C = "0x" + "cc" * 20
ADDR_ZERO = "0x" + "00" * 40
WPLS = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"


# ═══════════════════════════════════════════════════════════════════════════
# 1. SupplyOracle Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSupplyOracleUnit(unittest.TestCase):
    """Tests for oracle/supply_oracle.py — supply inflation tracking."""

    def setUp(self):
        self.oracle = SupplyOracle()
        # Prevent real file I/O
        self.oracle._loaded = True

    @patch("scripts.Joystick.oracle.supply_oracle.multicall")
    @patch("scripts.Joystick.oracle.supply_oracle.erc20")
    def test_first_run_no_prior_snapshot(self, mock_erc20, mock_multicall):
        """First update() should populate snapshots but not flag inflation (no old data)."""
        mock_erc20.return_value = MagicMock()
        mock_multicall.return_value = [1000 * 10**18, 2000 * 10**18]

        self.oracle._token_list = [
            {"address": ADDR_A.lower(), "symbol": "TOKA"},
            {"address": ADDR_B.lower(), "symbol": "TOKB"},
        ]
        self.oracle._snapshots = {}  # no prior data

        self.oracle.update()

        self.assertEqual(len(self.oracle._snapshots), 2)
        self.assertEqual(len(self.oracle.get_inflated_tokens()), 0)

    @patch("scripts.Joystick.oracle.supply_oracle.multicall")
    @patch("scripts.Joystick.oracle.supply_oracle.erc20")
    def test_inflation_detected(self, mock_erc20, mock_multicall):
        """2% growth (above 1% threshold) should be flagged."""
        mock_erc20.return_value = MagicMock()
        old_supply = 1000 * 10**18
        new_supply = 1020 * 10**18  # +2%
        mock_multicall.return_value = [new_supply]

        self.oracle._token_list = [{"address": ADDR_A.lower(), "symbol": "TOKA"}]
        self.oracle._snapshots = {
            ADDR_A.lower(): {"supply": old_supply, "timestamp": time.time() - 60},
        }

        self.oracle.update()

        inflated = self.oracle.get_inflated_tokens()
        self.assertEqual(len(inflated), 1)
        self.assertAlmostEqual(inflated[0]["growth_pct"], 2.0, places=1)
        self.assertEqual(inflated[0]["symbol"], "TOKA")

    @patch("scripts.Joystick.oracle.supply_oracle.multicall")
    @patch("scripts.Joystick.oracle.supply_oracle.erc20")
    def test_below_threshold_not_flagged(self, mock_erc20, mock_multicall):
        """0.5% growth (below 1% threshold) should NOT be flagged."""
        mock_erc20.return_value = MagicMock()
        old_supply = 1000 * 10**18
        new_supply = 1005 * 10**18  # +0.5%
        mock_multicall.return_value = [new_supply]

        self.oracle._token_list = [{"address": ADDR_A.lower(), "symbol": "TOKA"}]
        self.oracle._snapshots = {
            ADDR_A.lower(): {"supply": old_supply, "timestamp": time.time() - 60},
        }

        self.oracle.update()

        self.assertEqual(len(self.oracle.get_inflated_tokens()), 0)

    @patch("scripts.Joystick.oracle.supply_oracle.multicall")
    @patch("scripts.Joystick.oracle.supply_oracle.erc20")
    def test_cooldown_enforcement(self, mock_erc20, mock_multicall):
        """Token flagged recently should NOT be re-flagged within cooldown."""
        mock_erc20.return_value = MagicMock()
        new_supply = 1500 * 10**18  # +50% — massive growth
        mock_multicall.return_value = [new_supply]

        self.oracle._token_list = [{"address": ADDR_A.lower(), "symbol": "TOKA"}]
        self.oracle._snapshots = {
            ADDR_A.lower(): {"supply": 1000 * 10**18, "timestamp": time.time() - 60},
        }
        # Set cooldown: flagged 10 seconds ago (within 300s window)
        self.oracle._cooldowns = {ADDR_A.lower(): time.time() - 10}

        self.oracle.update()

        self.assertEqual(len(self.oracle.get_inflated_tokens()), 0)

    @patch("scripts.Joystick.oracle.supply_oracle.multicall")
    @patch("scripts.Joystick.oracle.supply_oracle.erc20")
    def test_zero_old_supply_no_crash(self, mock_erc20, mock_multicall):
        """Old supply=0 should not cause ZeroDivisionError."""
        mock_erc20.return_value = MagicMock()
        mock_multicall.return_value = [100 * 10**18]

        self.oracle._token_list = [{"address": ADDR_A.lower(), "symbol": "TOKA"}]
        self.oracle._snapshots = {
            ADDR_A.lower(): {"supply": 0, "timestamp": time.time() - 60},
        }

        # Should not raise
        self.oracle.update()
        self.assertEqual(len(self.oracle.get_inflated_tokens()), 0)

    def test_load_token_list_dedup(self):
        """Duplicate addresses from V2 Federal + watchlist should be deduplicated."""
        self.oracle._token_list = []  # reset

        with patch("scripts.Joystick.oracle.data_store.DataStore") as mock_ds_cls:
            mock_ds = MagicMock()
            mock_ds_cls.get.return_value = mock_ds
            mock_ds.v2_federal_tokens.return_value = [
                {"address": ADDR_A, "symbol": "TOKA"},
                {"address": ADDR_B, "symbol": "TOKB"},
            ]
            # Watchlist has ADDR_A again (duplicate)
            with patch("scripts.Joystick.oracle.supply_oracle.os.path.exists", return_value=True):
                with patch("builtins.open", unittest.mock.mock_open(
                    read_data=json.dumps([{"address": ADDR_A, "symbol": "DUPE"}, {"address": ADDR_C, "symbol": "TOKC"}])
                )):
                    tokens = self.oracle._load_token_list()

        self.assertEqual(len(tokens), 3)  # A, B, C — no duplicate A
        addrs = [t["address"] for t in tokens]
        self.assertEqual(len(set(addrs)), 3)

    def test_status_dict(self):
        """status() should return dict with expected keys."""
        self.oracle._token_list = [{"address": ADDR_A.lower(), "symbol": "X"}]
        s = self.oracle.status()
        self.assertIn("tracked", s)
        self.assertIn("snapshots", s)
        self.assertIn("inflated", s)
        self.assertIn("cooldowns_active", s)


# ═══════════════════════════════════════════════════════════════════════════
# 2. E6 TreasurySniperEngine — Cross-Treasury Sell Route Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTreasurySniperSellRoute(unittest.TestCase):
    """Tests for _find_best_sell_route() in treasury_sniper.py."""

    def setUp(self):
        self.engine = TreasurySniperEngine()
        self.engine._last_load = float("inf")  # skip recon loading
        # Populate targets for cross-treasury candidate scanning
        self.engine._targets = [
            TreasuryTarget(
                label="INTER", address=ADDR_C,
                backing_asset=ADDR_B, self_balance=int(1e18),
                parent_balance=0, pls_per_token=1.0, parent_pls=1.0,
                estimated_pls=100.0,
            ),
        ]

    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out_v2")
    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out")
    def test_direct_v1_best(self, mock_v1, mock_v2):
        """V1 yields more than V2 — should pick V1 direct."""
        amount = 100 * 10**18
        mock_v1.return_value = [amount, 500 * 10**18]  # V1 = 500 PLS
        mock_v2.return_value = [amount, 400 * 10**18]  # V2 = 400 PLS

        route = self.engine._find_best_sell_route(ADDR_A, amount)

        self.assertEqual(route["mode"], "direct")
        self.assertEqual(route["router"], "V1")
        self.assertEqual(route["expected_pls"], 500 * 10**18)

    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out_v2")
    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out")
    def test_direct_v2_best(self, mock_v1, mock_v2):
        """V2 yields more than V1 — should pick V2 direct."""
        amount = 100 * 10**18
        mock_v1.return_value = [amount, 400 * 10**18]
        mock_v2.return_value = [amount, 600 * 10**18]

        route = self.engine._find_best_sell_route(ADDR_A, amount)

        self.assertEqual(route["mode"], "direct")
        self.assertEqual(route["router"], "V2")
        self.assertEqual(route["expected_pls"], 600 * 10**18)

    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out_v2")
    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out")
    def test_no_liquidity(self, mock_v1, mock_v2):
        """Both routers return None — no DEX liquidity."""
        mock_v1.return_value = None
        mock_v2.return_value = None

        route = self.engine._find_best_sell_route(ADDR_A, 100 * 10**18)

        self.assertEqual(route["expected_pls"], 0)
        self.assertEqual(route["mode"], "direct")

    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out_v2")
    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out")
    def test_cross_treasury_above_threshold(self, mock_v1, mock_v2):
        """Cross-treasury yields 20% more than direct — should use cross route."""
        amount = 100 * 10**18
        direct_pls = 100 * 10**18
        cross_hop1_out = 50 * 10**18
        cross_hop2_out = 120 * 10**18  # 20% improvement over 100

        def v1_side_effect(amt, path):
            if len(path) == 2 and path[1].lower() == WPLS.lower():
                # Direct: parent -> WPLS
                if path[0].lower() != ADDR_C.lower():
                    return [amt, direct_pls]
                # Hop2: intermediate -> WPLS
                return [amt, cross_hop2_out]
            # Hop1: parent -> intermediate
            return [amt, cross_hop1_out]

        mock_v1.side_effect = v1_side_effect
        mock_v2.return_value = None  # V2 not available

        route = self.engine._find_best_sell_route(ADDR_A, amount)

        self.assertEqual(route["mode"], "cross_treasury")
        self.assertEqual(route["expected_pls"], cross_hop2_out)

    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out_v2")
    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out")
    def test_cross_treasury_below_threshold(self, mock_v1, mock_v2):
        """Cross-treasury yields only 5% more — below 10% threshold, stays direct."""
        amount = 100 * 10**18
        direct_pls = 100 * 10**18
        cross_hop2_out = 105 * 10**18  # only 5% improvement

        def v1_side_effect(amt, path):
            if len(path) == 2 and path[1].lower() == WPLS.lower():
                if path[0].lower() != ADDR_C.lower():
                    return [amt, direct_pls]
                return [amt, cross_hop2_out]
            return [amt, 50 * 10**18]

        mock_v1.side_effect = v1_side_effect
        mock_v2.return_value = None

        route = self.engine._find_best_sell_route(ADDR_A, amount)

        self.assertEqual(route["mode"], "direct")

    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out_v2")
    @patch("scripts.Joystick.engines.treasury_sniper.get_amounts_out")
    def test_cross_treasury_hop1_zero(self, mock_v1, mock_v2):
        """First hop returns 0 — cross path should be skipped."""
        amount = 100 * 10**18

        def v1_side_effect(amt, path):
            if len(path) == 2 and path[1].lower() == WPLS.lower():
                return [amt, 100 * 10**18]
            return [amt, 0]  # hop1 returns 0

        mock_v1.side_effect = v1_side_effect
        mock_v2.return_value = None

        route = self.engine._find_best_sell_route(ADDR_A, amount)

        self.assertEqual(route["mode"], "direct")


# ═══════════════════════════════════════════════════════════════════════════
# 3. E7 SpineRunnerEngine — Dynamic Spine Discovery Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSpineRunnerDiscovery(unittest.TestCase):
    """Tests for _discover_spine_pairs(), cache load/save in spine_runner.py."""

    def setUp(self):
        self.engine = SpineRunnerEngine()
        self.engine._last_load = float("inf")  # prevent auto-refresh

    @patch("scripts.Joystick.oracle.price.get_amounts_out_v2")
    @patch("scripts.Joystick.oracle.price.get_amounts_out")
    @patch("scripts.Joystick.engines.spine_runner.multicall")
    @patch("scripts.Joystick.engines.spine_runner._treasury_contract")
    def test_discover_normal(self, mock_tc, mock_multicall, mock_v1, mock_v2):
        """2 Deb=True tokens should produce 2 spine pairs (each paired with the other)."""
        with patch("scripts.Joystick.oracle.data_store.DataStore") as mock_ds_cls:
            mock_ds = MagicMock()
            mock_ds_cls.get.return_value = mock_ds
            mock_ds.v2_federal_tokens.return_value = [
                {"address": ADDR_A, "symbol": "TOKA"},
                {"address": ADDR_B, "symbol": "TOKB"},
                {"address": ADDR_C, "symbol": "TOKC"},
            ]
            mock_tc.return_value = MagicMock()

            # Multicall: [Deb_A, Parent_A, Deb_B, Parent_B, Deb_C, Parent_C]
            parent_a = "0x" + "11" * 20
            parent_b = "0x" + "22" * 20
            mock_multicall.return_value = [
                True, parent_a,    # TOKA: Deb=True
                True, parent_b,    # TOKB: Deb=True
                False, ADDR_ZERO,  # TOKC: Deb=False
            ]

            # DEX price: return some value
            mock_v2.return_value = [10**18, 50 * 10**18]
            mock_v1.return_value = None

            spines = self.engine._discover_spine_pairs()

        # 2 Deb=True tokens, each paired with the other = 2 pairs
        self.assertEqual(len(spines), 2)
        labels = {s.label for s in spines}
        self.assertEqual(labels, {"TOKA", "TOKB"})

    @patch("scripts.Joystick.engines.spine_runner.multicall")
    @patch("scripts.Joystick.engines.spine_runner._treasury_contract")
    def test_discover_no_debenture(self, mock_tc, mock_multicall):
        """All Deb=False should return empty list."""
        with patch("scripts.Joystick.oracle.data_store.DataStore") as mock_ds_cls:
            mock_ds = MagicMock()
            mock_ds_cls.get.return_value = mock_ds
            mock_ds.v2_federal_tokens.return_value = [
                {"address": ADDR_A, "symbol": "TOKA"},
            ]
            mock_tc.return_value = MagicMock()
            mock_multicall.return_value = [False, "0x" + "11" * 20]

            spines = self.engine._discover_spine_pairs()

        self.assertEqual(len(spines), 0)

    @patch("scripts.Joystick.engines.spine_runner.multicall")
    @patch("scripts.Joystick.engines.spine_runner._treasury_contract")
    def test_discover_zero_parent(self, mock_tc, mock_multicall):
        """Deb=True but Parent=0x0000...0 should be filtered out."""
        with patch("scripts.Joystick.oracle.data_store.DataStore") as mock_ds_cls:
            mock_ds = MagicMock()
            mock_ds_cls.get.return_value = mock_ds
            mock_ds.v2_federal_tokens.return_value = [
                {"address": ADDR_A, "symbol": "TOKA"},
            ]
            mock_tc.return_value = MagicMock()
            mock_multicall.return_value = [True, "0x" + "00" * 20]

            spines = self.engine._discover_spine_pairs()

        self.assertEqual(len(spines), 0)

    def test_cache_load_fresh(self):
        """Fresh cache file should load spines without triggering on-chain discovery."""
        cache_data = {
            "timestamp": time.time() - 10,  # 10 seconds ago (within 1800s TTL)
            "pairs": [{
                "label": "OZZY",
                "child": "0x52b4F56d87765E7A9567E35bea97de13C3386554",
                "parent": "0xaAE18Cd46C45d343BbA1eab46716B4D69d799734",
                "spend_token": "0x52b4F56d87765E7A9567E35bea97de13C3386554",
                "pls_per_child": 0.001,
                "active": True,
            }],
        }

        with patch("scripts.Joystick.engines.spine_runner.os.path.exists", return_value=True):
            with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(cache_data))):
                spines = self.engine._load_cached_spine_pairs()

        self.assertEqual(len(spines), 1)
        self.assertEqual(spines[0].label, "OZZY")

    def test_cache_stale(self):
        """Stale cache (old timestamp) should return empty list."""
        cache_data = {
            "timestamp": time.time() - 3600,  # 1 hour ago (beyond 1800s TTL)
            "pairs": [{"label": "OLD", "child": ADDR_A, "parent": ADDR_B,
                        "spend_token": ADDR_A, "pls_per_child": 0.0, "active": True}],
        }

        with patch("scripts.Joystick.engines.spine_runner.os.path.exists", return_value=True):
            with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(cache_data))):
                spines = self.engine._load_cached_spine_pairs()

        self.assertEqual(len(spines), 0)

    @patch("scripts.Joystick.oracle.price.get_amounts_out_v2")
    @patch("scripts.Joystick.oracle.price.get_amounts_out")
    @patch("scripts.Joystick.engines.spine_runner.multicall")
    @patch("scripts.Joystick.engines.spine_runner._treasury_contract")
    def test_force_rediscovery(self, mock_tc, mock_multicall, mock_v1, mock_v2):
        """_force_rediscovery=True should trigger discovery even with cached data."""
        self.engine._force_rediscovery = True
        self.engine._last_load = 0
        self.engine._last_discovery = 0

        with patch("scripts.Joystick.oracle.data_store.DataStore") as mock_ds_cls:
            mock_ds = MagicMock()
            mock_ds_cls.get.return_value = mock_ds
            # Need 2 Deb=True tokens so they can pair with each other
            mock_ds.v2_federal_tokens.return_value = [
                {"address": ADDR_A, "symbol": "TOKA"},
                {"address": ADDR_B, "symbol": "TOKB"},
            ]
            mock_tc.return_value = MagicMock()
            parent = "0x" + "11" * 20
            mock_multicall.return_value = [True, parent, True, parent]
            mock_v2.return_value = [10**18, 10 * 10**18]
            mock_v1.return_value = None

            # Mock cache loading to return empty (stale)
            with patch.object(self.engine, "_load_cached_spine_pairs", return_value=[]):
                with patch.object(self.engine, "_save_spine_pairs"):
                    self.engine._refresh_spines()

        # Discovery produced results, so _force_rediscovery should be reset
        self.assertFalse(self.engine._force_rediscovery)


# ═══════════════════════════════════════════════════════════════════════════
# 4. GasOracle — Mempool Gas Price Sampling Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGasOracleMempool(unittest.TestCase):
    """Tests for mempool gas sampling in gas_oracle.py."""

    def setUp(self):
        self.oracle = GasOracle()

    def _make_block(self, gas_prices):
        """Create a mock pending block with TXs at given gas prices."""
        txs = [{"gasPrice": gp, "hash": f"0x{i:064x}"} for i, gp in enumerate(gas_prices)]
        return {"transactions": txs}

    @patch("scripts.Joystick.core.gas_oracle.w3_read")
    def test_percentiles_10_txs(self, mock_w3):
        """Correct percentile computation from 10 sorted TXs."""
        prices = [i * 10**9 for i in range(1, 11)]  # 1-10 Beats in wei
        mock_w3.eth.get_block.return_value = self._make_block(prices)

        result = self.oracle._sample_pending_block()

        self.assertIsNotNone(result)
        self.assertEqual(result["tx_count"], 10)
        # p50 of [1..10]*1e9: index min(5, 9) = 5 → prices[5] = 6*1e9
        self.assertEqual(result["p50"], 6 * 10**9)
        # p10: index min(1, 9) = 1 → prices[1] = 2*1e9
        self.assertEqual(result["p10"], 2 * 10**9)
        # p90: index min(9, 9) = 9 → prices[9] = 10*1e9
        self.assertEqual(result["p90"], 10 * 10**9)

    @patch("scripts.Joystick.core.gas_oracle.w3_read")
    def test_rpc_unsupported(self, mock_w3):
        """RPC that doesn't support pending block should return None."""
        mock_w3.eth.get_block.side_effect = Exception("Method not supported")

        result = self.oracle._sample_pending_block()
        self.assertIsNone(result)

    @patch("scripts.Joystick.core.gas_oracle.w3_read")
    def test_empty_txs(self, mock_w3):
        """Empty TX list should return None."""
        mock_w3.eth.get_block.return_value = {"transactions": []}

        result = self.oracle._sample_pending_block()
        self.assertIsNone(result)

    @patch("scripts.Joystick.core.gas_oracle.w3_read")
    def test_single_tx(self, mock_w3):
        """Single TX — all percentiles should equal that TX's price."""
        price = 500_000 * 10**9  # 500K Beats
        mock_w3.eth.get_block.return_value = self._make_block([price])

        result = self.oracle._sample_pending_block()

        self.assertIsNotNone(result)
        self.assertEqual(result["tx_count"], 1)
        for key in ["p10", "p25", "p50", "p70", "p80", "p90"]:
            self.assertEqual(result[key], price)

    @patch("scripts.Joystick.core.gas_oracle.w3_read")
    def test_eip1559_maxfeepergas(self, mock_w3):
        """Should prefer maxFeePerGas over gasPrice for EIP-1559 TXs."""
        txs = [
            {"maxFeePerGas": 200 * 10**9, "gasPrice": 100 * 10**9, "hash": "0x01"},
            {"maxFeePerGas": 300 * 10**9, "gasPrice": 150 * 10**9, "hash": "0x02"},
        ]
        mock_w3.eth.get_block.return_value = {"transactions": txs}

        result = self.oracle._sample_pending_block()

        self.assertIsNotNone(result)
        # Both TXs should use maxFeePerGas, not gasPrice
        self.assertGreaterEqual(result["p50"], 200 * 10**9)

    def test_mempool_speed_mapping(self):
        """mempool_price() should map speed names to correct percentiles."""
        self.oracle._mempool_data = {
            "p10": 10, "p25": 25, "p50": 50, "p70": 70, "p80": 80, "p90": 90,
            "tx_count": 100, "timestamp": time.time(),
        }

        self.assertEqual(self.oracle.mempool_price("slow"), 25)
        self.assertEqual(self.oracle.mempool_price("standard"), 50)
        self.assertEqual(self.oracle.mempool_price("fast"), 70)
        self.assertEqual(self.oracle.mempool_price("rapid"), 80)

    def test_recommended_gas_price_fallback(self):
        """recommended_gas_price: mempool p50 if available, else eth_gasPrice."""
        # With mempool data
        self.oracle._mempool_data = {
            "p50": 200, "p25": 100, "p70": 300, "p80": 400,
            "tx_count": 50, "timestamp": time.time(),
        }
        self.oracle._last_price = 500
        self.assertEqual(self.oracle.recommended_gas_price(), 200)

        # Without mempool data
        self.oracle._mempool_data = None
        self.assertEqual(self.oracle.recommended_gas_price(), 500)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Auto-ABI Fetch — BlockScout + load_contract_dynamic Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAutoABIFetch(unittest.TestCase):
    """Tests for fetch_abi_blockscout(), load_abi(), load_contract_dynamic() in chain.py."""

    def setUp(self):
        # Reset rate limit global between tests
        import scripts.Joystick.core.chain as chain_mod
        chain_mod._last_blockscout_fetch = 0.0

    @patch("scripts.Joystick.core.chain.time.sleep")
    @patch("scripts.Joystick.core.chain.time.time", return_value=100.0)
    @patch("scripts.Joystick.core.chain.requests.get")
    @patch("scripts.Joystick.core.chain.os.path.exists")
    def test_fetch_cached_exists(self, mock_exists, mock_get, mock_time, mock_sleep):
        """Cached ABI file should be returned without HTTP request."""
        from scripts.Joystick.core.chain import fetch_abi_blockscout

        mock_exists.return_value = True
        test_abi = [{"name": "balanceOf", "type": "function"}]

        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(test_abi))):
            result = fetch_abi_blockscout(ADDR_A)

        self.assertEqual(result, test_abi)
        mock_get.assert_not_called()

    @patch("scripts.Joystick.core.chain.time.sleep")
    @patch("scripts.Joystick.core.chain.time.time", return_value=100.0)
    @patch("scripts.Joystick.core.chain.requests.get")
    @patch("scripts.Joystick.core.chain.os.path.exists", return_value=False)
    def test_fetch_404_not_verified(self, mock_exists, mock_get, mock_time, mock_sleep):
        """404 response should return None (contract not verified)."""
        from scripts.Joystick.core.chain import fetch_abi_blockscout

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = Exception("404")
        mock_get.return_value = mock_resp

        result = fetch_abi_blockscout(ADDR_A)
        self.assertIsNone(result)

    @patch("scripts.Joystick.core.chain.os.replace")
    @patch("scripts.Joystick.core.chain.time.sleep")
    @patch("scripts.Joystick.core.chain.time.time", return_value=100.0)
    @patch("scripts.Joystick.core.chain.requests.get")
    @patch("scripts.Joystick.core.chain.os.path.exists", return_value=False)
    def test_fetch_success_caches(self, mock_exists, mock_get, mock_time, mock_sleep, mock_replace):
        """Successful fetch should cache ABI via atomic write."""
        from scripts.Joystick.core.chain import fetch_abi_blockscout

        test_abi = [{"name": "totalSupply", "type": "function"}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"abi": test_abi}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("builtins.open", unittest.mock.mock_open()):
            result = fetch_abi_blockscout(ADDR_A)

        self.assertEqual(result, test_abi)
        mock_replace.assert_called_once()  # Atomic write

    @patch("scripts.Joystick.core.chain.os.replace")
    @patch("scripts.Joystick.core.chain.time.sleep")
    @patch("scripts.Joystick.core.chain.time.time", return_value=100.0)
    @patch("scripts.Joystick.core.chain.requests.get")
    @patch("scripts.Joystick.core.chain.os.path.exists", return_value=False)
    def test_fetch_retry_on_error(self, mock_exists, mock_get, mock_time, mock_sleep, mock_replace):
        """Network errors should trigger retries with backoff."""
        import requests as req_lib
        from scripts.Joystick.core.chain import fetch_abi_blockscout

        test_abi = [{"name": "symbol", "type": "function"}]
        # First 2 fail, third succeeds
        mock_get.side_effect = [
            req_lib.RequestException("timeout"),
            req_lib.RequestException("connection reset"),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"abi": test_abi}),
                raise_for_status=MagicMock(),
            ),
        ]

        with patch("builtins.open", unittest.mock.mock_open()):
            result = fetch_abi_blockscout(ADDR_A)

        self.assertEqual(result, test_abi)
        self.assertEqual(mock_get.call_count, 3)

    @patch("scripts.Joystick.core.chain.time.sleep")
    @patch("scripts.Joystick.core.chain.time.time", return_value=100.0)
    @patch("scripts.Joystick.core.chain.requests.get")
    @patch("scripts.Joystick.core.chain.os.path.exists", return_value=False)
    def test_fetch_all_retries_fail(self, mock_exists, mock_get, mock_time, mock_sleep):
        """All 3 retries fail — should return None."""
        import requests as req_lib
        from scripts.Joystick.core.chain import fetch_abi_blockscout

        mock_get.side_effect = req_lib.RequestException("network down")

        result = fetch_abi_blockscout(ADDR_A)

        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 3)

    def test_load_abi_named_file(self):
        """Named ABI file (e.g., 'erc20') should load from disk, no BlockScout."""
        from scripts.Joystick.core.chain import load_abi

        # 'erc20' is a real file that exists
        result = load_abi("erc20")
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    @patch("scripts.Joystick.core.chain.w3_read")
    def test_load_contract_dynamic_erc20_fallback(self, mock_w3):
        """When no ABI is found, should fall back to ERC20_ABI."""
        from scripts.Joystick.core.chain import load_contract_dynamic, ERC20_ABI

        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract

        # Use a fake address that won't have a cached ABI
        with patch("scripts.Joystick.core.chain.load_abi", side_effect=FileNotFoundError("nope")):
            result = load_contract_dynamic("0x1234567890abcdef1234567890abcdef12345678")

        self.assertEqual(result, mock_contract)
        # Verify ERC20_ABI was used as fallback
        call_args = mock_w3.eth.contract.call_args
        self.assertEqual(call_args.kwargs.get("abi") or call_args[1].get("abi"), ERC20_ABI)


if __name__ == "__main__":
    unittest.main(verbosity=2)
