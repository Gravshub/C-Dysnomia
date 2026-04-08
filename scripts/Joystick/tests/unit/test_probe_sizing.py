"""Test the constant-product sell-sizing math."""
import math
import pytest

from scripts.Joystick.core.probe_controller import solve_for_impact


def test_solve_for_impact_baseline():
    """At 0.3% impact on a 5000 GIBS pool, expect ~7.5 GIBS sell."""
    # x = R_gibs * (sqrt(1 + p) - 1) / 0.997
    # = 5000 * (sqrt(1.003) - 1) / 0.997
    # = 5000 * 0.001498 / 0.997 ≈ 7.51 GIBS
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result_wei = solve_for_impact(0.3, (R_gibs, R_wpls))
    result_gibs = result_wei / 1e18
    assert 7.0 < result_gibs < 8.0


def test_solve_for_impact_5pct():
    """At 5% impact, expect ~125 GIBS sell on the same pool."""
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result_wei = solve_for_impact(5.0, (R_gibs, R_wpls))
    result_gibs = result_wei / 1e18
    assert 120 < result_gibs < 130


def test_solve_for_impact_10pct_cap():
    """At 10% target impact, expect ~244 GIBS (under-delivers to ~9.09% execution)."""
    R_gibs = 5000 * 10**18
    R_wpls = 210_000 * 10**18
    result_wei = solve_for_impact(10.0, (R_gibs, R_wpls))
    result_gibs = result_wei / 1e18
    assert 230 < result_gibs < 260


def test_solve_for_impact_zero_returns_zero():
    """0% impact should return 0."""
    assert solve_for_impact(0.0, (5000 * 10**18, 210_000 * 10**18)) == 0


def test_solve_for_impact_negative_raises():
    """Negative impact is a usage error."""
    with pytest.raises(ValueError):
        solve_for_impact(-1.0, (5000 * 10**18, 210_000 * 10**18))


def test_solve_for_impact_zero_reserve_raises():
    """Empty pool is undefined."""
    with pytest.raises(ValueError):
        solve_for_impact(1.0, (0, 210_000 * 10**18))
