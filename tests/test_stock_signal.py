"""
Run with:
    pytest tests/test_stock_signal.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from stock_signal import momentum_score, trailing_dividend_yield, composite_score, rank_candidates


def make_price_series(start_price, daily_changes, start_date=date(2026, 1, 5)):
    prices = []
    price = start_price
    d = start_date
    for change in daily_changes:
        prices.append((d, price))
        price *= change
        d += timedelta(days=1)
    return prices


def test_momentum_positive_for_uptrend():
    prices = make_price_series(100.0, [1.002] * 150)
    score = momentum_score(prices, lookback_days=126, skip_recent_days=21)
    assert score > 0


def test_momentum_negative_for_downtrend():
    prices = make_price_series(100.0, [0.998] * 150)
    score = momentum_score(prices, lookback_days=126, skip_recent_days=21)
    assert score < 0


def test_momentum_raises_on_insufficient_data():
    prices = make_price_series(100.0, [1.0] * 50)
    with pytest.raises(ValueError):
        momentum_score(prices, lookback_days=126, skip_recent_days=21)


def test_momentum_skip_recent_must_be_smaller_than_lookback():
    prices = make_price_series(100.0, [1.0] * 200)
    with pytest.raises(ValueError):
        momentum_score(prices, lookback_days=20, skip_recent_days=20)


def test_trailing_dividend_yield_sums_within_window():
    prices = [(date(2026, 6, 30), 80.0)]
    dividends = [
        (date(2026, 3, 15), 0.70),
        (date(2026, 6, 15), 0.68),
        (date(2024, 1, 1), 5.0),  # outside the trailing window, should be excluded
    ]
    yield_ = trailing_dividend_yield(prices, dividends, trailing_days=365)
    assert yield_ == pytest.approx((0.70 + 0.68) / 80.0)


def test_trailing_dividend_yield_zero_when_no_dividends():
    prices = [(date(2026, 6, 30), 80.0)]
    assert trailing_dividend_yield(prices, []) == 0.0


def test_composite_score_default_weights():
    score = composite_score(momentum=0.20, div_yield=0.03, news_tilt=0.5)
    assert score == pytest.approx(0.6 * 0.20 + 0.3 * 0.03 + 0.1 * 0.5)


def test_composite_score_custom_weights():
    score = composite_score(momentum=0.10, div_yield=0.05, news_tilt=0.0, weights={"momentum": 1.0})
    assert score == pytest.approx(0.10)


def test_rank_candidates_sorts_descending():
    scores = {"A": 0.05, "B": 0.20, "C": -0.10}
    assert rank_candidates(scores) == ["B", "A", "C"]
