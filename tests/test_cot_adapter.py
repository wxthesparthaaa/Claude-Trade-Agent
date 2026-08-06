"""
Run with:
    pytest tests/test_cot_adapter.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from cot_adapter import parse_cot_positioning, positioning_to_tilt, PositioningMetric


def make_row(report_date, oi, long_, short):
    return {
        "report_date_as_yyyy_mm_dd": report_date,
        "open_interest_all": str(oi),
        "noncomm_positions_long_all": str(long_),
        "noncomm_positions_short_all": str(short),
    }


def test_parse_cot_positioning_computes_current_net_pct():
    rows = [make_row("2026-07-28", 1000, 300, 200)]  # most recent first
    metric = parse_cot_positioning(rows, "sp500")
    assert metric.net_position_pct_oi == pytest.approx((300 - 200) / 1000)
    assert metric.as_of == "2026-07-28"
    assert metric.weeks_of_history == 1
    assert metric.z_score == 0.0  # can't compute a z-score from one data point


def test_parse_cot_positioning_computes_zscore_against_history():
    # Trailing weeks all around net ~0%, current week spikes to 40% net long.
    rows = [make_row("2026-07-28", 1000, 700, 300)] + [
        make_row(f"2026-0{m}-01", 1000, 500, 500) for m in range(1, 7)
    ]
    metric = parse_cot_positioning(rows, "sp500")
    assert metric.net_position_pct_oi == pytest.approx(0.40)
    assert metric.z_score > 1.5  # clearly an outlier vs a flat trailing history


def test_parse_cot_positioning_skips_malformed_rows():
    rows = [
        {"report_date_as_yyyy_mm_dd": "2026-07-28"},  # missing numeric fields
        make_row("2026-07-21", 1000, 400, 300),
    ]
    metric = parse_cot_positioning(rows, "sp500")
    assert metric.weeks_of_history == 1
    assert metric.as_of == "2026-07-21"


def test_parse_cot_positioning_skips_zero_open_interest():
    rows = [make_row("2026-07-28", 0, 100, 50), make_row("2026-07-21", 1000, 400, 300)]
    metric = parse_cot_positioning(rows, "sp500")
    assert metric.weeks_of_history == 1


def test_parse_cot_positioning_returns_none_for_empty_input():
    assert parse_cot_positioning([], "sp500") is None
    assert parse_cot_positioning(None, "sp500") is None


def test_positioning_to_tilt_neutral_when_no_metrics():
    assert positioning_to_tilt({}) == 1.0


def test_positioning_to_tilt_reduces_on_crowded_long():
    metrics = {"sp500": PositioningMetric("sp500", "2026-07-28", 0.4, z_score=2.5, weeks_of_history=52)}
    tilt = positioning_to_tilt(metrics, extreme_z=2.0, tilt_magnitude=0.1)
    assert tilt == pytest.approx(0.9)  # clamped at extreme_z -> full -0.1 tilt


def test_positioning_to_tilt_increases_on_crowded_short():
    metrics = {"sp500": PositioningMetric("sp500", "2026-07-28", -0.4, z_score=-2.5, weeks_of_history=52)}
    tilt = positioning_to_tilt(metrics, extreme_z=2.0, tilt_magnitude=0.1)
    assert tilt == pytest.approx(1.1)


def test_positioning_to_tilt_averages_across_contracts():
    metrics = {
        "sp500": PositioningMetric("sp500", "2026-07-28", 0.1, z_score=2.0, weeks_of_history=52),
        "nasdaq100": PositioningMetric("nasdaq100", "2026-07-28", 0.1, z_score=0.0, weeks_of_history=52),
    }
    tilt = positioning_to_tilt(metrics, extreme_z=2.0, tilt_magnitude=0.1)
    assert tilt == pytest.approx(1.0 - (1.0 / 2.0) * 0.1)  # avg z = 1.0
