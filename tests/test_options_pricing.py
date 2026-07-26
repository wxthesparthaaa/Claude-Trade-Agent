"""
Run with:
    pytest tests/test_options_pricing.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from options_pricing import (
    put_price, put_delta, call_price, call_delta, solve_strike_for_put_delta,
)


def test_put_call_parity():
    # C - P = S - K*e^(-rT)   (standard Black-Scholes identity)
    spot, strike, dte_years, vol, rate = 100.0, 100.0, 7 / 365, 0.30, 0.045
    c = call_price(spot, strike, dte_years, vol, rate)
    p = put_price(spot, strike, dte_years, vol, rate)
    import math
    expected = spot - strike * math.exp(-rate * dte_years)
    assert (c - p) == pytest.approx(expected, abs=1e-6)


def test_put_delta_bounds():
    # Put delta must always be between -1 and 0
    for strike in (50, 80, 100, 120, 150):
        d = put_delta(100.0, strike, 7 / 365, 0.30)
        assert -1.0 <= d <= 0.0


def test_deeper_otm_put_has_smaller_delta_magnitude():
    spot, dte_years, vol = 100.0, 7 / 365, 0.30
    d_near = put_delta(spot, 95, dte_years, vol)   # closer to the money
    d_far = put_delta(spot, 80, dte_years, vol)    # further OTM
    assert abs(d_far) < abs(d_near)


def test_call_delta_bounds():
    for strike in (50, 80, 100, 120, 150):
        d = call_delta(100.0, strike, 7 / 365, 0.30)
        assert 0.0 <= d <= 1.0


def test_solve_strike_for_put_delta_matches_target():
    spot, dte_years, vol = 100.0, 7 / 365, 0.30
    for target in (0.10, 0.20, 0.30):
        strike = solve_strike_for_put_delta(spot, target, dte_years, vol)
        actual_delta = put_delta(spot, strike, dte_years, vol)
        assert abs(actual_delta) == pytest.approx(target, abs=0.005)


def test_solved_strike_is_below_spot_for_otm_put():
    spot, dte_years, vol = 100.0, 7 / 365, 0.30
    strike = solve_strike_for_put_delta(spot, 0.20, dte_years, vol)
    assert strike < spot


def test_higher_vol_increases_put_premium():
    spot, strike, dte_years = 100.0, 95.0, 7 / 365
    low_vol_price = put_price(spot, strike, dte_years, 0.15)
    high_vol_price = put_price(spot, strike, dte_years, 0.50)
    assert high_vol_price > low_vol_price


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        put_price(100, 100, dte_years=0, vol=0.3)
    with pytest.raises(ValueError):
        put_price(100, 100, dte_years=0.1, vol=0)
