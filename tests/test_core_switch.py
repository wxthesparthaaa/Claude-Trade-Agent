"""
Run with:
    pytest tests/test_core_switch.py -v

Growth's index-core switch (src/core_switch.py, wired in scan_workflow.run_scan):
the core sleeve holds QQQ while QQQ is above its 200-day SMA band and sits in cash
otherwise. Reuses test_scan_workflow's fakes.
"""
import dataclasses
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core_switch import CoreSwitchConfig, core_switch_risk_on
from portfolio_profiles import GROWTH_PROFILE, _build_dividend_profile
from scan_workflow import run_scan
from universe import UniverseEntry
from test_scan_workflow import (
    make_price_series, make_profile, patch_fetches, no_regime, UPTREND,
    FakeQuoteClient, FakeTradeClient, FakePosition, FakeContract,
)

TODAY = date(2030, 1, 1)
SWITCH = CoreSwitchConfig(symbol="QQQ", sma_days=200, band_pct=0.02)

QQQ_SLOW_UP = make_price_series(100.0, [1.0005] * 260)                 # above the band, weak momentum (low confidence)
QQQ_CRASH = make_price_series(100.0, [1.003] * 200 + [0.99] * 60)       # far below the band
# flat, a long decline, then a sharp rebound: above the band, but 126/21 momentum is deeply negative
QQQ_REBOUND = make_price_series(100.0, [1.0] * 230 + [0.995] * 105 + [1.03] * 25)


def _closes(changes, start=100.0):
    return make_price_series(start, changes)


def test_risk_on_above_band_and_off_below():
    assert core_switch_risk_on(QQQ_SLOW_UP, 200, 0.02, TODAY) is True
    assert core_switch_risk_on(QQQ_CRASH, 200, 0.02, TODAY) is False


def test_inside_the_band_keeps_the_previous_state():
    on_then_flat = _closes([1.003] * 220 + [1.0] * 400)    # rises through the band, then flat: SMA catches up to price
    assert core_switch_risk_on(on_then_flat, 200, 0.02, TODAY) is True
    off_then_flat = _closes([0.997] * 220 + [1.0] * 400)
    assert core_switch_risk_on(off_then_flat, 200, 0.02, TODAY) is False


def test_band_actually_delays_the_flip():
    # 1% above a flat SMA: on without a band, still off with a 2% band
    series = _closes([1.0] * 250 + [1.01, 1.0])   # make_price_series applies a change AFTER recording a price
    assert core_switch_risk_on(series, 200, 0.0, TODAY) is True
    assert core_switch_risk_on(series, 200, 0.02, TODAY) is False


def test_todays_partial_bar_is_ignored():
    series = list(QQQ_SLOW_UP)
    series.append((TODAY, series[-1][1] * 0.5))   # an intraday crash on today's partial bar
    assert core_switch_risk_on(series, 200, 0.02, TODAY) is True
    assert core_switch_risk_on(series, 200, 0.02, TODAY + timedelta(days=1)) is False


def test_not_enough_history_is_unknown():
    assert core_switch_risk_on(make_price_series(100.0, [1.001] * 150), 200, 0.02, TODAY) is None
    assert core_switch_risk_on([], 200, 0.02, TODAY) is None


def test_growth_profile_has_the_switch_and_dividend_does_not(monkeypatch):
    assert GROWTH_PROFILE.core_switch == SWITCH
    monkeypatch.setenv("DIVIDEND_PORTFOLIO_CAPITAL", "30000")
    assert _build_dividend_profile().core_switch is None


def _universe():
    return [UniverseEntry("QQQ", "US", "USD", "", "core"), UniverseEntry("IWM", "US", "USD", "", "core"),
            UniverseEntry("UP", "US", "USD", "", "satellite")]


def _profile(tmp_path, switch=SWITCH):
    p = make_profile(tmp_path, _universe(), initial_capital=5000.0, max_capital_at_risk=5000.0,
                     confidence_scale=0.15, rebalance_band_pct=0.2)
    return dataclasses.replace(p, core_switch=switch)


def test_risk_on_core_is_qqq_only_with_the_gate_waived(tmp_path, monkeypatch):
    patch_fetches(monkeypatch, {"QQQ": QQQ_SLOW_UP, "IWM": UPTREND, "UP": UPTREND})
    no_regime(monkeypatch, tmp_path)
    result = run_scan(FakeQuoteClient(), FakeTradeClient(), _profile(tmp_path))

    assert result.confidence_by_symbol["QQQ"] < 70.0           # would fail the gate without the switch
    assert result.confidence_by_symbol["IWM"] >= 70.0
    core = {p.symbol for p in result.planned if p.sleeve == "core"}
    assert core == {"QQQ"}
    qqq = next(p for p in result.planned if p.symbol == "QQQ")
    assert abs(qqq.target_pct - 0.35) < 1e-9                    # 40% core budget, capped at the 35% single-name cap
    assert any(i.symbol == "QQQ" and i.action == "BUY" for i in result.instructions)
    iwm = next(d for d in result.decisions if d.symbol == "IWM")
    assert iwm.action == "reject" and iwm.reason.startswith("core switch")


def test_risk_off_core_goes_to_cash_and_a_held_core_name_is_sold(tmp_path, monkeypatch):
    patch_fetches(monkeypatch, {"QQQ": QQQ_CRASH, "IWM": UPTREND, "UP": UPTREND})
    no_regime(monkeypatch, tmp_path)
    px = UPTREND[-1][1]
    held = FakeTradeClient([FakePosition(FakeContract("IWM"), 10, px, px, 10 * px, 0.0, 0.0)])
    result = run_scan(FakeQuoteClient(), held, _profile(tmp_path))

    assert not [p for p in result.planned if p.sleeve == "core"]
    assert any(i.symbol == "IWM" and i.action == "SELL" and i.quantity == 10 for i in result.instructions)
    assert not any(i.symbol == "QQQ" and i.action == "BUY" for i in result.instructions)
    assert {p.symbol for p in result.planned} == {"UP"}         # satellites unaffected


def test_without_the_switch_the_core_is_trend_ranked_as_before(tmp_path, monkeypatch):
    patch_fetches(monkeypatch, {"QQQ": QQQ_CRASH, "IWM": UPTREND, "UP": UPTREND})
    no_regime(monkeypatch, tmp_path)
    result = run_scan(FakeQuoteClient(), FakeTradeClient(), _profile(tmp_path, switch=None))
    assert {p.symbol for p in result.planned if p.sleeve == "core"} == {"IWM"}


def test_held_switch_etf_skips_the_momentum_exit_but_not_without_the_switch(tmp_path, monkeypatch):
    patch_fetches(monkeypatch, {"QQQ": QQQ_REBOUND, "IWM": UPTREND, "UP": UPTREND})
    no_regime(monkeypatch, tmp_path)
    assert core_switch_risk_on(QQQ_REBOUND, 200, 0.02, TODAY) is True
    px = QQQ_REBOUND[-1][1]
    held = [FakePosition(FakeContract("QQQ"), 10, px, px, 10 * px, 0.0, 0.0)]

    with_switch = run_scan(FakeQuoteClient(), FakeTradeClient(held), _profile(tmp_path))
    assert "QQQ" not in with_switch.exit_reasons
    assert "QQQ" in {p.symbol for p in with_switch.planned}

    without = run_scan(FakeQuoteClient(), FakeTradeClient(held), _profile(tmp_path, switch=None))
    assert "momentum" in without.exit_reasons.get("QQQ", "").lower()


def test_unknown_state_allows_no_new_core_entry(tmp_path, monkeypatch):
    short_qqq = make_price_series(100.0, [1.001] * 160)   # scored, but too short for a 200d SMA
    patch_fetches(monkeypatch, {"QQQ": short_qqq, "IWM": UPTREND, "UP": UPTREND})
    no_regime(monkeypatch, tmp_path)
    result = run_scan(FakeQuoteClient(), FakeTradeClient(), _profile(tmp_path))
    assert not [p for p in result.planned if p.sleeve == "core"]
    assert "not enough QQQ history" in next(d for d in result.decisions if d.symbol == "IWM").reason
