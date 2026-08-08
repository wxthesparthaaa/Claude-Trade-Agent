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


def test_validate_trade_without_direction_arg_is_unaffected_by_short_checks():
    # direction defaults to "long" -- omitting it entirely (every pre-existing
    # call site in this codebase does) must behave exactly as before, even
    # with a short-exposure cap tight enough it would block an actual short.
    engine = make_engine(max_capital_at_risk=10000, max_risk_per_trade_pct=0.5,
                          max_short_exposure_pct=0.01, max_short_positions=0)
    state = empty_state()
    assert engine.validate_trade(state, "core_hold", proposed_notional=2000) is True


def test_short_exposure_cap_blocks_oversized_short():
    engine = make_engine(max_capital_at_risk=1000, max_risk_per_trade_pct=1.0,
                          max_short_exposure_pct=0.15, allowed_strategies=("satellite_short",))
    state = empty_state()
    with pytest.raises(RiskViolation, match="short-exposure cap"):
        engine.validate_trade(state, "satellite_short", proposed_notional=200, direction="short")


def test_short_exposure_cap_allows_short_within_cap():
    engine = make_engine(max_capital_at_risk=1000, max_risk_per_trade_pct=1.0,
                          max_short_exposure_pct=0.15, allowed_strategies=("satellite_short",))
    state = empty_state()
    assert engine.validate_trade(state, "satellite_short", proposed_notional=150, direction="short") is True


def test_short_exposure_aggregates_existing_shorts():
    engine = make_engine(max_capital_at_risk=1000, max_risk_per_trade_pct=1.0,
                          max_short_exposure_pct=0.15, max_short_positions=5,
                          allowed_strategies=("satellite_short",))
    state = DailyState(
        date=date.today(),
        open_positions=[Position("AMD", "satellite_short", 100, 0, date.today(), direction="short")],
    )
    # existing short (100) + proposed (60) = 160 > 150 cap (15% of 1000)
    with pytest.raises(RiskViolation, match="short-exposure cap"):
        engine.validate_trade(state, "satellite_short", proposed_notional=60, direction="short")


def test_max_short_positions_blocks_additional_short():
    engine = make_engine(max_capital_at_risk=10000, max_risk_per_trade_pct=1.0,
                          max_short_exposure_pct=1.0, max_short_positions=1,
                          allowed_strategies=("satellite_short",))
    state = DailyState(
        date=date.today(),
        open_positions=[Position("AMD", "satellite_short", 100, 0, date.today(), direction="short")],
    )
    with pytest.raises(RiskViolation, match="Max short positions"):
        engine.validate_trade(state, "satellite_short", proposed_notional=50, direction="short")


def test_long_positions_do_not_count_toward_short_exposure_cap():
    engine = make_engine(max_capital_at_risk=2000, max_risk_per_trade_pct=1.0,
                          max_short_exposure_pct=0.15, allowed_strategies=("satellite_short",))
    state = DailyState(
        date=date.today(),
        open_positions=[Position("NVDA", "satellite_momentum", 900, 0, date.today())],  # direction defaults "long"
    )
    # a big long position shouldn't count against the short-exposure cap
    # (150 <= 15% of 2000 = 300, and 900 + 150 = 1050 stays under the 2000 total cap)
    assert engine.validate_trade(state, "satellite_short", proposed_notional=150, direction="short") is True
