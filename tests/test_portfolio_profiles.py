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
    effective_universe, validate_new_universe_entry,
)
from universe import UniverseEntry
from universe_extra import ExtraUniverseEntry, save_extra_universe


def test_growth_profile_defaults():
    assert GROWTH_PROFILE.name == "growth"
    assert GROWTH_PROFILE.initial_capital == 1000.0
    assert GROWTH_PROFILE.allow_short is True
    assert GROWTH_PROFILE.active is True
    assert "satellite_short" in GROWTH_PROFILE.risk_config.allowed_strategies


def test_growth_profile_has_confidence_gating_enabled():
    assert GROWTH_PROFILE.confidence_scale == 0.15
    assert GROWTH_PROFILE.journal_path.endswith("trade_journal.json")


def test_dividend_profile_has_confidence_gating_enabled():
    # Calibrated against real decision_log_dividend.json history (23 scored
    # decisions, range ~0.0058-0.0838) -- see portfolio_profiles.py's comment.
    assert DIVIDEND_PROFILE.confidence_scale == 0.06
    assert DIVIDEND_PROFILE.journal_path.endswith("trade_journal_dividend.json")


def test_growth_and_dividend_settings_and_shortlist_paths_are_distinct():
    assert GROWTH_PROFILE.scan_settings_path != DIVIDEND_PROFILE.scan_settings_path
    assert GROWTH_PROFILE.shortlist_path != DIVIDEND_PROFILE.shortlist_path
    assert GROWTH_PROFILE.changelog_path != DIVIDEND_PROFILE.changelog_path
    assert GROWTH_PROFILE.paused_symbols_path != DIVIDEND_PROFILE.paused_symbols_path


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
        changelog_path="a6.json", scan_settings_path="a7.json", shortlist_path="a8.json",
        paused_symbols_path="a9.json", extra_universe_path="a10.json", sector_suggestions_path="a11.json",
    )
    b = GROWTH_PROFILE.__class__(
        name="b", initial_capital=1000.0, universe=[UniverseEntry("AAA", "US", "USD", "", "core")],
        portfolio_config=GROWTH_PROFILE.portfolio_config, risk_config=GROWTH_PROFILE.risk_config,
        allow_short=False, active=True, ledger_path="b.json", decision_log_path="b2.json",
        snapshot_path="b3.json", pending_approvals_path="b4.json", journal_path="b5.json",
        changelog_path="b6.json", scan_settings_path="b7.json", shortlist_path="b8.json",
        paused_symbols_path="b9.json", extra_universe_path="b10.json", sector_suggestions_path="b11.json",
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


# ---- effective_universe -------------------------------------------------

def test_effective_universe_equals_static_universe_when_no_extras(tmp_path, monkeypatch):
    monkeypatch.setattr(GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "does_not_exist.json"))
    assert effective_universe(GROWTH_PROFILE) == list(GROWTH_PROFILE.universe)


def test_effective_universe_appends_approved_extras(tmp_path, monkeypatch):
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(GROWTH_PROFILE, "extra_universe_path", path)
    save_extra_universe(path, [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite",
                            added_at="2026-08-16", source_sector="Financials"),
    ])

    result = effective_universe(GROWTH_PROFILE)

    assert len(result) == len(GROWTH_PROFILE.universe) + 1
    assert result[-1] == UniverseEntry("JPM", "US", "USD", "", "satellite")


def test_effective_universe_never_mutates_the_static_universe_list(tmp_path, monkeypatch):
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(GROWTH_PROFILE, "extra_universe_path", path)
    save_extra_universe(path, [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite", added_at="2026-08-16"),
    ])
    original_length = len(GROWTH_PROFILE.universe)

    effective_universe(GROWTH_PROFILE)

    assert len(GROWTH_PROFILE.universe) == original_length  # untouched -- profile.universe itself never grows


# ---- validate_new_universe_entry -------------------------------------------------

def test_validate_new_universe_entry_allows_a_genuinely_new_symbol():
    validate_new_universe_entry("ZZZZ_NOT_A_REAL_SYMBOL", GROWTH_PROFILE)  # must not raise


def test_validate_new_universe_entry_rejects_a_symbol_already_in_the_same_profile():
    existing_symbol = GROWTH_PROFILE.universe[0].symbol
    with pytest.raises(ValueError, match="already in the 'growth' portfolio"):
        validate_new_universe_entry(existing_symbol, GROWTH_PROFILE)


def test_validate_new_universe_entry_rejects_a_symbol_already_in_the_other_profile():
    existing_dividend_symbol = DIVIDEND_PROFILE.universe[0].symbol
    with pytest.raises(ValueError, match="already in the 'dividend' portfolio"):
        validate_new_universe_entry(existing_dividend_symbol, GROWTH_PROFILE)


def test_validate_new_universe_entry_rejects_a_symbol_already_approved_as_an_extra(tmp_path, monkeypatch):
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(DIVIDEND_PROFILE, "extra_universe_path", path)
    save_extra_universe(path, [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="core", added_at="2026-08-16"),
    ])

    with pytest.raises(ValueError, match="already in the 'dividend' portfolio"):
        validate_new_universe_entry("JPM", GROWTH_PROFILE)
