"""
Tests for Engine 5 (Treasury Sniper) and Engine 6 (Spine Runner).
Pure unit tests — no chain interaction, no Anvil required.

Run:
  python3 scripts/Joystick/tests/test_engines_5_6.py
"""
import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# We need to mock the wallet module before it tries to load a real key.
# wallet.py runs _load_account() at module level which validates the private key.
# Mock the entire wallet module's account loading to avoid this.
os.environ.setdefault("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
os.environ.setdefault("PULSECHAIN_RPC", "http://127.0.0.1:8545")
os.environ.setdefault("PULSECHAIN_READ_RPC", "http://127.0.0.1:8545")
# Remove DYSNOMIA_PRIVATE_KEY if set (e.g. by conftest) — let wallet.py fall through to read-only mode
os.environ.pop("DYSNOMIA_PRIVATE_KEY", None)

# Force reimport of wallet if it was already loaded with wrong key
if "scripts.Joystick.core.wallet" in sys.modules:
    del sys.modules["scripts.Joystick.core.wallet"]
if "scripts.Joystick.core.executor" in sys.modules:
    del sys.modules["scripts.Joystick.core.executor"]

from scripts.Joystick.engines.treasury_sniper import TreasurySniperEngine, TreasuryTarget
from scripts.Joystick.engines.spine_runner import SpineRunnerEngine, Spine, BATCH_ITERATIONS
from scripts.Joystick.engines.base import EngineResult


def _make_recon_file(targets: dict) -> str:
    """Write a temporary recon_results.json and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump({"results": targets}, f)
    return path


class TestTreasurySniperUnit(unittest.TestCase):

    def setUp(self):
        self.e5 = TreasurySniperEngine()

    def test_import(self):
        self.assertIsNotNone(self.e5)

    def test_name(self):
        self.assertEqual(self.e5.name, "TreasurySniper")

    def test_is_ready_no_recon(self):
        """Without recon file, should not be ready."""
        self.e5._recon_path = "/tmp/nonexistent_recon_12345.json"
        self.assertFalse(self.e5.is_ready())

    @patch("scripts.Joystick.engines.treasury_sniper.w3_read")
    def test_simulate_no_targets(self, mock_w3):
        """With no targets, simulate returns (0,0)."""
        mock_w3.eth.gas_price = 100 * 10**9
        self.e5._targets = []
        self.e5._last_load = float('inf')
        profit, gas = self.e5.simulate()
        self.assertEqual(profit, 0)
        self.assertEqual(gas, 0)

    @patch("scripts.Joystick.engines.treasury_sniper.w3_read")
    def test_pick_best_batch_respects_claimed(self, mock_w3):
        """Already-claimed tokens should not appear in batch."""
        mock_w3.eth.gas_price = 100 * 10**9
        addr = "0x" + "de" * 20
        self.e5._targets = [TreasuryTarget(
            label="TEST", address=addr,
            backing_asset="0x" + "01" * 20,
            self_balance=int(1000e18), parent_balance=0,
            pls_per_token=1e15, parent_pls=1e15,
            estimated_pls=1000.0
        )]
        self.e5._claimed = {addr.lower()}
        self.e5._last_load = float('inf')
        batch = self.e5._pick_best_batch()
        self.assertEqual(len(batch), 0)

    def test_refresh_targets_from_file(self):
        """Verify targets are loaded from recon data."""
        addr = "0x" + "aa" * 20
        parent = "0x" + "bb" * 20
        recon = {
            "results": {
                addr: {
                    "label": "TESTTOKEN",
                    "chain_data": {
                        "selfBalance": int(10000e18),
                        "parentBalance": int(5000e18),
                        "pls_per_token": int(1e18),
                        "parent": parent,
                        "decimals": 18,
                    }
                }
            }
        }
        self.e5._last_load = 0
        with patch("scripts.Joystick.oracle.data_store.DataStore") as mock_ds_cls:
            mock_ds = MagicMock()
            mock_ds_cls.get.return_value = mock_ds
            mock_ds.recon_data.return_value = recon
            self.e5._refresh_targets()
        self.assertEqual(len(self.e5._targets), 1)
        self.assertEqual(self.e5._targets[0].label, "TESTTOKEN")

    def test_status_line_returns_string(self):
        self.e5._last_load = float('inf')
        line = self.e5.status_line()
        self.assertIn("TreasurySniper", line)

    def test_circuit_breaker(self):
        """After MAX_FAILURES, engine should be disabled."""
        for _ in range(self.e5.MAX_FAILURES):
            self.e5.record_failure()
        self.assertTrue(self.e5.is_disabled())

    def test_record_success_resets(self):
        self.e5.failure_count = 2
        self.e5.record_success()
        self.assertEqual(self.e5.failure_count, 0)


class TestSpineRunnerUnit(unittest.TestCase):

    def setUp(self):
        self.e6 = SpineRunnerEngine()

    def test_import(self):
        self.assertIsNotNone(self.e6)

    def test_name(self):
        self.assertEqual(self.e6.name, "SpineRunner")

    def test_batch_iterations_constant(self):
        self.assertEqual(BATCH_ITERATIONS, 20)

    def test_inactive_spine_not_picked(self):
        """Inactive spine should not be returned by _pick_best_spine."""
        self.e6._spines = [Spine(
            label="DEAD", child="0x" + "01" * 20, parent="0x" + "02" * 20,
            spend_token="0x" + "03" * 20, pls_per_child=1e15, active=False
        )]
        self.e6._last_load = float('inf')
        result = self.e6._pick_best_spine()
        self.assertIsNone(result)

    def test_zero_pls_spine_not_picked(self):
        """Spine with pls_per_child=0 should not be picked."""
        self.e6._spines = [Spine(
            label="NOPRICE", child="0x" + "01" * 20, parent="0x" + "02" * 20,
            spend_token="0x" + "03" * 20, pls_per_child=0, active=True
        )]
        self.e6._last_load = float('inf')
        result = self.e6._pick_best_spine()
        self.assertIsNone(result)

    def test_status_line_returns_string(self):
        self.e6._last_load = float('inf')
        line = self.e6.status_line()
        self.assertIn("SpineRunner", line)

    def test_refresh_loads_ozzy_fallback(self):
        """With no v2_federal_tokens.json and no cache, should load OZZY fallback."""
        self.e6._v2fed_path = "/tmp/nonexistent_v2_12345.json"
        self.e6._last_load = 0
        # Mock discovery and cache paths to return empty so we reach the OZZY fallback
        with patch.object(self.e6, "_load_cached_spine_pairs", return_value=[]):
            with patch.object(self.e6, "_discover_spine_pairs", return_value=[]):
                with patch.object(self.e6, "_load_spines_from_recon", return_value=[]):
                    self.e6._refresh_spines()
        self.assertEqual(len(self.e6._spines), 1)
        self.assertEqual(self.e6._spines[0].label, "OZZY")
        self.assertFalse(self.e6._spines[0].active)

    def test_circuit_breaker(self):
        for _ in range(self.e6.MAX_FAILURES):
            self.e6.record_failure()
        self.assertTrue(self.e6.is_disabled())


class TestEngineResultContract(unittest.TestCase):
    """Verify EngineResult works as expected for both engines."""

    def test_success_result(self):
        r = EngineResult(success=True, profit_wei=int(100e18), gas_wei=int(5e18),
                         tx_hashes=["0xabc"], notes="test")
        self.assertTrue(r.success)
        self.assertAlmostEqual(r.profit_pls, 100.0)
        self.assertAlmostEqual(r.gas_pls, 5.0)
        self.assertAlmostEqual(r.net_pls, 95.0)

    def test_failure_result(self):
        r = EngineResult(success=False, profit_wei=0, gas_wei=0, notes="reverted")
        self.assertFalse(r.success)
        self.assertEqual(r.net_pls, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
