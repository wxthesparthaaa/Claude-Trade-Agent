"""
Run with:
    pytest tests/test_market_breadth.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from market_breadth import compute_ratio_series, compute_breadth_signal


def make_series(start_price, daily_changes, start_date=date(2026, 1, 1)):
    series = []
    price = start_price
    d = start_date
    for change in daily_changes:
        series.append((d, price))
        price *= change
        d += timedelta(days=1)
    return series


def test_compute_ratio_series_aligns_by_date_and_divides():
    rsp = [(date(2026, 1, 1), 50.0), (date(2026, 1, 2), 51.0)]
    spy = [(date(2026, 1, 1), 500.0), (date(2026, 1, 2), 510.0)]
    ratio = compute_ratio_series(rsp, spy)
    assert ratio == [(date(2026, 1, 1), 0.1), (date(2026, 1, 2), 0.1)]


def test_compute_ratio_series_skips_dates_missing_from_either_side():
    rsp = [(date(2026, 1, 1), 50.0), (date(2026, 1, 2), 51.0)]
    spy = [(date(2026, 1, 1), 500.0)]  # missing 1/2
    ratio = compute_ratio_series(rsp, spy)
    assert ratio == [(date(2026, 1, 1), 0.1)]


def test_compute_breadth_signal_returns_none_on_insufficient_history():
    ratio = make_series(0.5, [1.0] * 50)
    assert compute_breadth_signal(ratio, ma_short_days=20, ma_long_days=100, roc_lookback_days=20) is None


def test_compute_breadth_signal_detects_broadening_trend():
    # steadily rising ratio -> price above both MAs, short MA above long MA
    ratio = make_series(0.5, [1.001] * 200)
    signal = compute_breadth_signal(ratio, ma_short_days=20, ma_long_days=100, roc_lookback_days=20)
    assert signal is not None
    assert signal.trend == "broadening"


def test_compute_breadth_signal_detects_narrowing_trend():
    ratio = make_series(0.5, [0.999] * 200)
    signal = compute_breadth_signal(ratio, ma_short_days=20, ma_long_days=100, roc_lookback_days=20)
    assert signal is not None
    assert signal.trend == "narrowing"


def test_compute_breadth_signal_flat_when_choppy():
    # oscillates around a level -- no persistent trend either MA-relative-to-ratio direction
    changes = [1.01, 0.99] * 100
    ratio = make_series(0.5, changes)
    signal = compute_breadth_signal(ratio, ma_short_days=20, ma_long_days=100, roc_lookback_days=20)
    assert signal is not None
    assert signal.trend == "flat"


def test_compute_breadth_signal_at_edge_on_extreme_roc():
    # a long flat stretch, then a sharp recent acceleration -> its ROC is an
    # outlier vs the trailing ROC history -> at_edge should trip
    flat = make_series(0.5, [1.0] * 150)
    last_date = flat[-1][0] + timedelta(days=1)
    spike = []
    price = flat[-1][1]
    d = last_date
    for _ in range(25):
        price *= 1.01
        spike.append((d, price))
        d += timedelta(days=1)
    ratio = flat + spike
    signal = compute_breadth_signal(ratio, ma_short_days=20, ma_long_days=100, roc_lookback_days=20, extreme_z=2.0)
    assert signal is not None
    assert signal.at_edge is True


def test_compute_breadth_signal_tilt_bounded_between_point_nine_and_one_point_one():
    ratio = make_series(0.5, [1.001] * 200)
    signal = compute_breadth_signal(ratio, ma_short_days=20, ma_long_days=100, roc_lookback_days=20, tilt_magnitude=0.1)
    assert 0.9 <= signal.tilt <= 1.1
