"""
Run with:
    pytest tests/test_strategy.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from strategy import OptionContract, StrategyConfig, generate_candidates, select_portfolio
from risk_engine import RiskConfig, RiskEngine, DailyState, Position

TODAY = date(2026, 7, 26)


def make_put(symbol, strike, dte, delta, bid, ask, oi=200, vol=50):
    return OptionContract(
        symbol=symbol,
        option_symbol=f"{symbol}_{strike}_PUT",
        strike=strike,
        expiry=TODAY + timedelta(days=dte),
        put_call="PUT",
        bid=bid,
        ask=ask,
        delta=-abs(delta),   # puts carry negative delta
        open_interest=oi,
        volume=vol,
        implied_volatility=0.35,
    )


def test_filters_by_delta_range():
    chain = [
        make_put("AAPL", 190, dte=7, delta=0.10, bid=1.0, ask=1.1),   # too low delta
        make_put("AAPL", 185, dte=7, delta=0.20, bid=1.2, ask=1.3),   # in range
        make_put("AAPL", 180, dte=7, delta=0.40, bid=1.5, ask=1.6),   # too high delta
    ]
    config = StrategyConfig(target_delta_min=0.15, target_delta_max=0.30)
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)
    assert len(candidates) == 1
    assert candidates[0].strike == 185


def test_filters_by_dte_range():
    chain = [
        make_put("AAPL", 185, dte=2, delta=0.20, bid=1.0, ask=1.1),    # too short
        make_put("AAPL", 185, dte=10, delta=0.20, bid=1.2, ask=1.3),   # in range
        make_put("AAPL", 185, dte=30, delta=0.20, bid=2.0, ask=2.1),   # too long
    ]
    config = StrategyConfig(min_dte=5, max_dte=14)
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)
    assert len(candidates) == 1
    assert candidates[0].dte == 10


def test_filters_by_liquidity():
    chain = [
        make_put("AAPL", 185, dte=7, delta=0.20, bid=1.0, ask=1.1, oi=10, vol=1),   # illiquid
        make_put("AAPL", 180, dte=7, delta=0.20, bid=1.0, ask=1.1, oi=500, vol=50),  # liquid
    ]
    config = StrategyConfig(min_open_interest=100, min_volume=10)
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)
    assert len(candidates) == 1
    assert candidates[0].strike == 180


def test_earnings_filter_excludes_contracts_spanning_earnings():
    chain = [make_put("AAPL", 185, dte=10, delta=0.20, bid=1.0, ask=1.1)]
    config = StrategyConfig()
    earnings_in_window = TODAY + timedelta(days=5)
    candidates = generate_candidates(
        chain, "cash_secured_put", config, as_of=TODAY, next_earnings_date=earnings_in_window
    )
    assert len(candidates) == 0


def test_earnings_filter_allows_contracts_expiring_before_earnings():
    chain = [make_put("AAPL", 185, dte=7, delta=0.20, bid=1.0, ask=1.1)]
    config = StrategyConfig()
    earnings_after_expiry = TODAY + timedelta(days=20)
    candidates = generate_candidates(
        chain, "cash_secured_put", config, as_of=TODAY, next_earnings_date=earnings_after_expiry
    )
    assert len(candidates) == 1


def test_candidates_sorted_by_weekly_yield_descending():
    chain = [
        make_put("AAPL", 185, dte=7, delta=0.20, bid=1.0, ask=1.0),   # yield ~ 1.08%/wk
        make_put("MSFT", 400, dte=7, delta=0.20, bid=6.0, ask=6.0),   # yield ~ 3.0%/wk
    ]
    config = StrategyConfig()
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)
    assert len(candidates) == 2
    assert candidates[0].symbol == "MSFT"  # higher yield first
    assert candidates[0].weekly_yield_estimate > candidates[1].weekly_yield_estimate


def test_select_portfolio_respects_capital_cap():
    chain = [
        make_put("AAPL", 200, dte=7, delta=0.20, bid=2.0, ask=2.0),  # notional 20000
        make_put("MSFT", 200, dte=7, delta=0.20, bid=2.0, ask=2.0),  # notional 20000
        make_put("GOOG", 200, dte=7, delta=0.20, bid=2.0, ask=2.0),  # notional 20000
    ]
    config = StrategyConfig()
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)

    risk_config = RiskConfig(max_capital_at_risk=25000, max_risk_per_trade_pct=1.0,
                              max_concurrent_positions=10)
    engine = RiskEngine(risk_config)
    state = DailyState(date=TODAY)

    accepted = select_portfolio(candidates, engine, state)
    # Only one 20000-notional position fits under a 25000 cap
    assert len(accepted) == 1


def test_select_portfolio_diversifies_across_symbols():
    chain = [
        make_put("AAPL", 50, dte=7, delta=0.20, bid=1.0, ask=1.0),
        make_put("AAPL", 45, dte=7, delta=0.20, bid=0.9, ask=0.9),  # second AAPL contract
        make_put("MSFT", 50, dte=7, delta=0.20, bid=1.0, ask=1.0),
    ]
    config = StrategyConfig()
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)

    risk_config = RiskConfig(max_capital_at_risk=25000, max_risk_per_trade_pct=1.0,
                              max_concurrent_positions=10)
    engine = RiskEngine(risk_config)
    state = DailyState(date=TODAY)

    accepted = select_portfolio(candidates, engine, state, one_per_symbol=True)
    symbols = [c.symbol for c in accepted]
    assert len(symbols) == len(set(symbols))  # no duplicate underlyings


def test_select_portfolio_blocked_by_kill_switch():
    chain = [make_put("AAPL", 50, dte=7, delta=0.20, bid=1.0, ask=1.0)]
    config = StrategyConfig()
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)

    risk_config = RiskConfig(kill_switch=True)
    engine = RiskEngine(risk_config)
    state = DailyState(date=TODAY)

    accepted = select_portfolio(candidates, engine, state)
    assert accepted == []


def test_select_portfolio_respects_existing_open_positions():
    chain = [make_put("AAPL", 200, dte=7, delta=0.20, bid=2.0, ask=2.0)]  # notional 20000
    config = StrategyConfig()
    candidates = generate_candidates(chain, "cash_secured_put", config, as_of=TODAY)

    risk_config = RiskConfig(max_capital_at_risk=25000, max_risk_per_trade_pct=1.0)
    engine = RiskEngine(risk_config)
    # Already have a 10000 notional position open -- only 15000 of headroom left
    state = DailyState(
        date=TODAY,
        open_positions=[Position("TSLA", "cash_secured_put", 10000, 100, TODAY)],
    )

    accepted = select_portfolio(candidates, engine, state)
    # The 20000 notional candidate should NOT fit in the remaining 15000 headroom
    assert accepted == []
