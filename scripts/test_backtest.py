"""
Run with:
    pytest tests/test_backtest.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from backtest import run_backtest, summarize, realized_volatility


def make_price_series(start_price, daily_changes, start_date=date(2026, 1, 5)):
    """daily_changes: list of multiplicative factors, e.g. 1.001 = +0.1%/day"""
    prices = []
    price = start_price
    d = start_date
    for change in daily_changes:
        prices.append((d, price))
        price *= change
        d += timedelta(days=1)
    return prices


def test_realized_volatility_zero_for_flat_prices():
    closes = [100.0] * 25
    vol = realized_volatility(closes)
    assert vol == pytest.approx(0.0, abs=1e-9)


def test_realized_volatility_positive_for_moving_prices():
    closes = [100, 101, 99, 102, 98, 103, 97, 104, 96, 105]
    vol = realized_volatility(closes)
    assert vol > 0


def test_realized_volatility_requires_min_two_points():
    with pytest.raises(ValueError):
        realized_volatility([100.0])


def test_backtest_no_assignment_when_price_stays_flat():
    # Flat/slightly noisy price shouldn't trigger many assignments for a
    # 20-delta (fairly OTM) put
    changes = [1.0 + (0.001 if i % 2 == 0 else -0.001) for i in range(60)]
    prices = make_price_series(100.0, changes)
    results = run_backtest(prices, target_delta=0.20, dte_days=7, trading_days_per_period=5, vol_window=20)
    assert len(results) > 0
    summary = summarize(results)
    # With a flat market and a 20-delta put, assignment should be rare, not the norm
    assert summary["assignment_rate"] < 0.5


def test_backtest_assignment_when_price_crashes():
    # Big sustained drop should trigger assignment
    changes = [0.98] * 60  # -2%/day sustained crash
    prices = make_price_series(100.0, changes)
    results = run_backtest(prices, target_delta=0.20, dte_days=7, trading_days_per_period=5, vol_window=20)
    assert len(results) > 0
    summary = summarize(results)
    assert summary["assignment_rate"] > 0.5


def test_backtest_raises_on_insufficient_data():
    prices = make_price_series(100.0, [1.0] * 10)  # too few points
    with pytest.raises(ValueError):
        run_backtest(prices, vol_window=20, trading_days_per_period=5)


def test_pnl_math_on_assigned_week():
    # Construct a scenario, then manually verify the pnl formula on the
    # first result: pnl = premium_total - max(0, strike - close_at_expiry)*100*contracts
    changes = [0.99] * 60
    prices = make_price_series(100.0, changes)
    results = run_backtest(prices, target_delta=0.20, dte_days=7, trading_days_per_period=5, vol_window=20)
    r = results[0]
    expected_loss = max(0.0, r.strike - r.close_at_expiry) * 100 * r.contracts
    expected_pnl = round(r.premium_total - expected_loss, 2)
    assert r.pnl == expected_pnl


def test_summarize_empty_results():
    summary = summarize([])
    assert summary == {"weeks": 0}
