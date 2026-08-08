"""
Run with:
    pytest tests/test_short_signal.py -v
"""
import sys
import os
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from short_signal import score_short_candidate, market_favors_shorting


def make_price_series(start_price, daily_changes, start_date=date(2026, 1, 5)):
    prices = []
    price = start_price
    d = start_date
    for change in daily_changes:
        prices.append((d, price))
        price *= change
        d += timedelta(days=1)
    return prices


def regime(positioning_tilt=None, breadth_trend=None, breadth_at_edge=False):
    return SimpleNamespace(positioning_tilt=positioning_tilt, breadth_trend=breadth_trend, breadth_at_edge=breadth_at_edge)


def test_score_short_candidate_flags_a_real_breakdown():
    prices = make_price_series(100.0, [0.998] * 150)  # steady downtrend
    score = score_short_candidate(prices, lookback_days=126, skip_recent_days=21, breakdown_threshold=-0.10)
    assert score is not None
    assert score <= -0.10


def test_score_short_candidate_ignores_mild_decline():
    prices = make_price_series(100.0, [0.9995] * 150)  # mild decline, not a real breakdown
    score = score_short_candidate(prices, lookback_days=126, skip_recent_days=21, breakdown_threshold=-0.15)
    assert score is None


def test_score_short_candidate_ignores_uptrend():
    prices = make_price_series(100.0, [1.002] * 150)
    assert score_short_candidate(prices, lookback_days=126, skip_recent_days=21) is None


def test_score_short_candidate_returns_none_on_insufficient_history():
    prices = make_price_series(100.0, [0.99] * 50)
    assert score_short_candidate(prices, lookback_days=126, skip_recent_days=21) is None


def test_market_favors_shorting_false_when_no_regime():
    assert market_favors_shorting(None) is False


def test_market_favors_shorting_false_when_neither_signal_fires():
    assert market_favors_shorting(regime(positioning_tilt=1.0, breadth_trend="broadening", breadth_at_edge=False)) is False


def test_market_favors_shorting_true_on_cot_crowded_long():
    assert market_favors_shorting(regime(positioning_tilt=0.90), crowded_threshold=0.92) is True


def test_market_favors_shorting_false_when_cot_tilt_above_threshold():
    assert market_favors_shorting(regime(positioning_tilt=0.976), crowded_threshold=0.92) is False


def test_market_favors_shorting_true_on_narrowing_breadth_at_edge():
    assert market_favors_shorting(regime(positioning_tilt=1.0, breadth_trend="narrowing", breadth_at_edge=True)) is True


def test_market_favors_shorting_false_on_narrowing_breadth_not_at_edge():
    assert market_favors_shorting(regime(positioning_tilt=1.0, breadth_trend="narrowing", breadth_at_edge=False)) is False


def test_market_favors_shorting_false_on_broadening_breadth_even_at_edge():
    assert market_favors_shorting(regime(positioning_tilt=1.0, breadth_trend="broadening", breadth_at_edge=True)) is False
