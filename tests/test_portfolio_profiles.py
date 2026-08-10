"""
Run with:
    pytest tests/test_portfolio_profiles.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import portfolio_profiles
from portfolio_profiles import (
    GROWTH_PROFILE, DIVIDEND_PROFILE, ALL_PROFILES, ACTIVE_PROFILES,
    get_profile, assert_universes_disjoint, _build_dividend_profile,
)
from universe import UniverseEntry


def test_growth_profile_defaults():
    assert GROWTH_PROFILE.name == "growth"
    assert GROWTH_PROFILE.initial_capital == 1000.0
    assert GROWTH_PROFILE.allow_short is True
    assert GROWTH_PROFILE.active is True
    assert "satellite_short" in GROWTH_PROFILE.risk_config.allowed_strategies


def test_growth_profile_has_confidence_gating_enabled():
    assert GROWTH_PROFILE.confidence_scale == 0.15
    assert GROWTH_PROFILE.journal_path.endswith("trade_journal.json")


def test_dividend_profile_has_confidence_gating_disabled():
    assert DIVIDEND_PROFILE.confidence_scale is None
    assert DIVIDEND_PROFILE.journal_path.endswith("trade_journal_dividend.json")


def test_dividend_profile_inactive_when_env_var_unset(monkeypatch):
    monkeypatch.delenv(portfolio_profiles.DIVIDEND_PORTFOLIO_CAPITAL_ENV, raising=False)
    profile = _build_dividend_profile()
    assert profile.active is False
    assert profile.initial_capital == 0.0
    assert profile.risk_config.max_capital_at_risk == 0.0


def test_dividend_profile_activates_when_funded(monkeypatch):
    monkeypatch.setenv(portfolio_profiles.DIVIDEND_PORTFOLIO_CAPITAL_ENV, "30000")
    profile = _build_dividend_profile()
    assert profile.active is True
    assert profile.initial_capital == 30000.0
    assert profile.risk_config.max_capital_at_risk == 30000.0


def test_dividend_profile_treats_malformed_env_var_as_unfunded(monkeypatch):
    monkeypatch.setenv(portfolio_profiles.DIVIDEND_PORTFOLIO_CAPITAL_ENV, "not-a-number")
    profile = _build_dividend_profile()
    assert profile.active is False
    assert profile.initial_capital == 0.0


def test_dividend_profile_excludes_growth_strategies():
    assert DIVIDEND_PROFILE.risk_config.allowed_strategies == ("core_hold",)
    assert DIVIDEND_PROFILE.allow_short is False


def test_dividend_profile_scores_yield_first():
    assert DIVIDEND_PROFILE.scoring_weights == {"momentum": 0.2, "div_yield": 0.7, "news_tilt": 0.1}


def test_growth_profile_uses_default_scoring_weights():
    assert GROWTH_PROFILE.scoring_weights is None


def test_dividend_profile_single_sleeve_config():
    config = DIVIDEND_PROFILE.portfolio_config
    assert config.core_pct == 1.0
    assert config.satellite_pct == 0.0
    assert config.max_satellite_positions == 0


def test_growth_and_dividend_state_paths_are_distinct():
    assert GROWTH_PROFILE.ledger_path != DIVIDEND_PROFILE.ledger_path
    assert GROWTH_PROFILE.decision_log_path != DIVIDEND_PROFILE.decision_log_path
    assert GROWTH_PROFILE.snapshot_path != DIVIDEND_PROFILE.snapshot_path
    assert GROWTH_PROFILE.pending_approvals_path != DIVIDEND_PROFILE.pending_approvals_path


def test_real_profiles_have_disjoint_universes():
    assert_universes_disjoint(ALL_PROFILES)  # should not raise


def test_assert_universes_disjoint_raises_on_overlap():
    a = GROWTH_PROFILE.__class__(
        name="a", initial_capital=1000.0, universe=[UniverseEntry("AAA", "US", "USD", "", "core")],
        portfolio_config=GROWTH_PROFILE.portfolio_config, risk_config=GROWTH_PROFILE.risk_config,
        allow_short=False, active=True, ledger_path="a.json", decision_log_path="a2.json",
        snapshot_path="a3.json", pending_approvals_path="a4.json", journal_path="a5.json",
    )
    b = GROWTH_PROFILE.__class__(
        name="b", initial_capital=1000.0, universe=[UniverseEntry("AAA", "US", "USD", "", "core")],
        portfolio_config=GROWTH_PROFILE.portfolio_config, risk_config=GROWTH_PROFILE.risk_config,
        allow_short=False, active=True, ledger_path="b.json", decision_log_path="b2.json",
        snapshot_path="b3.json", pending_approvals_path="b4.json", journal_path="b5.json",
    )
    with pytest.raises(AssertionError, match="AAA"):
        assert_universes_disjoint([a, b])


def test_get_profile_returns_correct_profile():
    assert get_profile("growth") is GROWTH_PROFILE
    assert get_profile("dividend") is DIVIDEND_PROFILE


def test_get_profile_raises_on_unknown_name():
    with pytest.raises(ValueError, match="Unknown portfolio profile"):
        get_profile("crypto")


def test_active_profiles_only_includes_active_ones():
    for profile in ACTIVE_PROFILES:
        assert profile.active is True
