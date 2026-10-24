"""
Run with:
    pytest tests/test_stock_signal.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from stock_signal import (
    momentum_score, trailing_dividend_yield, composite_score, rank_candidates, score_symbol, trend_quality_score,
)


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


def test_score_symbol_returns_none_on_insufficient_history():
    prices = make_price_series(100.0, [1.001] * 50)
    assert score_symbol(prices, [], lookback_days=126, skip_recent_days=21) is None


def test_score_symbol_returns_populated_score():
    prices = make_price_series(100.0, [1.002] * 150)
    result = score_symbol(prices, [], lookback_days=126, skip_recent_days=21)
    assert result is not None
    assert result.momentum > 0
    assert result.div_yield == 0.0
    assert result.price == prices[-1][1]
    assert result.score == pytest.approx(composite_score(result.momentum, result.div_yield, 0.0))


def test_score_symbol_uses_news_tilt():
    prices = make_price_series(100.0, [1.0005] * 150)
    without_tilt = score_symbol(prices, [], lookback_days=126, skip_recent_days=21, news_tilt=0.0)
    with_tilt = score_symbol(prices, [], lookback_days=126, skip_recent_days=21, news_tilt=1.0)
    assert with_tilt.score > without_tilt.score


def test_composite_score_default_weights_include_sector_tilt():
    score = composite_score(momentum=0.20, div_yield=0.03, news_tilt=0.0, sector_tilt=0.5)
    assert score == pytest.approx(0.6 * 0.20 + 0.3 * 0.03 + 0.1 * 0.5)


def test_composite_score_sector_tilt_is_a_no_op_when_weights_omit_the_key():
    """DIVIDEND_SCORING_WEIGHTS has no "sector_tilt" key -- the tilt must
    contribute nothing regardless of its value, not raise or default to
    some other weight."""
    score = composite_score(
        momentum=0.20, div_yield=0.03, news_tilt=0.0, sector_tilt=1.0,
        weights={"momentum": 0.2, "div_yield": 0.7, "news_tilt": 0.1},
    )
    assert score == pytest.approx(0.2 * 0.20 + 0.7 * 0.03)


def test_score_symbol_uses_sector_tilt():
    prices = make_price_series(100.0, [1.0005] * 150)
    without_tilt = score_symbol(prices, [], lookback_days=126, skip_recent_days=21, sector_tilt=0.0)
    with_tilt = score_symbol(prices, [], lookback_days=126, skip_recent_days=21, sector_tilt=1.0)
    assert with_tilt.score > without_tilt.score


def test_trend_quality_of_a_perfect_exponential_is_its_annualized_log_growth():
    import math
    prices = make_price_series(100.0, [1.001] * 126)
    assert trend_quality_score(prices, window_days=126) == pytest.approx(252 * math.log(1.001), rel=1e-9)


def test_trend_quality_prefers_a_smooth_trend_over_a_choppy_one_with_the_same_return():
    choppy = make_price_series(100.0, [1.025, 0.9805] * 63)
    daily = (choppy[-1][1] / 100.0) ** (1 / 125)
    smooth = make_price_series(100.0, [daily] * 126)
    assert smooth[-1][1] == pytest.approx(choppy[-1][1])
    assert trend_quality_score(smooth) > trend_quality_score(choppy) > 0


def test_trend_quality_penalizes_a_spike_that_fades():
    # higher 126/21 momentum than the smooth climber, but a spike-and-fade
    # shape (AEHR, Oct 2026) -- trend quality ranks it far lower
    smooth = make_price_series(100.0, [1.002] * 160)
    spike_fade = make_price_series(100.0, [1.0] * 60 + [1.9] + [0.996] * 99)
    assert momentum_score(spike_fade, 126, 21) > momentum_score(smooth, 126, 21)
    assert trend_quality_score(spike_fade) < 0.2 * trend_quality_score(smooth)


def test_trend_quality_negative_for_downtrend():
    assert trend_quality_score(make_price_series(100.0, [0.998] * 130)) < 0


def test_trend_quality_none_without_a_full_window():
    assert trend_quality_score(make_price_series(100.0, [1.002] * 125), window_days=126) is None


def test_trend_quality_uses_only_the_last_window():
    early_crash = make_price_series(100.0, [0.9] * 20 + [1.002] * 126)
    assert trend_quality_score(early_crash, window_days=126) > 0


def test_trend_quality_flat_series_is_zero():
    assert trend_quality_score(make_price_series(100.0, [1.0] * 126)) == 0.0
