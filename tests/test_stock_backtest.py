"""
Run with:
    pytest tests/test_stock_backtest.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from stock_backtest import run_stock_backtest, summarize, _forward_fill_grid, BacktestPeriodResult
from portfolio_construction import PortfolioConfig
from risk_engine import RiskConfig, RiskEngine
from exit_rules import ExitConfig
from tiger_trade_metas_adapter import LotInfo
from universe import UniverseEntry
from decision_log import format_decision_summary


def make_series(start_price, daily_changes, start_date=date(2025, 1, 1)):
    prices = []
    price = start_price
    d = start_date
    for change in daily_changes:
        prices.append((d, price))
        price *= change
        d += timedelta(days=1)
    return prices


def default_engine(**overrides):
    return RiskEngine(RiskConfig(**overrides))


def test_raises_on_insufficient_data():
    universe = [UniverseEntry("A", "US", "USD", "", "core")]
    prices = {"A": make_series(100.0, [1.0] * 50)}
    with pytest.raises(ValueError):
        run_stock_backtest(prices, {}, universe, PortfolioConfig(), default_engine())


def test_backtest_produces_periods_for_valid_data():
    universe = [
        UniverseEntry("CORE1", "US", "USD", "", "core"),
        UniverseEntry("SAT1", "US", "USD", "", "satellite"),
    ]
    prices = {
        "CORE1": make_series(100.0, [1.0005] * 200),
        "SAT1": make_series(50.0, [1.002] * 200),
    }
    results = run_stock_backtest(prices, {}, universe, PortfolioConfig(), default_engine())
    assert len(results) > 0
    for r in results:
        assert isinstance(r, BacktestPeriodResult)
        assert not r.halted

    summary = summarize(results)
    assert summary["periods"] == len(results)
    assert "total_return_pct" in summary
    assert "max_drawdown_pct" in summary


def test_backtest_halts_on_severe_drawdown():
    universe = [
        UniverseEntry("CORE1", "US", "USD", "", "core"),
        UniverseEntry("SAT_CRASH", "US", "USD", "", "satellite"),
    ]
    # CORE1: flat throughout.
    core_prices = make_series(100.0, [1.0] * 200)
    # SAT_CRASH: mild uptrend for the first 127 days (wins the momentum
    # ranking), then craters -95% over the next rebalance period -- a
    # crash the scoring window couldn't have seen coming.
    uptrend = make_series(50.0, [1.003] * 128)
    crash_start_date = uptrend[-1][0] + timedelta(days=1)
    crash_price = uptrend[-1][1]
    crash = []
    d = crash_start_date
    for _ in range(72):
        crash.append((d, crash_price))
        crash_price *= 0.965  # steep sustained decline
        d += timedelta(days=1)
    sat_prices = uptrend + crash

    # Exit rules disabled for this test (stop_loss_pct=1.0 -> never triggers
    # on a normal price move) -- this test is about the drawdown circuit
    # breaker in isolation, not the stop-loss feature (which is what
    # actually would catch this crash in practice; see the dedicated
    # stop-loss test below).
    engine = default_engine(max_drawdown_pct=0.25)
    results = run_stock_backtest(
        {"CORE1": core_prices, "SAT_CRASH": sat_prices}, {}, universe, PortfolioConfig(), engine,
        exit_config=ExitConfig(stop_loss_pct=1.0, momentum_exit_threshold=-1.0),
    )
    assert len(results) > 0
    assert results[-1].halted is True
    assert "Max drawdown" in results[-1].halt_reason


def test_stop_loss_exits_crashing_position_early_and_caps_the_loss():
    universe = [
        UniverseEntry("CORE1", "US", "USD", "", "core"),
        UniverseEntry("SAT_CRASH", "US", "USD", "", "satellite"),
    ]
    core_prices = make_series(100.0, [1.0] * 200)
    uptrend = make_series(50.0, [1.003] * 128)
    crash_start_date = uptrend[-1][0] + timedelta(days=1)
    crash_price = uptrend[-1][1]
    crash = []
    d = crash_start_date
    for _ in range(72):
        crash.append((d, crash_price))
        crash_price *= 0.965
        d += timedelta(days=1)
    sat_prices = uptrend + crash

    # Default exit_config (15% stop-loss) is active here -- this is the
    # actual "when to sell" mechanism, not the drawdown breaker.
    results = run_stock_backtest(
        {"CORE1": core_prices, "SAT_CRASH": sat_prices}, {}, universe, PortfolioConfig(), default_engine(),
    )
    assert len(results) > 0
    all_exits = [e for r in results for e in r.exits if e.symbol == "SAT_CRASH"]
    assert len(all_exits) > 0
    assert all_exits[0].reason.startswith("stop_loss")
    # The stop-loss should have capped the realized loss well short of the
    # full -95% crash the underlying actually experienced.
    assert all_exits[0].return_at_exit > -0.25


def test_backtest_excludes_unaffordable_lot_sizes():
    universe = [
        UniverseEntry("CORE1", "US", "USD", "", "core"),
        UniverseEntry("SAT1", "HK", "HKD", "SEHK", "satellite"),
    ]
    prices = {
        "CORE1": make_series(100.0, [1.0005] * 200),
        "SAT1": make_series(50.0, [1.002] * 200),  # would normally win the momentum ranking
    }
    # SAT1's board lot (1000 shares at ~$50-90/share by the time of rebalancing)
    # costs far more than max_single_position_pct of $1,000 -- it should never
    # appear in any planned position once lot_infos is supplied.
    lot_infos = {"SAT1": LotInfo(lot_size=1000, min_tick=0.1)}

    results = run_stock_backtest(
        prices, {}, universe, PortfolioConfig(), default_engine(), lot_infos=lot_infos
    )
    assert len(results) > 0
    for r in results:
        assert all(p.symbol != "SAT1" for p in r.positions)


def test_backtest_produces_decision_log_entries():
    universe = [
        UniverseEntry("CORE1", "US", "USD", "", "core"),
        UniverseEntry("SAT1", "US", "USD", "", "satellite"),
        UniverseEntry("SAT2", "US", "USD", "", "satellite"),
    ]
    prices = {
        "CORE1": make_series(100.0, [1.0005] * 200),
        "SAT1": make_series(50.0, [1.002] * 200),
        "SAT2": make_series(50.0, [1.0005] * 200),  # weaker momentum than SAT1
    }
    results = run_stock_backtest(prices, {}, universe, PortfolioConfig(), default_engine())
    assert len(results) > 0

    first = results[0]
    assert len(first.decisions) > 0
    actions = {d.action for d in first.decisions}
    assert "buy" in actions
    buy_symbols = {d.symbol for d in first.decisions if d.action == "buy"}
    assert "CORE1" in buy_symbols
    assert "SAT1" in buy_symbols  # stronger momentum than SAT2, both fit under the sleeve cap

    second = results[1]
    hold_symbols = {d.symbol for d in second.decisions if d.action == "hold"}
    assert "SAT1" in hold_symbols  # still top pick next period -> hold, not re-bought

    summary_text = format_decision_summary(str(first.period_start), first.decisions)
    assert "Decisions for" in summary_text


def test_forward_fill_grid_carries_last_known_price():
    prices = {
        "A": [(date(2025, 1, 1), 10.0), (date(2025, 1, 3), 12.0)],
        "B": [(date(2025, 1, 1), 20.0), (date(2025, 1, 2), 21.0), (date(2025, 1, 3), 22.0)],
    }
    all_dates, aligned = _forward_fill_grid(prices)
    assert all_dates == [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
    # A has no price on 1/2 (market closed that day for A) -> forward-filled from 1/1
    assert aligned["A"] == [10.0, 10.0, 12.0]
    assert aligned["B"] == [20.0, 21.0, 22.0]


def test_summarize_empty_results():
    assert summarize([]) == {"periods": 0}
