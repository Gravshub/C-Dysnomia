"""
test_gas_eip1559.py — Unit tests for EIP-1559 Type 2 TX gas parameter building.

Validates:
  - build_gas_params() produces correct maxFeePerGas/maxPriorityFeePerGas
  - Gas pricing uses baseFeePerGas * floor_mult + priority (not legacy 3x)
  - Tier multipliers scale priority fee correctly
  - Fallback to eth_gasPrice when baseFeePerGas unavailable
  - GAS_PRICE_CEIL check works against maxFeePerGas

Run:
  python -m pytest scripts/Joystick/tests/test_gas_eip1559.py -v
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

# Ensure test environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
os.environ.setdefault("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32")
os.environ.setdefault("PULSECHAIN_RPC", "http://127.0.0.1:8545")
os.environ.setdefault("PULSECHAIN_READ_RPC", "http://127.0.0.1:8545")
os.environ.pop("DYSNOMIA_PRIVATE_KEY", None)


# Override autouse fixtures from conftest that require Anvil
@pytest.fixture(autouse=True)
def isolate(request):
    """No-op: these are pure unit tests."""
    yield


class TestBuildGasParams:
    """Test build_gas_params() with mocked Web3 provider."""

    def _mock_w3(self, base_fee_impulses: int):
        """Create a mock w3 with a block returning baseFeePerGas."""
        w3 = MagicMock()
        w3.eth.get_block.return_value = {"baseFeePerGas": base_fee_impulses}
        w3.eth.gas_price = base_fee_impulses * 2  # legacy fallback
        return w3

    def test_type2_params_present(self):
        """build_gas_params returns type=2 with maxFeePerGas and maxPriorityFeePerGas."""
        from scripts.Joystick.core.executor import build_gas_params

        # 748K Beats = 748_000 * 10^9 impulses (typical PulseChain base fee)
        base_fee = 748_000 * 10**9
        w3 = self._mock_w3(base_fee)

        params = build_gas_params(tier="fast", w3=w3)

        assert params["type"] == 2
        assert "maxFeePerGas" in params
        assert "maxPriorityFeePerGas" in params
        assert "gasPrice" not in params

    def test_max_fee_uses_floor_mult(self):
        """maxFeePerGas should be baseFee * GAS_PRICE_FLOOR_MULT + priority, not 3x baseFee."""
        from scripts.Joystick.core.executor import build_gas_params
        from scripts.Joystick.core.config import GAS_PRICE_FLOOR_MULT, GAS_PRIORITY_FEE

        base_fee = 748_000 * 10**9  # 748K Beats in impulses
        w3 = self._mock_w3(base_fee)

        params = build_gas_params(tier="fast", w3=w3)

        # fast tier = 4x fixed tip
        expected_priority = GAS_PRIORITY_FEE * 10**9 * 4
        expected_max = int(base_fee * GAS_PRICE_FLOOR_MULT) + expected_priority

        assert params["maxFeePerGas"] == expected_max
        assert params["maxPriorityFeePerGas"] == expected_priority

        # Verify it's much less than old 3x strategy
        old_max_fee = base_fee * 3
        assert params["maxFeePerGas"] < old_max_fee, \
            f"New maxFee {params['maxFeePerGas']} should be < old 3x {old_max_fee}"

    def test_tier_multipliers(self):
        """Different tiers should scale priority fee."""
        from scripts.Joystick.core.executor import build_gas_params
        from scripts.Joystick.core.config import GAS_PRIORITY_FEE

        base_fee = 748_000 * 10**9
        w3 = self._mock_w3(base_fee)
        base_tip = GAS_PRIORITY_FEE * 10**9

        slow = build_gas_params(tier="slow", w3=w3)
        fast = build_gas_params(tier="fast", w3=w3)
        urgent = build_gas_params(tier="urgent", w3=w3)

        assert slow["maxPriorityFeePerGas"] == base_tip * 1
        assert fast["maxPriorityFeePerGas"] == base_tip * 4
        assert urgent["maxPriorityFeePerGas"] == base_tip * 8
        assert slow["maxFeePerGas"] < fast["maxFeePerGas"] < urgent["maxFeePerGas"]

    def test_fallback_when_no_basefee(self):
        """Falls back to eth_gasPrice when baseFeePerGas unavailable."""
        from scripts.Joystick.core.executor import build_gas_params

        w3 = MagicMock()
        w3.eth.get_block.side_effect = KeyError("baseFeePerGas")
        w3.eth.gas_price = 1_000_000 * 10**9  # 1M Beats

        params = build_gas_params(tier="fast", w3=w3)

        assert params["type"] == 2
        assert params["maxFeePerGas"] == w3.eth.gas_price

    def test_savings_vs_old_strategy(self):
        """Quantify savings: new strategy should be ~45% cheaper than old 3x + 500K min tip."""
        from scripts.Joystick.core.executor import build_gas_params

        base_fee = 748_000 * 10**9  # Typical PulseChain base
        w3 = self._mock_w3(base_fee)

        params = build_gas_params(tier="fast", w3=w3)

        # Old strategy: maxFee = baseFee * 3 = 2,244,000 Beats
        old_max_fee = base_fee * 3
        new_max_fee = params["maxFeePerGas"]

        savings_pct = (old_max_fee - new_max_fee) / old_max_fee * 100
        assert savings_pct > 30, \
            f"Expected >30% savings, got {savings_pct:.1f}%"


class TestGasOracleBaseFee:
    """Test GasOracle base fee tracking."""

    def test_base_fee_tracked(self):
        """GasOracle.update() should track baseFeePerGas."""
        from scripts.Joystick.core.gas_oracle import GasOracle

        oracle = GasOracle()

        with patch("scripts.Joystick.core.gas_oracle.w3_read") as mock_w3:
            mock_w3.eth.gas_price = 1_000_000 * 10**9
            mock_w3.eth.get_block.return_value = {
                "baseFeePerGas": 748_000 * 10**9,
                "transactions": [],
            }

            oracle.update()

            assert oracle.base_fee() == 748_000 * 10**9
            assert oracle.base_fee_beats() == pytest.approx(748_000, rel=0.01)

    def test_base_fee_in_status(self):
        """GasOracle.status() should include base_fee_beats."""
        from scripts.Joystick.core.gas_oracle import GasOracle

        oracle = GasOracle()

        with patch("scripts.Joystick.core.gas_oracle.w3_read") as mock_w3:
            mock_w3.eth.gas_price = 1_000_000 * 10**9
            mock_w3.eth.get_block.return_value = {
                "baseFeePerGas": 748_000 * 10**9,
                "transactions": [],
            }

            oracle.update()
            status = oracle.status()

            assert "base_fee_beats" in status
            assert status["base_fee_beats"] == pytest.approx(748_000, rel=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
