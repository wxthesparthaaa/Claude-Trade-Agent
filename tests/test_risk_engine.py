"""
Run with:
    pytest tests/test_risk_engine.py -v

These tests exist to prove the risk engine actually blocks what it claims
to block. If any of these fail after a code change, do not "fix the test"
to make it pass -- the risk logic itself has regressed.
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from risk_engine import RiskConfig, RiskEngine, RiskViolation, DailyState, Position


def make_engine(**overrides):
    config = RiskConfig(**overrides)
    return RiskEngine(config)


def empty_state():
    return DailyState(date=date.today())


def test_trade_within_limits_passes():
    engine = make_engine(max_capital_at_risk=10000, max_risk_per_trade_pct=0.5)
    state = empty_state()
    assert engine.validate_trade(state, "cash_secured_put", proposed_notional=2000) is True


def test_kill_switch_blocks_everything():
    engine = make_engine(kill_switch=True)
    state = empty_state()
    with pytest.raises(RiskViolation, match="Kill switch"):
        engine.validate_trade(state, "cash_secured_put", proposed_notional=100)


def test_daily_loss_limit_halts_trading():
    engine = make_engine(max_daily_loss=200)
    state = DailyState(date=date.today(), realized_pnl_today=-250)
    with pytest.raises(RiskViolation, match="Daily loss limit"):
        engine.validate_trade(state, "cash_secured_put", proposed_notional=100)


def test_daily_loss_exactly_at_limit_halts():
    engine = make_engine(max_daily_loss=200)
    state = DailyState(date=date.today(), realized_pnl_today=-200)
    with pytest.raises(RiskViolation):
        engine.validate_trade(state, "cash_secured_put", proposed_notional=100)


def test_disallowed_strategy_blocked():
    engine = make_engine()
    state = empty_state()
    with pytest.raises(RiskViolation, match="not in the allowed list"):
        engine.validate_trade(state, "naked_call", proposed_notional=100)


def test_max_concurrent_positions_blocked():
    engine = make_engine(max_concurrent_positions=2, max_capital_at_risk=100000)
    state = DailyState(
        date=date.today(),
        open_positions=[
            Position("AAPL", "cash_secured_put", 1000, 20, date.today()),
            Position("MSFT", "covered_call", 1000, 20, date.today()),
        ],
    )
    with pytest.raises(RiskViolation, match="concurrent positions"):
        engine.validate_trade(state, "cash_secured_put", proposed_notional=1000)


def test_capital_cap_blocked():
    engine = make_engine(max_capital_at_risk=5000, max_risk_per_trade_pct=1.0)
    state = DailyState(
        date=date.today(),
        open_positions=[Position("AAPL", "cash_secured_put", 4000, 50, date.today())],
    )
    with pytest.raises(RiskViolation, match="exceeding cap"):
        engine.validate_trade(state, "cash_secured_put", proposed_notional=1500)


def test_per_trade_risk_blocked():
    engine = make_engine(max_capital_at_risk=10000, max_risk_per_trade_pct=0.10)
    state = empty_state()
    # 15% of the cap, but limit is 10% per trade
    with pytest.raises(RiskViolation, match="per-trade risk"):
        engine.validate_trade(state, "cash_secured_put", proposed_notional=1500)


def test_required_weekly_yield_math():
    engine = make_engine(weekly_income_target=100)
    assert engine.required_weekly_yield(10000) == pytest.approx(0.01)
    assert engine.required_weekly_yield(2000) == pytest.approx(0.05)


def test_required_weekly_yield_rejects_nonpositive_capital():
    engine = make_engine()
    with pytest.raises(ValueError):
        engine.required_weekly_yield(0)
