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


def test_reducing_trade_skips_capital_cap_and_per_trade_risk():
    """Reproduces a real trap: an account already over its capital cap
    (e.g. from a past bug) must still be able to sell its way back under
    it. Without increasing=False bypassing capital_cap/per_trade_risk, a
    SELL's own notional got added on top of already-committed capital,
    rejecting every order including the exact exits that would fix the
    overage."""
    engine = make_engine(max_capital_at_risk=5000, max_risk_per_trade_pct=0.10)
    # Already well over cap -- committed capital ($6000) alone exceeds
    # max_capital_at_risk ($5000), and the proposed notional (958) alone
    # would also fail the 10% per-trade-risk cap ($500) if it were
    # checked -- both would raise if this trade were treated as
    # increasing.
    state = DailyState(
        date=date.today(),
        open_positions=[Position("AEHR", "satellite_momentum", 6000, 50, date.today())],
    )
    assert engine.validate_trade(state, "satellite_momentum", proposed_notional=958, increasing=False) is True


def test_increasing_defaults_to_true_so_existing_callers_are_unaffected():
    engine = make_engine(max_capital_at_risk=5000, max_risk_per_trade_pct=1.0)
    state = DailyState(
        date=date.today(),
        open_positions=[Position("AAPL", "core_hold", 4000, 50, date.today())],
    )
    with pytest.raises(RiskViolation, match="exceeding cap"):
        engine.validate_trade(state, "core_hold", proposed_notional=1500)  # increasing not passed -> still True


def test_reducing_trade_still_blocked_by_checks_unrelated_to_capital_flow():
    """increasing=False must not become a blanket bypass -- concurrent-
    positions, kill-switch, daily-loss, and strategy-allowlist checks
    are about current state, not this trade's own capital flow, so they
    still apply regardless of direction."""
    engine = make_engine(kill_switch=True)
    state = empty_state()
    with pytest.raises(RiskViolation, match="Kill switch"):
        engine.validate_trade(state, "core_hold", proposed_notional=100, increasing=False)


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


def test_max_drawdown_releases_after_recovering_from_a_past_breach():
    """A permanent, non-releasing halt from a single historical bad day
    would disable the strategy forever, since scan_workflow.py calls
    this every scan with the account's full history. This is the real
    circuit-breaker behavior: it fires when CURRENTLY in a big drawdown
    and releases once capital recovers, even though the curve still
    contains an earlier >25% breach point."""
    engine = make_engine(max_drawdown_pct=0.25)
    equity_curve = [1000, 1100, 1200, 700, 1150]  # 700 was a 41.7% breach, but current (1150) has recovered
    engine.check_max_drawdown(equity_curve)  # should not raise -- current drawdown from peak is back under 25%


def test_max_drawdown_still_blocks_while_currently_in_a_breach_even_after_an_earlier_dip():
    """The release must not overshoot into leniency -- if capital is
    STILL down past the threshold right now, it halts regardless of
    what happened earlier in the curve."""
    engine = make_engine(max_drawdown_pct=0.25)
    equity_curve = [1000, 1100, 1200, 700, 800]  # recovered from 700 but still 33% off the 1200 peak
    with pytest.raises(RiskViolation, match="Max drawdown"):
        engine.check_max_drawdown(equity_curve)


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
