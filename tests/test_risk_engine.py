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
    assert engine.validate_trade(state, "core_hold", proposed_notional=2000) is True


def test_kill_switch_blocks_everything():
    engine = make_engine(kill_switch=True)
    state = empty_state()
    with pytest.raises(RiskViolation, match="Kill switch"):
        engine.validate_trade(state, "core_hold", proposed_notional=100)


def test_daily_loss_limit_halts_trading():
    engine = make_engine(max_daily_loss=200)
    state = DailyState(date=date.today(), realized_pnl_today=-250)
    with pytest.raises(RiskViolation, match="Daily loss limit"):
        engine.validate_trade(state, "core_hold", proposed_notional=100)


def test_daily_loss_exactly_at_limit_halts():
    engine = make_engine(max_daily_loss=200)
    state = DailyState(date=date.today(), realized_pnl_today=-200)
    with pytest.raises(RiskViolation):
        engine.validate_trade(state, "core_hold", proposed_notional=100)


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
            Position("AAPL", "core_hold", 1000, 20, date.today()),
            Position("MSFT", "satellite_momentum", 1000, 20, date.today()),
        ],
    )
    with pytest.raises(RiskViolation, match="concurrent positions"):
        engine.validate_trade(state, "core_hold", proposed_notional=1000)


def test_capital_cap_blocked():
    engine = make_engine(max_capital_at_risk=5000, max_risk_per_trade_pct=1.0)
    state = DailyState(
        date=date.today(),
        open_positions=[Position("AAPL", "core_hold", 4000, 50, date.today())],
    )
    with pytest.raises(RiskViolation, match="exceeding cap"):
        engine.validate_trade(state, "core_hold", proposed_notional=1500)


def test_per_trade_risk_blocked():
    engine = make_engine(max_capital_at_risk=10000, max_risk_per_trade_pct=0.10)
    state = empty_state()
    # 15% of the cap, but limit is 10% per trade
    with pytest.raises(RiskViolation, match="per-trade risk"):
        engine.validate_trade(state, "core_hold", proposed_notional=1500)


def test_required_monthly_yield_math():
    engine = make_engine(monthly_income_target=100)
    assert engine.required_monthly_yield(1000) == pytest.approx(0.10)
    assert engine.required_monthly_yield(2000) == pytest.approx(0.05)


def test_required_monthly_yield_rejects_nonpositive_capital():
    engine = make_engine()
    with pytest.raises(ValueError):
        engine.required_monthly_yield(0)


def test_max_drawdown_blocked():
    engine = make_engine(max_drawdown_pct=0.25)
    equity_curve = [1000, 1100, 1200, 900, 850]  # 900/850 is a >25% drop from the 1200 peak
    with pytest.raises(RiskViolation, match="Max drawdown"):
        engine.check_max_drawdown(equity_curve)


def test_max_drawdown_within_limit_passes():
    engine = make_engine(max_drawdown_pct=0.25)
    equity_curve = [1000, 1100, 1200, 1000, 950]  # ~21% off peak, under the 25% limit
    engine.check_max_drawdown(equity_curve)  # should not raise


def test_max_drawdown_ignores_short_curves():
    engine = make_engine(max_drawdown_pct=0.25)
    engine.check_max_drawdown([1000])  # should not raise, nothing to compare
