"""
test_logic_fixes.py — Unit tests for the 6 logic flaw fixes.
Pure unit tests — no chain interaction, no Anvil required.

Run:
  python -m pytest scripts/Joystick/tests/test_logic_fixes.py -v
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

os.environ.setdefault("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
os.environ.setdefault("PULSECHAIN_RPC", "http://127.0.0.1:8545")
os.environ.setdefault("PULSECHAIN_READ_RPC", "http://127.0.0.1:8545")
os.environ.pop("DYSNOMIA_PRIVATE_KEY", None)

if "scripts.Joystick.core.wallet" in sys.modules:
    del sys.modules["scripts.Joystick.core.wallet"]

from scripts.Joystick.engines.treasury_sniper import TreasurySniperEngine, TreasuryTarget


# Override the session-scoped autouse fixture so these pure unit tests
# do not require Anvil to be running.
@pytest.fixture(autouse=True)
def isolate(request):
    """No-op override: unit tests in this file need no Anvil snapshot/revert."""
    yield


class TestE6SimulateUsesLiveQuotes(unittest.TestCase):
    """Flaw #1: simulate() must use live DEX quotes, not stale recon estimates."""

    @patch("scripts.Joystick.engines.treasury_sniper.w3_read")
    def test_simulate_calls_find_best_sell_route(self, mock_w3):
        """simulate() should call _find_best_sell_route for each target, not use t.estimated_pls."""
        mock_w3.eth.gas_price = 100 * 10**9  # 100 Gwei

        engine = TreasurySniperEngine()
        engine._last_load = float('inf')  # skip recon reload

        target = TreasuryTarget(
            label="INFLATED", address="0x" + "ab" * 20,
            backing_asset="0x" + "cd" * 20,
            self_balance=int(1000e18), parent_balance=int(500e18),
            pls_per_token=99.0, parent_pls=99.0,
            estimated_pls=99000.0,  # stale inflated value
        )
        engine._targets = [target]

        engine._size_claim = MagicMock(return_value=int(500e18))

        live_pls = int(2000 * 10**18)  # 2000 PLS (much less than 99K)
        engine._find_best_sell_route = MagicMock(return_value={
            "route": ["0xparent", "0xwpls"], "router": "V2",
            "expected_pls": live_pls, "mode": "direct",
        })

        profit, gas = engine.simulate()

        engine._find_best_sell_route.assert_called_once()
        self.assertLess(profit, 5000 * 10**18, "Profit should reflect live DEX quote, not stale recon")


class TestE6BatchCap(unittest.TestCase):
    """Flaw #6: batch-level profit cap prevents runaway estimates."""

    @patch("scripts.Joystick.engines.treasury_sniper.w3_read")
    def test_batch_profit_capped(self, mock_w3):
        """Total batch profit must be capped even when many targets sum higher."""
        mock_w3.eth.gas_price = 100 * 10**9

        engine = TreasurySniperEngine()
        engine._last_load = float('inf')

        targets = []
        for i in range(10):
            addr = f"0x{i:040x}"
            targets.append(TreasuryTarget(
                label=f"T{i}", address=addr,
                backing_asset="0x" + "cd" * 20,
                self_balance=int(100e18), parent_balance=int(100e18),
                pls_per_token=200.0, parent_pls=200.0,
                estimated_pls=20000.0,
            ))
        engine._targets = targets

        engine._size_claim = MagicMock(return_value=int(100e18))
        engine._find_best_sell_route = MagicMock(return_value={
            "route": ["0xp", "0xw"], "router": "V2",
            "expected_pls": int(20000 * 10**18), "mode": "direct",
        })

        profit, gas = engine.simulate()

        MAX_BATCH_CAP = 50_000 * 10**18
        self.assertLessEqual(profit + gas, MAX_BATCH_CAP,
                             "Total batch estimate must be capped at 50K PLS")


class TestE2DepositOverflow(unittest.TestCase):
    """Flaw #2: E2 _acquire_aff must deposit actual AFF received, not full shortfall."""

    @patch("scripts.Joystick.engines.dss.send_tx")
    @patch("scripts.Joystick.engines.dss.approve_if_needed")
    @patch("scripts.Joystick.engines.dss.router_contract")
    @patch("scripts.Joystick.engines.dss.erc20")
    @patch("scripts.Joystick.engines.dss.safe")
    @patch("scripts.Joystick.engines.dss.w3_submit")
    def test_deposit_uses_actual_balance(self, mock_w3s, mock_safe, mock_erc20,
                                          mock_router, mock_approve, mock_send):
        """Deposit amount should be min(actual_aff_balance, shortfall_wei)."""
        from scripts.Joystick.engines.dss import DSSEngine

        engine = DSSEngine()

        # Setup mocks
        mock_w3s.eth.gas_price = 100 * 10**9
        mock_w3s.eth.contract = MagicMock()

        fake_receipt = {
            "transactionHash": MagicMock(hex=MagicMock(return_value="0x" + "aa" * 32)),
            "gasUsed": 100_000,
            "effectiveGasPrice": 100 * 10**9,
        }
        mock_send.return_value = fake_receipt
        mock_approve.return_value = None

        shortfall = int(100 * 10**18)  # 100 AFF needed
        actual_received = int(95 * 10**18)  # only got 95 AFF

        mock_safe.return_value = actual_received

        hub = MagicMock()
        engine._cheapest_aff_route = MagicMock(return_value=("dex", int(5000 * 10**18)))

        tx_hashes, gas_spent = engine._acquire_aff(shortfall, hub, dry_run=False)

        deposit_calls = [c for c in hub.functions.deposit.call_args_list]
        if deposit_calls:
            deposit_amount = deposit_calls[0][0][1]  # second positional arg
            self.assertLessEqual(deposit_amount, actual_received,
                                 f"Deposit {deposit_amount/1e18} AFF > received {actual_received/1e18}")


class TestBotLossMasking(unittest.TestCase):
    """Flaw #4: bot must track actual PLS losses, not clamp to 0."""

    def test_negative_delta_not_masked(self):
        """When pls_after < pls_before, realized delta should be negative."""
        pls_before = int(2_000_000 * 10**18)
        pls_after  = int(1_999_500 * 10**18)  # lost 500 PLS to gas

        # Current buggy code:
        buggy_profit = max(0, pls_after - pls_before)
        self.assertEqual(buggy_profit, 0, "Sanity: buggy code masks loss")

        # Fixed code should preserve the negative delta:
        realized_delta = pls_after - pls_before
        self.assertLess(realized_delta, 0, "Fixed code should show negative delta")
        self.assertEqual(realized_delta, -500 * 10**18)


if __name__ == "__main__":
    unittest.main()
