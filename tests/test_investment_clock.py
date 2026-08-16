"""
Run with:
    pytest tests/test_investment_clock.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import investment_clock
from investment_clock import (
    compute_investment_clock, hk_sg_unavailable_signal, refresh_investment_clock,
    load_investment_clock, save_investment_clock, InvestmentClockSignal,
    GROWTH_MA_LONG, INFLATION_MA_LONG,
)


def make_series(values, start=date(2020, 1, 1), step_days=30):
    d = start
    series = []
    for v in values:
        series.append((d, v))
        d += timedelta(days=step_days)
    return series


def _rising_series(n, step_days=30):
    return make_series([100.0 + i for i in range(n)], step_days=step_days)


def _falling_series(n, step_days=30):
    return make_series([100.0 - i for i in range(n)], step_days=step_days)


# ---- compute_investment_clock quadrant mapping -------------------------------------------------

def test_recovery_quadrant_growth_rising_inflation_falling():
    growth = _rising_series(GROWTH_MA_LONG + 2)
    inflation = _falling_series(INFLATION_MA_LONG + 5, step_days=1)
    signal = compute_investment_clock(growth, inflation)
    assert signal is not None
    assert signal.quadrant == "Recovery"
    assert signal.growth_trend == "rising"
    assert signal.inflation_trend == "falling"
    assert signal.best_sectors == ["Technology", "Consumer Discretionary", "Industrials"]


def test_overheat_quadrant_growth_rising_inflation_rising():
    growth = _rising_series(GROWTH_MA_LONG + 2)
    inflation = _rising_series(INFLATION_MA_LONG + 5, step_days=1)
    signal = compute_investment_clock(growth, inflation)
    assert signal.quadrant == "Overheat"
    assert signal.best_sectors == ["Energy", "Materials"]


def test_stagflation_quadrant_growth_falling_inflation_rising():
    growth = _falling_series(GROWTH_MA_LONG + 2)
    inflation = _rising_series(INFLATION_MA_LONG + 5, step_days=1)
    signal = compute_investment_clock(growth, inflation)
    assert signal.quadrant == "Stagflation"
    assert signal.best_sectors == ["Consumer Staples", "Utilities", "Health Care"]


def test_reflation_quadrant_growth_falling_inflation_falling():
    growth = _falling_series(GROWTH_MA_LONG + 2)
    inflation = _falling_series(INFLATION_MA_LONG + 5, step_days=1)
    signal = compute_investment_clock(growth, inflation)
    assert signal.quadrant == "Reflation"
    assert signal.best_sectors == ["Utilities", "Health Care", "Consumer Staples"]


def test_returns_none_when_growth_history_insufficient():
    growth = _rising_series(GROWTH_MA_LONG - 1)
    inflation = _rising_series(INFLATION_MA_LONG + 5, step_days=1)
    assert compute_investment_clock(growth, inflation) is None


def test_returns_none_when_inflation_history_insufficient():
    growth = _rising_series(GROWTH_MA_LONG + 2)
    inflation = _rising_series(INFLATION_MA_LONG - 1, step_days=1)
    assert compute_investment_clock(growth, inflation) is None


def test_signal_carries_latest_raw_values():
    growth = _rising_series(GROWTH_MA_LONG + 2)
    inflation = _falling_series(INFLATION_MA_LONG + 5, step_days=1)
    signal = compute_investment_clock(growth, inflation)
    assert signal.growth_value == growth[-1][1]
    assert signal.inflation_value == inflation[-1][1]
    assert signal.region == "US"
    assert signal.as_of == date.today().isoformat()


# ---- hk_sg_unavailable_signal -------------------------------------------------

def test_hk_sg_unavailable_signal_shape():
    signal = hk_sg_unavailable_signal("HK")
    assert signal.region == "HK"
    assert signal.quadrant == ""
    assert signal.best_sectors == []
    assert "US-only" in signal.note


# ---- refresh_investment_clock (orchestration) -------------------------------------------------

def test_refresh_investment_clock_success(monkeypatch):
    growth = _rising_series(GROWTH_MA_LONG + 2)
    inflation = _falling_series(INFLATION_MA_LONG + 5, step_days=1)

    def fake_fetch(series_id, timeout=20.0):
        return growth if series_id == "INDPRO" else inflation
    monkeypatch.setattr(investment_clock, "fetch_and_parse_series", fake_fetch)

    signal = refresh_investment_clock()
    assert signal.quadrant == "Recovery"


def test_refresh_investment_clock_raises_when_not_enough_history(monkeypatch):
    monkeypatch.setattr(investment_clock, "fetch_and_parse_series", lambda series_id, timeout=20.0: [])
    try:
        refresh_investment_clock()
        assert False, "expected ValueError"
    except ValueError:
        pass


# ---- load/save round trip -------------------------------------------------

def test_load_investment_clock_none_when_file_missing(tmp_path):
    assert load_investment_clock(str(tmp_path / "does_not_exist.json")) is None


def test_save_then_load_investment_clock_round_trips(tmp_path):
    path = str(tmp_path / "investment_clock.json")
    original = InvestmentClockSignal(
        as_of="2026-08-16", region="US", quadrant="Recovery", growth_trend="rising",
        inflation_trend="falling", growth_value=105.2, inflation_value=2.1,
        best_sectors=["Technology", "Consumer Discretionary", "Industrials"],
    )
    save_investment_clock(path, original)
    assert load_investment_clock(path) == original
