"""
Run with:
    pytest tests/test_app.py -v

RUN_SCHEDULER=false is set before importing app, so these tests never
start the real background scheduler or touch the network.
"""
import sys
import os

os.environ["RUN_SCHEDULER"] = "false"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import app as app_module


@pytest.fixture(autouse=True)
def _reset_telegram_dedupe_cache():
    """_send_telegram_if_changed's cache is process-lifetime, module-level
    state -- without a reset it leaks between tests in this file (e.g. a
    later test reusing the same pending-item text as an earlier one would
    silently skip the send instead of exercising its own path)."""
    app_module._last_sent_telegram.clear()
    yield
    app_module._last_sent_telegram.clear()


def test_health_endpoint():
    client = app_module.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_no_unexpected_routes_exist():
    rules = [str(r) for r in app_module.app.url_map.iter_rules()]
    assert set(rules) == {
        "/static/<path:filename>",
        "/health",
        "/",
        "/scan",
        "/settings",
        "/settings/reset-capital",
        "/review",
        "/news",
        "/news/refresh",
        "/positions/<symbol>/close",
        "/approve/<approval_id>",
        "/universe/add",
        "/universe/remove",
    }


def test_approve_route_only_places_order_on_post():
    methods = set()
    for r in app_module.app.url_map.iter_rules():
        if str(r) == "/approve/<approval_id>":
            methods |= r.methods
    assert "GET" in methods
    assert "POST" in methods


def test_dashboard_renders_with_no_state_present(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "portfolio_snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Total Capital" in text
    assert "$1000.00" in text or "$1,000.00" in text
    assert "Live data unavailable" in text


def test_dashboard_shows_monthly_gain_vs_target_for_growth(tmp_path, monkeypatch):
    from strategy_ledger import load_or_init_ledger, record_snapshot

    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "portfolio_snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))

    from datetime import date, timedelta
    load_or_init_ledger(ledger_path, 1000.0)
    month_ago = (date.today() - timedelta(days=35)).isoformat()
    record_snapshot(ledger_path, capital=1000.0, as_of=month_ago)
    record_snapshot(ledger_path, capital=1120.0, as_of=date.today().isoformat())  # +12% over the trailing 30 days

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Monthly Gain" in text
    assert "+12.0%" in text
    assert "vs 10% target" in text


def test_dashboard_shows_auto_paused_symbols(tmp_path, monkeypatch):
    from self_improvement import SelfImprovementState, save_self_improvement_state

    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "portfolio_snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))
    paused_symbols_path = str(tmp_path / "paused_symbols.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "paused_symbols_path", paused_symbols_path)
    save_self_improvement_state(paused_symbols_path, SelfImprovementState(paused_symbols={"NVDA": "2026-08-01"}))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Auto-paused symbols" in text
    assert "NVDA" in text
    assert "resumes 2026-08-15" in text


def test_dashboard_shows_developer_notes_panel(monkeypatch):
    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)
    monkeypatch.setattr(app_module, "DEVELOPER_NOTES", [("2026-08-15", "A test-only note.")])

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Developer notes" in text
    assert "A test-only note." in text
    assert "2026-08-15" in text


def test_dashboard_shows_recently_executed_trades_only(tmp_path, monkeypatch):
    """Regression coverage for the real point of confusion: 'Most recent
    decisions' (decision_log.json) includes shortlisted/rejected
    candidates that were never actually traded -- 'Recently executed
    trades' must be a separate, real-fills-only panel sourced from
    trade_journal.json instead."""
    from trade_journal import JournalEntry, save_journal

    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "portfolio_snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))
    journal_path = str(tmp_path / "journal.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "journal_path", journal_path)
    save_journal(journal_path, [JournalEntry(
        symbol="NVDA", sleeve="satellite", position_type="long", quantity=7, entry_price=220.01,
        confidence_pct=81.4, reason="top satellite pick", opened_at="2026-08-12T14:13:57+00:00",
        status="OPEN",
    )])

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Recently executed trades" in text
    assert "NVDA" in text
    assert "7 @ $220.01" in text
    assert "OPEN" in text
    assert "2026-08-12" in text
    # The clarifying caption distinguishing it from the full rationale trail.
    assert "not just trades that were actually" in text


def _isolate_profile_state(monkeypatch, profile, tmp_path, suffix=""):
    monkeypatch.setattr(profile, "ledger_path", str(tmp_path / f"ledger{suffix}.json"))
    monkeypatch.setattr(profile, "snapshot_path", str(tmp_path / f"snapshot{suffix}.json"))
    monkeypatch.setattr(profile, "decision_log_path", str(tmp_path / f"decision_log{suffix}.json"))


def test_dashboard_shows_sector_rotation_empty_state(tmp_path, monkeypatch):
    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Where money is flowing" in text
    assert "No data yet" in text
    assert "Investment Clock hasn&#39;t run yet" in text or "Investment Clock hasn't run yet" in text
    assert "Sector opportunities" in text
    assert "No new candidates surfaced yet" in text
    assert "Approved additions" not in text  # section is hidden entirely when there are none


def test_dashboard_shows_ranked_sectors_and_investment_clock(tmp_path, monkeypatch):
    from sector_rotation import SectorRotationSignal, SectorRankEntry, save_sector_rotation
    from investment_clock import InvestmentClockSignal, save_investment_clock

    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    rotation_path = str(tmp_path / "sector_rotation.json")
    clock_path = str(tmp_path / "investment_clock.json")
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", rotation_path)
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", clock_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))

    save_sector_rotation(rotation_path, {
        "US": SectorRotationSignal(as_of="2026-08-16", region="US", method="sector_etf", entries=[
            SectorRankEntry("Technology", "45", "XLK", "broadening", 0.031, 1.4, 1),
        ]),
        "SG": SectorRotationSignal(as_of="2026-08-16", region="SG", method="unavailable", entries=[],
                                    note="Sector classification isn't available for SG through Tiger's API (confirmed unsupported)."),
    })
    save_investment_clock(clock_path, InvestmentClockSignal(
        as_of="2026-08-16", region="US", quadrant="Recovery", growth_trend="rising", inflation_trend="falling",
        growth_value=105.0, inflation_value=2.1, best_sectors=["Technology", "Consumer Discretionary", "Industrials"],
    ))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "#1 Technology" in text
    assert "[XLK]" in text
    assert "+3.10%" in text
    assert "Recovery" in text
    assert "Technology, Consumer Discretionary, Industrials" in text
    assert "confirmed unsupported" in text  # SG's explicit gap note


def test_dashboard_shows_sector_opportunities_with_add_form(tmp_path, monkeypatch):
    from sector_suggestions import SectorSuggestion, save_suggestions

    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    suggestions_path = str(tmp_path / "sector_suggestions.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", suggestions_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))
    save_suggestions(suggestions_path, [
        SectorSuggestion(symbol="JPM", market="US", sector_name="Financials", gics_sector_id="40",
                          discovered_at="2026-08-16", reason="Financials is hot; JPM is liquid and untracked."),
    ])

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Sector opportunities (1)" in text
    assert "JPM" in text
    assert "Financials is hot" in text
    assert '/universe/add?portfolio=growth' in text


def test_dashboard_shows_approved_additions_with_remove_form(tmp_path, monkeypatch):
    from universe_extra import ExtraUniverseEntry, save_extra_universe

    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions.json"))
    extra_path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", extra_path)
    save_extra_universe(extra_path, [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite",
                            added_at="2026-08-16", source_sector="Financials"),
    ])

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Approved additions (1)" in text
    assert "JPM" in text
    assert "added 2026-08-16 from Financials" in text
    assert '/universe/remove?portfolio=growth' in text


def test_dashboard_shows_todays_movers_panel_for_growth(tmp_path, monkeypatch):
    from movers import MoversSignal, MoverEntry, save_movers

    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))
    movers_path = str(tmp_path / "movers.json")
    monkeypatch.setattr(app_module, "MOVERS_PATH", movers_path)
    save_movers(movers_path, {
        "US": MoversSignal(as_of="2026-08-19", region="US", entries=[
            MoverEntry(symbol="NVDA", name="NVIDIA", change_rate=0.05, rank=1),
        ]),
    })

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Today's movers" in text
    assert "#1 NVDA" in text
    assert "+5.00%" in text


def test_dashboard_hides_todays_movers_panel_for_dividend(tmp_path, monkeypatch):
    """Movers/auto-add are growth-only -- dividend's dashboard shouldn't
    show the panel at all, even if movers.json has real data in it."""
    from movers import MoversSignal, MoverEntry, save_movers

    _isolate_profile_state(monkeypatch, app_module.DIVIDEND_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe_dividend.json"))
    movers_path = str(tmp_path / "movers.json")
    monkeypatch.setattr(app_module, "MOVERS_PATH", movers_path)
    save_movers(movers_path, {
        "US": MoversSignal(as_of="2026-08-19", region="US", entries=[
            MoverEntry(symbol="NVDA", name="NVIDIA", change_rate=0.05, rank=1),
        ]),
    })

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=dividend")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Today's movers" not in text


def test_dashboard_marks_auto_added_entries_in_approved_additions(tmp_path, monkeypatch):
    from universe_extra import ExtraUniverseEntry, save_extra_universe

    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions.json"))
    extra_path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", extra_path)
    save_extra_universe(extra_path, [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite",
                            added_at="2026-08-19", source_sector="Financials", auto_added=True),
        ExtraUniverseEntry(symbol="XOM", market="US", currency="USD", exchange="", sleeve="satellite",
                            added_at="2026-08-19", source_sector="Energy", auto_added=False),
    ])

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    text = response.get_data(as_text=True)
    assert text.count("auto-added") == 1  # only JPM, not XOM


def test_dashboard_shows_weekly_gain_chart(tmp_path, monkeypatch):
    from strategy_ledger import load_or_init_ledger, record_snapshot
    from datetime import date, timedelta

    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))

    ledger_path = app_module.GROWTH_PROFILE.ledger_path
    load_or_init_ledger(ledger_path, 1000.0)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    record_snapshot(ledger_path, capital=1000.0, as_of=monday.isoformat())
    record_snapshot(ledger_path, capital=1050.0, as_of=today.isoformat())

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "This week's gain" in text
    assert 'id="weeklyGainChart"' in text


def test_dashboard_shows_dividends_earned_panel_for_dividend(tmp_path, monkeypatch):
    from dividend_tracker import DividendSummary, DividendPayment, save_dividends_earned

    _isolate_profile_state(monkeypatch, app_module.DIVIDEND_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe_dividend.json"))
    div_path = str(tmp_path / "dividends_earned.json")
    monkeypatch.setattr(app_module, "DIVIDENDS_EARNED_PATH", div_path)
    save_dividends_earned(div_path, DividendSummary(
        as_of="2026-08-20", year=2026, total_by_currency={"USD": 42.50},
        payments=[DividendPayment(symbol="VYM", amount_per_share=0.85, shares_held=10, total_amount=8.5,
                                   currency="USD", ex_date="2026-06-15", pay_date="2026-06-20")],
    ))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=dividend")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Dividends Earned (2026)" in text
    assert "42.50 USD" in text
    assert "VYM" in text
    assert "0.8500/share" in text


def test_dashboard_hides_dividends_earned_panel_for_growth(tmp_path, monkeypatch):
    """Dividend tracking is dividend-only -- growth's dashboard
    shouldn't show it at all, even if dividends_earned.json exists."""
    from dividend_tracker import DividendSummary, save_dividends_earned

    _isolate_profile_state(monkeypatch, app_module.GROWTH_PROFILE, tmp_path)
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", str(tmp_path / "sector_rotation.json"))
    monkeypatch.setattr(app_module, "INVESTMENT_CLOCK_PATH", str(tmp_path / "investment_clock.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "sector_suggestions_path", str(tmp_path / "sector_suggestions.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))
    div_path = str(tmp_path / "dividends_earned.json")
    monkeypatch.setattr(app_module, "DIVIDENDS_EARNED_PATH", div_path)
    save_dividends_earned(div_path, DividendSummary(as_of="2026-08-20", year=2026, total_by_currency={"USD": 42.50}))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    text = response.get_data(as_text=True)
    assert "Dividends Earned" not in text


def test_home_overview_shows_sector_rotation_panel(monkeypatch):
    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Where money is flowing" in text
    assert "United States" in text
    assert "Hong Kong" in text
    assert "Singapore" in text
    assert "Sectors" in text


def test_home_overview_hides_industries_that_only_repeat_their_sector(tmp_path, monkeypatch):
    """A thin-sample region (e.g. one tagged stock per sector, so its
    industry average is identical to the sector average) shouldn't show
    that industry as if it were new information -- see
    sector_rotation.distinct_industries. A sector that genuinely splits
    into more than one industry group should still show."""
    from sector_rotation import SectorRotationSignal, SectorRankEntry, IndustryRankEntry, save_sector_rotation

    rotation_path = str(tmp_path / "sector_rotation.json")
    monkeypatch.setattr(app_module, "SECTOR_ROTATION_PATH", rotation_path)
    save_sector_rotation(rotation_path, {
        "HK": SectorRotationSignal(
            as_of="2026-08-16", region="HK", method="gics_aggregate",
            entries=[
                SectorRankEntry("Financials", "40", None, "", 0.17, 0.0, 1),
                SectorRankEntry("Consumer Discretionary", "25", None, "", -0.16, 0.0, 2),
            ],
            industries=[
                IndustryRankEntry("Banks", "4010", "Financials", 0.17, 1),
                IndustryRankEntry("Consumer Services", "2530", "Consumer Discretionary", -0.06, 2),
                IndustryRankEntry("Consumer Discretionary Distribution & Retail", "2550", "Consumer Discretionary", -0.26, 3),
            ],
        ),
    })

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/")
    text = response.get_data(as_text=True)
    assert "#1 Banks" not in text  # only industry under Financials -- redundant with the sector line, hidden
    assert "Consumer Services" in text  # Consumer Discretionary genuinely splits into two -- both shown
    assert "Consumer Discretionary Distribution &amp; Retail" in text


def test_dashboard_recently_executed_trades_empty_state(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "portfolio_snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "journal_path", str(tmp_path / "journal.json"))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "No trades executed yet" in text


def test_developer_notes_capped_at_five_entries():
    assert len(app_module.DEVELOPER_NOTES) <= 5


def test_dashboard_shows_monthly_gain_vs_annual_target_for_dividend(tmp_path, monkeypatch):
    """Dividend's target is 10%/year (much lower-turnover than growth's
    10%/month) -- the card must say so, per the user's explicit request
    that dividend mirror growth's format with its own annual target."""
    from strategy_ledger import load_or_init_ledger, record_snapshot

    ledger_path = str(tmp_path / "ledger_dividend.json")
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", True)
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "snapshot_path", str(tmp_path / "snapshot_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "decision_log_path", str(tmp_path / "decision_log_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "pending_approvals_path", str(tmp_path / "pending_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "shortlist_path", str(tmp_path / "shortlist_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "changelog_path", str(tmp_path / "changelog_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "initial_capital", 30000.0)

    from datetime import date, timedelta
    load_or_init_ledger(ledger_path, 30000.0)
    month_ago = (date.today() - timedelta(days=35)).isoformat()
    record_snapshot(ledger_path, capital=30000.0, as_of=month_ago)
    record_snapshot(ledger_path, capital=30060.0, as_of=date.today().isoformat())  # +0.2% over the trailing 30 days

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=dividend")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Monthly Gain" in text
    assert "+0.2%" in text
    assert "vs 10% target per year" in text


def test_dashboard_shows_live_positions_when_tiger_reachable(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "portfolio_snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))

    class FakeContract:
        symbol = "NVDA"

    class FakePosition:
        contract = FakeContract()
        quantity = 2
        average_cost = 100.0
        market_price = 120.0
        market_value = 240.0
        unrealized_pnl = 40.0
        unrealized_pnl_percent = 0.20

    class FakeTradeClient:
        def get_positions(self):
            return [FakePosition()]

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "NVDA" in text
    assert "Live data unavailable" not in text
    # cash_reserve (1000, no trades yet) + live market value (240) = 1240
    assert "$1240.00" in text or "$1,240.00" in text


def test_dashboard_dividend_portfolio_shows_inactive_state_when_unfunded(monkeypatch):
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", False)
    client = app_module.app.test_client()
    response = client.get("/?portfolio=dividend")
    assert response.status_code == 200


def test_bare_root_defaults_to_home_overview_not_growth(monkeypatch):
    """Bare '/' (no ?portfolio=) must render the combined home overview,
    not silently fall back to growth the way it used to -- see the
    dashboard() route's docstring comment."""
    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Growth Portfolio" in text
    assert "Dividend Portfolio" in text
    # Growth's own full dashboard has a Settings panel and a Scan Now
    # button; the overview must not be that page under a different name.
    assert "Scan Now" not in text


def test_home_overview_shows_a_one_liner_per_position(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", str(tmp_path / "pending.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "paused_symbols_path", str(tmp_path / "paused.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", False)  # keep this test scoped to growth only

    class FakeContract:
        symbol = "NVDA"

    class FakePosition:
        contract = FakeContract()
        quantity = 2
        average_cost = 100.0
        market_price = 120.0
        market_value = 240.0
        unrealized_pnl = 40.0
        unrealized_pnl_percent = 0.20

    class FakeTradeClient:
        def get_positions(self):
            return [FakePosition()]

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "NVDA" in text
    assert "2 @ $120.00" in text
    assert "+20.0%" in text
    assert "Not yet funded" in text  # dividend, forced inactive above


def test_scheduled_pull_state_swallows_errors(monkeypatch, capsys):
    def raise_error():
        raise RuntimeError("network down")
    monkeypatch.setattr(app_module, "pull_state_from_github", raise_error)

    app_module.scheduled_pull_state()  # must not raise
    assert "State pull failed" in capsys.readouterr().out


def test_scheduled_pull_state_reports_when_files_pulled(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "pull_state_from_github", lambda: 3)
    app_module.scheduled_pull_state()
    assert "Pulled 3 state file(s)" in capsys.readouterr().out


def test_scheduled_refresh_snapshot_swallows_errors(monkeypatch, capsys):
    def raise_error(*a, **k):
        raise RuntimeError("tiger api down")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    app_module.scheduled_refresh_snapshot()  # must not raise
    assert "Snapshot refresh failed" in capsys.readouterr().out


def test_scheduled_daily_update_swallows_errors_per_profile(monkeypatch, capsys):
    def raise_error(profile):
        raise RuntimeError("telegram down")
    monkeypatch.setattr(app_module, "run_daily_update", raise_error)

    app_module.scheduled_daily_update()  # must not raise
    assert "Daily update failed for 'growth'" in capsys.readouterr().out


def test_scheduled_weekly_review_swallows_errors(monkeypatch, capsys):
    def raise_error():
        raise RuntimeError("telegram down")
    monkeypatch.setattr(app_module, "run_weekly_review", raise_error)

    app_module.scheduled_weekly_review()  # must not raise
    assert "Weekly review failed" in capsys.readouterr().out


def test_scheduled_us_open_scan_swallows_errors_per_profile(monkeypatch, capsys):
    def raise_error(profile):
        raise RuntimeError("tiger api down")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", raise_error)

    app_module.scheduled_us_open_scan()  # must not raise
    assert "Scheduled scan failed for 'growth'" in capsys.readouterr().out


def test_scheduled_us_open_scan_reports_pending_count(monkeypatch, capsys):
    class FakeResult:
        approved_instructions = ["a", "b"]
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: FakeResult())

    app_module.scheduled_us_open_scan()
    assert "'growth' scan complete: 2 instruction(s) pending approval" in capsys.readouterr().out


def test_scheduled_us_open_scan_only_runs_active_profiles(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    class FakeResult:
        approved_instructions = []

    def fake_scan(profile):
        calls.append(profile.name)
        return FakeResult()
    monkeypatch.setattr(app_module, "_run_and_persist_scan", fake_scan)

    app_module.scheduled_us_open_scan()
    assert calls == ["growth"]


def test_scheduled_asia_hours_scan_sends_telegram_when_items_pending(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

    pending_path = str(tmp_path / "pending.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "shortlist_path", str(tmp_path / "shortlist.json"))  # isolate from real disk state
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    def fake_scan(profile):
        write_pending_approvals(pending_path, [PendingApproval(**_sample_pending_item())], scan_id="2026-08-12")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", fake_scan)

    sent = []
    monkeypatch.setattr(app_module, "get_telegram_config", lambda: type("C", (), {"bot_token": "t", "chat_id": "c"})())
    monkeypatch.setattr(app_module, "send_message", lambda text, token, chat_id: sent.append(text))

    app_module.scheduled_asia_hours_scan()

    assert len(sent) == 1  # no shortlist file -> only the pending-approvals message
    assert "NVDA" in sent[0]


def test_scheduled_asia_hours_scan_sends_nothing_when_no_pending_items(tmp_path, monkeypatch):
    pending_path = str(tmp_path / "pending.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "shortlist_path", str(tmp_path / "shortlist.json"))  # isolate from real disk state
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: None)

    def fail_if_called(*a, **k):
        raise AssertionError("must not send a Telegram alert when there's nothing pending or shortlisted")
    monkeypatch.setattr(app_module, "get_telegram_config", fail_if_called)

    app_module.scheduled_asia_hours_scan()  # must not raise


def test_scheduled_asia_hours_scan_sends_shortlist_digest_when_present(tmp_path, monkeypatch):
    from shortlist import ShortlistEntry, save_shortlist

    pending_path = str(tmp_path / "pending.json")
    shortlist_path = str(tmp_path / "shortlist.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "shortlist_path", shortlist_path)
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    save_shortlist(shortlist_path, [
        ShortlistEntry(symbol="VOO", sleeve="core", first_seen="2026-08-10", last_updated="2026-08-13",
                        confidence_pct=67.0, previous_confidence_pct=None, score=0.03, price=550.0, reason="x"),
    ])
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: None)  # no pending items this run

    sent = []
    monkeypatch.setattr(app_module, "get_telegram_config", lambda: type("C", (), {"bot_token": "t", "chat_id": "c"})())
    monkeypatch.setattr(app_module, "send_message", lambda text, token, chat_id: sent.append(text))

    app_module.scheduled_asia_hours_scan()

    assert len(sent) == 1
    assert sent[0].startswith("Claude Stock Trading Shortlist:")
    assert "Vanguard S&P 500 ETF (VOO) - 67%" in sent[0]


def test_scheduled_asia_hours_scan_swallows_errors_per_profile(monkeypatch, capsys):
    def raise_error(profile):
        raise RuntimeError("tiger api down")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", raise_error)

    app_module.scheduled_asia_hours_scan()  # must not raise
    assert "Asia-hours scan failed for 'growth'" in capsys.readouterr().out


def test_scheduled_asia_hours_scan_telegram_not_configured_does_not_raise(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

    pending_path = str(tmp_path / "pending.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "shortlist_path", str(tmp_path / "shortlist.json"))
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    def fake_scan(profile):
        write_pending_approvals(pending_path, [PendingApproval(**_sample_pending_item())], scan_id="2026-08-12")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", fake_scan)

    def raise_not_found():
        raise FileNotFoundError("not configured")
    monkeypatch.setattr(app_module, "get_telegram_config", raise_not_found)

    app_module.scheduled_asia_hours_scan()  # must not raise


def test_scheduled_asia_hours_scan_does_not_repeat_identical_telegram_messages(tmp_path, monkeypatch):
    """Reproduces the real user report: SG-open and HK-open scans, 30
    minutes apart, compute the same shortlist/pending-approvals off
    unchanged daily-bar scores and were sending the exact same two
    Telegram messages twice. A second scheduled_asia_hours_scan() run
    with unchanged state must send nothing new."""
    from pending_approvals import write_pending_approvals, PendingApproval
    from shortlist import ShortlistEntry, save_shortlist

    pending_path = str(tmp_path / "pending.json")
    shortlist_path = str(tmp_path / "shortlist.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "shortlist_path", shortlist_path)
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    write_pending_approvals(pending_path, [PendingApproval(**_sample_pending_item())], scan_id="2026-08-12")
    save_shortlist(shortlist_path, [
        ShortlistEntry(symbol="VOO", sleeve="core", first_seen="2026-08-10", last_updated="2026-08-13",
                        confidence_pct=67.0, previous_confidence_pct=None, score=0.03, price=550.0, reason="x"),
    ])
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: None)  # scan reruns but state is unchanged

    sent = []
    monkeypatch.setattr(app_module, "get_telegram_config", lambda: type("C", (), {"bot_token": "t", "chat_id": "c"})())
    monkeypatch.setattr(app_module, "send_message", lambda text, token, chat_id: sent.append(text))

    app_module.scheduled_asia_hours_scan()  # e.g. the SG-open run
    assert len(sent) == 2  # pending approvals + shortlist digest

    app_module.scheduled_asia_hours_scan()  # e.g. the HK-open run, 30 min later, nothing changed
    assert len(sent) == 2  # no repeats sent


def test_scheduled_cot_update_swallows_errors(monkeypatch, capsys):
    def raise_error():
        raise RuntimeError("cftc api down")
    monkeypatch.setattr(app_module, "fetch_positioning_signals", raise_error)

    app_module.scheduled_cot_update()  # must not raise
    assert "COT update failed" in capsys.readouterr().out


def test_scheduled_cot_update_pushes_state(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "fetch_positioning_signals", lambda: {})
    monkeypatch.setattr(app_module, "positioning_to_tilt", lambda metrics: 0.975)
    calls = {}
    monkeypatch.setattr(app_module, "update_positioning_tilt", lambda *a, **k: calls.setdefault("updated", True))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: calls.setdefault("pushed", path))

    app_module.scheduled_cot_update()
    assert calls.get("updated") is True
    assert calls.get("pushed") == app_module.REGIME_PATH
    assert "tilt=0.9750" in capsys.readouterr().out


def test_scheduled_breadth_update_swallows_errors(monkeypatch, capsys):
    def raise_error():
        raise RuntimeError("tiger api down")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    app_module.scheduled_breadth_update()  # must not raise
    assert "Breadth update failed" in capsys.readouterr().out


def test_scheduled_breadth_update_skips_cleanly_when_no_signal(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "fetch_breadth_prices", lambda qc: ([], []))
    monkeypatch.setattr(app_module, "compute_ratio_series", lambda rsp, spy: [])
    monkeypatch.setattr(app_module, "compute_breadth_signal", lambda ratio: None)

    app_module.scheduled_breadth_update()
    assert "Not enough RSP/SPY history" in capsys.readouterr().out


def test_scheduled_breadth_update_pushes_state(monkeypatch, capsys):
    from market_breadth import BreadthSignal

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "fetch_breadth_prices", lambda qc: ([], []))
    monkeypatch.setattr(app_module, "compute_ratio_series", lambda rsp, spy: [1])
    signal = BreadthSignal(as_of="2026-08-08", ratio=0.5, ma_short=0.49, ma_long=0.48,
                            trend="broadening", roc=0.02, roc_zscore=1.0, at_edge=False, tilt=1.05)
    monkeypatch.setattr(app_module, "compute_breadth_signal", lambda ratio: signal)
    calls = {}
    monkeypatch.setattr(app_module, "update_breadth_signal", lambda *a, **k: calls.setdefault("updated", True))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: calls.setdefault("pushed", path))

    app_module.scheduled_breadth_update()
    assert calls.get("updated") is True
    assert calls.get("pushed") == app_module.REGIME_PATH
    assert "trend=broadening" in capsys.readouterr().out


def test_scheduled_sector_rotation_update_skips_cleanly_when_client_unavailable(monkeypatch, capsys):
    def raise_error():
        raise RuntimeError("tiger api down")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    app_module.scheduled_sector_rotation_update()  # must not raise
    assert "Sector rotation update skipped" in capsys.readouterr().out


def test_scheduled_sector_rotation_update_tolerates_a_ranking_failure(monkeypatch, capsys):
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())

    def raise_error(*a, **k):
        raise RuntimeError("bars fetch failed")
    monkeypatch.setattr(app_module, "refresh_sector_rotation", raise_error)
    monkeypatch.setattr(app_module, "refresh_investment_clock", raise_error)
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [])

    app_module.scheduled_sector_rotation_update()  # must not raise
    out = capsys.readouterr().out
    assert "Sector rotation ranking failed" in out
    assert "Investment Clock update failed" in out


def test_scheduled_sector_rotation_update_pushes_state_and_builds_suggestions(tmp_path, monkeypatch, capsys):
    from sector_rotation import SectorRotationSignal, SectorRankEntry
    from investment_clock import InvestmentClockSignal
    from sector_suggestions import SectorSuggestion

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    # Isolated from the real extra_universe.json -- this test is about
    # suggestion-building, not the growth-only auto-add path (see its
    # own dedicated tests), so auto-add is stubbed to a no-op here.
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))
    monkeypatch.setattr(app_module, "_auto_add_candidates", lambda profile, suggestions: ([], suggestions))

    us_signal = SectorRotationSignal(
        as_of="2026-08-16", region="US", method="sector_etf",
        entries=[SectorRankEntry("Technology", "45", "XLK", "broadening", 0.05, 1.2, 1)],
    )
    monkeypatch.setattr(app_module, "refresh_sector_rotation", lambda qc, us_symbols, hk_symbols, path: {"US": us_signal, "HK": None, "SG": None})

    clock_signal = InvestmentClockSignal(
        as_of="2026-08-16", region="US", quadrant="Recovery", growth_trend="rising",
        inflation_trend="falling", growth_value=1.0, inflation_value=2.0,
        best_sectors=["Technology"],
    )
    monkeypatch.setattr(app_module, "refresh_investment_clock", lambda: clock_signal)

    suggestion = SectorSuggestion(symbol="JPM", market="US", sector_name="Technology", gics_sector_id="45",
                                   discovered_at="2026-08-16", reason="test")
    monkeypatch.setattr(app_module, "fetch_suggestions_for_sector", lambda *a, **k: [suggestion])

    pushed = []
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: pushed.append(path))
    monkeypatch.setattr(app_module, "save_sector_rotation", lambda path, signals: None)
    monkeypatch.setattr(app_module, "save_investment_clock", lambda path, signal: None)
    saved_suggestions = {}
    monkeypatch.setattr(app_module, "save_suggestions", lambda path, suggestions: saved_suggestions.setdefault(path, suggestions))
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    app_module.scheduled_sector_rotation_update()

    out = capsys.readouterr().out
    assert "Sector rotation updated: US top sector = Technology" in out
    assert "Investment Clock updated: Recovery" in out
    assert "Sector opportunities updated for 'growth': 1 suggestion(s)." in out
    assert app_module.SECTOR_ROTATION_PATH in pushed
    assert app_module.INVESTMENT_CLOCK_PATH in pushed
    assert saved_suggestions[app_module.GROWTH_PROFILE.sector_suggestions_path] == [suggestion]


def test_scheduled_sector_rotation_update_prefers_top_industry_over_top_sector(monkeypatch, capsys):
    from sector_rotation import SectorRotationSignal, SectorRankEntry, IndustryRankEntry
    from investment_clock import InvestmentClockSignal

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())

    us_signal = SectorRotationSignal(
        as_of="2026-08-16", region="US", method="sector_etf",
        entries=[SectorRankEntry("Technology", "45", "XLK", "broadening", 0.05, 1.2, 1)],
        industries=[IndustryRankEntry("Semiconductors & Semiconductor Equipment", "4530", "Technology", 0.08, 1)],
    )
    monkeypatch.setattr(app_module, "refresh_sector_rotation", lambda qc, us_symbols, hk_symbols, path: {"US": us_signal, "HK": None, "SG": None})
    monkeypatch.setattr(app_module, "refresh_investment_clock", lambda: InvestmentClockSignal(
        as_of="2026-08-16", region="US", quadrant="Recovery", growth_trend="rising",
        inflation_trend="falling", growth_value=1.0, inflation_value=2.0, best_sectors=["Technology"],
    ))

    calls = []

    def fake_fetch_suggestions_for_sector(qc, gics_id, name, market, excluded):
        calls.append((gics_id, name))
        return []
    monkeypatch.setattr(app_module, "fetch_suggestions_for_sector", fake_fetch_suggestions_for_sector)

    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)
    monkeypatch.setattr(app_module, "save_sector_rotation", lambda path, signals: None)
    monkeypatch.setattr(app_module, "save_investment_clock", lambda path, signal: None)
    monkeypatch.setattr(app_module, "save_suggestions", lambda path, suggestions: None)
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    app_module.scheduled_sector_rotation_update()

    assert ("4530", "Semiconductors & Semiconductor Equipment") in calls
    assert not any(gics_id == "45" for gics_id, _name in calls)


# ---- _mover_based_suggestions / _dedupe_by_symbol -------------------------------------------------

def test_mover_based_suggestions_intersects_sector_membership_with_movers(monkeypatch):
    from movers import MoversSignal, MoverEntry
    from tigeropen.common.consts import Market

    monkeypatch.setattr(app_module, "fetch_industry_stocks", lambda qc, gics_id, market: [{"symbol": "NVDA"}, {"symbol": "OBSCURE"}])
    monkeypatch.setattr(app_module, "parse_industry_stocks", lambda raw: [e["symbol"] for e in raw])

    movers_signal = MoversSignal(as_of="2026-08-19", region="US", entries=[
        MoverEntry(symbol="NVDA", name="NVIDIA", change_rate=0.05, rank=1),
        MoverEntry(symbol="OTHERSYM", name="Other", change_rate=0.02, rank=2),
    ])

    result = app_module._mover_based_suggestions(
        object(), "45", "Technology", Market.US, movers_signal, excluded=set(),
    )

    assert [s.symbol for s in result] == ["NVDA"]  # OBSCURE isn't a mover, OTHERSYM isn't in the sector
    assert "actively-traded" in result[0].reason


def test_mover_based_suggestions_empty_when_no_movers_signal():
    result = app_module._mover_based_suggestions(object(), "45", "Technology", None, None, excluded=set())
    assert result == []


def test_dedupe_by_symbol_keeps_first_occurrence():
    deduped = app_module._dedupe_by_symbol([
        _fake_suggestion("NVDA", sector_name="Technology"),
        _fake_suggestion("NVDA", sector_name="Semiconductors"),
        _fake_suggestion("AMD"),
    ])
    assert [s.symbol for s in deduped] == ["NVDA", "AMD"]
    assert deduped[0].sector_name == "Technology"  # first occurrence wins


# ---- _auto_add_candidates -------------------------------------------------

def _fake_suggestion(symbol, market="US", sector_name="Technology"):
    from sector_suggestions import SectorSuggestion
    return SectorSuggestion(symbol=symbol, market=market, sector_name=sector_name, gics_sector_id="45",
                             discovered_at="2026-08-19", reason="test")


def test_auto_add_candidates_adds_up_to_the_per_run_cap(tmp_path, monkeypatch):
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: True)

    suggestions = [_fake_suggestion(f"SYM{i}") for i in range(app_module.MAX_AUTO_ADDS_PER_RUN + 2)]
    added, remaining = app_module._auto_add_candidates(app_module.GROWTH_PROFILE, suggestions)

    assert len(added) == app_module.MAX_AUTO_ADDS_PER_RUN
    assert len(remaining) == 2
    from universe_extra import load_extra_universe
    entries = load_extra_universe(path)
    assert len(entries) == app_module.MAX_AUTO_ADDS_PER_RUN
    assert all(e.auto_added for e in entries)


def test_auto_add_candidates_stops_once_extra_universe_reaches_the_size_ceiling(tmp_path, monkeypatch):
    from universe_extra import ExtraUniverseEntry, save_extra_universe

    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    save_extra_universe(path, [
        ExtraUniverseEntry(symbol=f"OLD{i}", market="US", currency="USD", exchange="", sleeve="satellite",
                            added_at="2026-08-01")
        for i in range(app_module.MAX_EXTRA_UNIVERSE_SIZE)
    ])

    def fail_if_called(p):
        raise AssertionError("must not push when nothing was added")
    monkeypatch.setattr(app_module, "push_state_to_github", fail_if_called)

    suggestions = [_fake_suggestion("NEWSYM")]
    added, remaining = app_module._auto_add_candidates(app_module.GROWTH_PROFILE, suggestions)

    assert added == []
    assert remaining == suggestions


def test_auto_add_candidates_defers_a_symbol_that_fails_validation(tmp_path, monkeypatch):
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: True)

    def raise_for_bad(symbol, profile):
        if symbol == "BADSYM":
            raise ValueError("already tracked")
    monkeypatch.setattr(app_module, "validate_new_universe_entry", raise_for_bad)

    suggestions = [_fake_suggestion("BADSYM"), _fake_suggestion("GOODSYM")]
    added, remaining = app_module._auto_add_candidates(app_module.GROWTH_PROFILE, suggestions)

    assert [s.symbol for s in added] == ["GOODSYM"]
    assert [s.symbol for s in remaining] == ["BADSYM"]


def test_auto_add_candidates_does_not_push_when_nothing_added(tmp_path, monkeypatch):
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)

    def fail_if_called(p):
        raise AssertionError("must not push when nothing was added")
    monkeypatch.setattr(app_module, "push_state_to_github", fail_if_called)

    added, remaining = app_module._auto_add_candidates(app_module.GROWTH_PROFILE, [])
    assert added == []


# ---- scheduled_sector_rotation_update: growth-only auto-add + movers -------------------------------------------------

def test_scheduled_sector_rotation_update_auto_adds_for_growth_only(tmp_path, monkeypatch, capsys):
    from sector_rotation import SectorRotationSignal, SectorRankEntry
    from investment_clock import InvestmentClockSignal

    growth_extra = str(tmp_path / "extra_universe.json")
    dividend_extra = str(tmp_path / "extra_universe_dividend.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", growth_extra)
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "extra_universe_path", dividend_extra)

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())

    us_signal = SectorRotationSignal(
        as_of="2026-08-19", region="US", method="sector_etf",
        entries=[SectorRankEntry("Technology", "45", "XLK", "broadening", 0.05, 1.2, 1)],
    )
    monkeypatch.setattr(app_module, "refresh_sector_rotation", lambda qc, us_symbols, hk_symbols, path: {"US": us_signal, "HK": None, "SG": None})
    monkeypatch.setattr(app_module, "refresh_investment_clock", lambda: InvestmentClockSignal(
        as_of="2026-08-19", region="US", quadrant="Recovery", growth_trend="rising",
        inflation_trend="falling", growth_value=1.0, inflation_value=2.0, best_sectors=["Technology"],
    ))
    monkeypatch.setattr(app_module, "fetch_suggestions_for_sector", lambda qc, gics_id, name, market, excluded: [_fake_suggestion("JPM")])
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)
    monkeypatch.setattr(app_module, "save_sector_rotation", lambda path, signals: None)
    monkeypatch.setattr(app_module, "save_investment_clock", lambda path, signal: None)
    monkeypatch.setattr(app_module, "save_suggestions", lambda path, suggestions: None)
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE, app_module.DIVIDEND_PROFILE])

    app_module.scheduled_sector_rotation_update()

    from universe_extra import load_extra_universe
    growth_entries = load_extra_universe(growth_extra)
    dividend_entries = load_extra_universe(dividend_extra)
    assert [e.symbol for e in growth_entries] == ["JPM"]  # growth: auto-added, no click
    assert dividend_entries == []  # dividend: manual-approval flow unchanged

    out = capsys.readouterr().out
    assert "Auto-added 1 symbol(s) to 'growth' universe: JPM." in out


def test_scheduled_sector_rotation_update_refreshes_movers(tmp_path, monkeypatch, capsys):
    from sector_rotation import SectorRotationSignal
    from investment_clock import InvestmentClockSignal
    from movers import MoversSignal, MoverEntry

    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "refresh_sector_rotation", lambda qc, us_symbols, hk_symbols, path: {})
    monkeypatch.setattr(app_module, "refresh_investment_clock", lambda: InvestmentClockSignal(
        as_of="2026-08-19", region="US", quadrant="Recovery", growth_trend="rising",
        inflation_trend="falling", growth_value=1.0, inflation_value=2.0, best_sectors=["Technology"],
    ))
    monkeypatch.setattr(app_module, "refresh_movers", lambda qc: {
        "US": MoversSignal(as_of="2026-08-19", region="US", entries=[
            MoverEntry(symbol="NVDA", name="NVIDIA", change_rate=0.05, rank=1),
        ]),
        "HK": MoversSignal(as_of="2026-08-19", region="HK", entries=[]),
        "SG": MoversSignal(as_of="2026-08-19", region="SG", entries=[]),
    })
    saved = {}
    monkeypatch.setattr(app_module, "save_movers", lambda path, signals: saved.setdefault("signals", signals))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)
    monkeypatch.setattr(app_module, "save_sector_rotation", lambda path, signals: None)
    monkeypatch.setattr(app_module, "save_investment_clock", lambda path, signal: None)
    monkeypatch.setattr(app_module, "save_suggestions", lambda path, suggestions: None)
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    app_module.scheduled_sector_rotation_update()

    assert saved["signals"]["US"].entries[0].symbol == "NVDA"
    assert "Movers updated: US top = NVDA" in capsys.readouterr().out


def test_scheduled_sector_rotation_update_movers_failure_does_not_block_suggestions(tmp_path, monkeypatch, capsys):
    """Same independent-stage tolerance as sector rotation/Investment
    Clock -- a movers fetch failure must not stop suggestions from
    updating."""
    from sector_rotation import SectorRotationSignal, SectorRankEntry
    from investment_clock import InvestmentClockSignal

    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", str(tmp_path / "extra_universe.json"))
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())

    us_signal = SectorRotationSignal(
        as_of="2026-08-19", region="US", method="sector_etf",
        entries=[SectorRankEntry("Technology", "45", "XLK", "broadening", 0.05, 1.2, 1)],
    )
    monkeypatch.setattr(app_module, "refresh_sector_rotation", lambda qc, us_symbols, hk_symbols, path: {"US": us_signal, "HK": None, "SG": None})
    monkeypatch.setattr(app_module, "refresh_investment_clock", lambda: InvestmentClockSignal(
        as_of="2026-08-19", region="US", quadrant="Recovery", growth_trend="rising",
        inflation_trend="falling", growth_value=1.0, inflation_value=2.0, best_sectors=["Technology"],
    ))

    def raise_error(qc):
        raise RuntimeError("Tiger movers endpoint down")
    monkeypatch.setattr(app_module, "refresh_movers", raise_error)
    monkeypatch.setattr(app_module, "fetch_suggestions_for_sector", lambda *a, **k: [])
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)
    monkeypatch.setattr(app_module, "save_sector_rotation", lambda path, signals: None)
    monkeypatch.setattr(app_module, "save_investment_clock", lambda path, signal: None)
    monkeypatch.setattr(app_module, "save_suggestions", lambda path, suggestions: None)
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    app_module.scheduled_sector_rotation_update()  # must not raise

    out = capsys.readouterr().out
    assert "Movers update failed" in out
    assert "Sector opportunities updated for 'growth'" in out


# ---- _weekly_gain_chart_data -------------------------------------------------

def test_weekly_gain_chart_data_computes_pct_gain_from_monday():
    from datetime import date, timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    last_day = today if today.weekday() < 5 else monday + timedelta(days=4)
    ledger = {"history": [
        {"date": monday.isoformat(), "capital": 1000.0},
        {"date": last_day.isoformat(), "capital": 1050.0},
    ]}

    result = app_module._weekly_gain_chart_data(ledger)

    assert result["labels"][0] == "Mon"
    assert result["labels"][-1] == last_day.strftime("%a")
    assert result["values"][-1] == pytest.approx(0.05)
    assert result["values"][0] == pytest.approx(0.0)  # Monday's own baseline vs itself


def test_weekly_gain_chart_data_starts_from_a_reset_this_week_not_monday():
    """A capital reset mid-week must not be counted as a fake weekly
    gain/loss -- the chart should start from the reset date instead of
    Monday, same reset-skip convention as gain_baseline_date."""
    from datetime import date, timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() == 0:
        return  # no room for a "reset later this week" case on a Monday test run
    reset_day = monday + timedelta(days=1)
    ledger = {"history": [
        {"date": monday.isoformat(), "capital": 100000.0},  # would look like a huge loss if not skipped
        {"date": reset_day.isoformat(), "capital": 1000.0, "type": "reset"},
        {"date": today.isoformat() if today.weekday() < 5 else (monday + timedelta(days=4)).isoformat(), "capital": 1010.0},
    ]}

    result = app_module._weekly_gain_chart_data(ledger)

    assert result["labels"][0] == reset_day.strftime("%a")
    assert result["values"][-1] == pytest.approx(0.01)


def test_weekly_gain_chart_data_empty_history_defaults_to_zero():
    from datetime import date, timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    ledger = {"history": [{"date": monday.isoformat(), "capital": 0.0}]}
    result = app_module._weekly_gain_chart_data(ledger)
    assert all(v == 0.0 for v in result["values"])  # no division by zero


# ---- scheduled_dividends_update -------------------------------------------------

def test_scheduled_dividends_update_skips_when_dividend_inactive(monkeypatch, capsys):
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", False)

    def fail_if_called(*a, **k):
        raise AssertionError("must not touch Tiger when dividend portfolio is inactive")
    monkeypatch.setattr(app_module, "get_client_config", fail_if_called)

    app_module.scheduled_dividends_update()  # must not raise


def test_scheduled_dividends_update_skips_cleanly_when_client_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", True)

    def raise_error():
        raise RuntimeError("tiger api down")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    app_module.scheduled_dividends_update()  # must not raise
    assert "Dividends update skipped" in capsys.readouterr().out


def test_scheduled_dividends_update_tolerates_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", True)
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())

    def raise_error(*a, **k):
        raise RuntimeError("journal unreadable")
    monkeypatch.setattr(app_module, "load_journal", raise_error)

    app_module.scheduled_dividends_update()  # must not raise
    assert "Dividends update failed" in capsys.readouterr().out


def test_scheduled_dividends_update_saves_and_pushes_summary(tmp_path, monkeypatch, capsys):
    from dividend_tracker import DividendSummary

    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", True)
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "load_journal", lambda path: [])

    summary = DividendSummary(as_of="2026-08-20", year=2026, total_by_currency={"USD": 12.5}, payments=[])
    monkeypatch.setattr(app_module, "refresh_dividends_earned", lambda *a, **k: summary)

    saved = {}
    monkeypatch.setattr(app_module, "save_dividends_earned", lambda path, s: saved.setdefault("summary", s))
    pushed = []
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: pushed.append(path))

    app_module.scheduled_dividends_update()

    assert saved["summary"] == summary
    assert app_module.DIVIDENDS_EARNED_PATH in pushed
    assert "Dividends updated: 12.50 USD earned in 2026" in capsys.readouterr().out


def test_scheduled_news_scan_skips_without_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    app_module.scheduled_news_scan()
    assert "skipping automated news scan" in capsys.readouterr().out


def test_scheduled_news_scan_swallows_errors(monkeypatch, capsys):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "testkey")

    def raise_error(*a, **k):
        raise RuntimeError("alpha vantage down")
    monkeypatch.setattr(app_module, "fetch_news_sentiment", raise_error)

    app_module.scheduled_news_scan()  # must not raise
    assert "News scan failed" in capsys.readouterr().out


def test_run_and_persist_news_scan_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
        app_module._run_and_persist_news_scan()


def test_run_and_persist_news_scan_prefers_finnhub_when_both_keys_set(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "NEWS_PATH", str(tmp_path / "news.json"))
    monkeypatch.setenv("FINNHUB_API_KEY", "finnhub-key")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha-key")
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)

    captured = {}

    def fake_fetch_finnhub(symbols, api_key, as_of):
        captured["finnhub_key"] = api_key
        return {}
    monkeypatch.setattr(app_module, "fetch_news_for_universe", fake_fetch_finnhub)

    def fail_if_called(*a, **k):
        raise AssertionError("Alpha Vantage must not be used when FINNHUB_API_KEY is set")
    monkeypatch.setattr(app_module, "fetch_news_sentiment", fail_if_called)

    app_module._run_and_persist_news_scan()
    assert captured["finnhub_key"] == "finnhub-key"


def test_run_and_persist_news_scan_falls_back_to_alpha_vantage_without_finnhub_key(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "NEWS_PATH", str(tmp_path / "news.json"))
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha-key")
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)

    def fail_if_called(*a, **k):
        raise AssertionError("Finnhub must not be used when FINNHUB_API_KEY is not set")
    monkeypatch.setattr(app_module, "fetch_news_for_universe", fail_if_called)

    captured = {}

    def fake_fetch_alpha(symbols, api_key):
        captured["alpha_key"] = api_key
        return {"feed": []}
    monkeypatch.setattr(app_module, "fetch_news_sentiment", fake_fetch_alpha)

    app_module._run_and_persist_news_scan()
    assert captured["alpha_key"] == "alpha-key"


def test_news_route_renders_with_no_state(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "NEWS_PATH", str(tmp_path / "news.json"))
    monkeypatch.setattr(app_module, "REGIME_PATH", str(tmp_path / "regime.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))

    client = app_module.app.test_client()
    response = client.get("/news")
    assert response.status_code == 200
    assert b"No notable news" in response.data or b"No macro regime data" in response.data


def test_news_route_shows_notable_implications(tmp_path, monkeypatch):
    from news_scanner import write_news_signal, SymbolNewsSignal

    news_path = str(tmp_path / "news.json")
    monkeypatch.setattr(app_module, "NEWS_PATH", news_path)
    monkeypatch.setattr(app_module, "REGIME_PATH", str(tmp_path / "regime.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))
    write_news_signal(news_path, [
        SymbolNewsSignal(symbol="NVDA", tilt=0.6, as_of="2026-08-08", headlines_considered=["NVDA surges on AI demand"]),
    ])

    client = app_module.app.test_client()
    response = client.get("/news")
    assert response.status_code == 200
    assert b"NVDA" in response.data
    assert b"AI demand" in response.data


def test_news_refresh_route_redirects_with_success_message(monkeypatch):
    monkeypatch.setattr(app_module, "_run_and_persist_news_scan", lambda: {"NVDA": object()})
    client = app_module.app.test_client()
    response = client.post("/news/refresh", follow_redirects=True)
    assert response.status_code == 200
    assert b"News refreshed: 1 symbol(s) updated." in response.data


def test_news_refresh_route_redirects_with_failure_message(monkeypatch):
    def raise_error():
        raise RuntimeError("ALPHA_VANTAGE_API_KEY is not set")
    monkeypatch.setattr(app_module, "_run_and_persist_news_scan", raise_error)
    client = app_module.app.test_client()
    response = client.post("/news/refresh", follow_redirects=True)
    assert response.status_code == 200
    assert b"News refresh failed" in response.data


def test_dashboard_includes_news_summary_context(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))
    monkeypatch.setattr(app_module, "NEWS_PATH", str(tmp_path / "news.json"))
    monkeypatch.setattr(app_module, "REGIME_PATH", str(tmp_path / "regime.json"))

    def raise_error():
        raise RuntimeError("no credentials in test env")
    monkeypatch.setattr(app_module, "get_client_config", raise_error)

    client = app_module.app.test_client()
    response = client.get("/?portfolio=growth")
    assert response.status_code == 200


def test_scan_now_route_redirects_with_success_message(monkeypatch):
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: None)
    monkeypatch.setattr(app_module, "is_any_market_open", lambda codes, now_utc: True)
    client = app_module.app.test_client()
    response = client.post("/scan", follow_redirects=True)
    assert response.status_code == 200
    assert b"Scan complete." in response.data


def test_scan_now_route_redirects_with_failure_message(monkeypatch):
    def raise_error(profile):
        raise RuntimeError("tiger down")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", raise_error)
    monkeypatch.setattr(app_module, "is_any_market_open", lambda codes, now_utc: True)
    client = app_module.app.test_client()
    response = client.post("/scan", follow_redirects=True)
    assert response.status_code == 200
    assert b"Scan failed" in response.data


def test_scan_now_route_rejects_inactive_portfolio(monkeypatch):
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", False)
    client = app_module.app.test_client()
    response = client.post("/scan?portfolio=dividend", follow_redirects=True)
    assert response.status_code == 200
    assert b"isn&#39;t funded yet" in response.data or b"isn't funded yet" in response.data


def test_scan_now_route_skips_scan_when_all_relevant_markets_closed(monkeypatch):
    def fail_if_called(profile):
        raise AssertionError("must not scan while every relevant market is closed")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", fail_if_called)
    monkeypatch.setattr(app_module, "is_any_market_open", lambda codes, now_utc: False)

    client = app_module.app.test_client()
    response = client.post("/scan", follow_redirects=True)
    assert response.status_code == 200
    assert b"markets are closed" in response.data
    assert b"no trades can be placed" in response.data


def test_scan_now_route_passes_only_the_profiles_own_markets(monkeypatch):
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "active", True)
    seen = {}

    def capture(codes, now_utc):
        seen["codes"] = codes
        return True
    monkeypatch.setattr(app_module, "is_any_market_open", capture)
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: None)

    client = app_module.app.test_client()
    client.post("/scan?portfolio=dividend", follow_redirects=True)

    assert seen["codes"] == {e.market for e in app_module.DIVIDEND_PROFILE.universe}


def _make_fake_scan_result(**overrides):
    from scan_workflow import ScanResult
    from portfolio_construction import ScoredCandidate
    from execution import OrderInstruction
    from universe import UniverseEntry

    defaults = dict(
        profile_name="growth", as_of="2026-08-10",
        universe=[UniverseEntry("NVDA", "US", "USD", "", "satellite")],
        sleeve_by_symbol={"NVDA": "satellite"},
        all_candidates=[ScoredCandidate(symbol="NVDA", sleeve="satellite", score=0.22, price=200.0)],
        affordable_candidates=[ScoredCandidate(symbol="NVDA", sleeve="satellite", score=0.22, price=200.0)],
        planned=[], current_positions={}, price_by_symbol={"NVDA": 200.0}, exit_reasons={},
        instructions=[OrderInstruction("NVDA", "BUY", 1, 200.0, "top satellite pick")],
        instruction_outcomes={"NVDA": ("buy", "top satellite pick")},
        approved_instructions=[OrderInstruction("NVDA", "BUY", 1, 200.0, "top satellite pick")],
        decisions=[], capital=1000.0, halted=False, halt_reason=None,
        confidence_by_symbol={"NVDA": 81.4},
    )
    defaults.update(overrides)
    return ScanResult(**defaults)


def _stub_scan_dependencies(monkeypatch, tmp_path, scan_result):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", str(tmp_path / "pending.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "shortlist_path", str(tmp_path / "shortlist.json"))
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: object())
    monkeypatch.setattr(app_module, "run_scan", lambda *a, **k: scan_result)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)
    # Deterministic by default -- "market open" regardless of wall-clock
    # time, matching these tests' actual intent (autopilot on/off logic,
    # not market hours). Tests of the per-instruction market-hours
    # filtering itself override this explicitly.
    monkeypatch.setattr(app_module, "is_any_market_open", lambda market_codes, now_utc: True)


def test_run_and_persist_scan_autopilot_off_leaves_items_pending(tmp_path, monkeypatch):
    from scan_settings import ScanSettings, save_scan_settings

    result = _make_fake_scan_result()
    _stub_scan_dependencies(monkeypatch, tmp_path, result)
    save_scan_settings(app_module.GROWTH_PROFILE.scan_settings_path, ScanSettings(autopilot=False))

    def fail_if_called(*a, **k):
        raise AssertionError("execute_instructions must not be called when autopilot is off")
    monkeypatch.setattr(app_module, "execute_instructions", fail_if_called)

    app_module._run_and_persist_scan(app_module.GROWTH_PROFILE)

    from pending_approvals import load_pending_approvals
    pending = load_pending_approvals(app_module.GROWTH_PROFILE.pending_approvals_path)
    assert len(pending["items"]) == 1
    assert pending["items"][0]["symbol"] == "NVDA"


def test_run_and_persist_scan_autopilot_on_executes_and_clears_pending(tmp_path, monkeypatch):
    from scan_settings import ScanSettings, save_scan_settings

    result = _make_fake_scan_result()
    _stub_scan_dependencies(monkeypatch, tmp_path, result)
    save_scan_settings(app_module.GROWTH_PROFILE.scan_settings_path, ScanSettings(autopilot=True))

    executed = {}

    def fake_execute_instructions(trade_client, client_config, universe_by_symbol, instructions,
                                   sleeve_by_symbol, capital, ledger_path=None, **kwargs):
        executed["instructions"] = instructions
        executed["confidence_by_symbol"] = kwargs.get("confidence_by_symbol")
    monkeypatch.setattr(app_module, "execute_instructions", fake_execute_instructions)

    app_module._run_and_persist_scan(app_module.GROWTH_PROFILE)

    assert len(executed["instructions"]) == 1
    assert executed["instructions"][0].symbol == "NVDA"
    assert executed["confidence_by_symbol"] == {"NVDA": 81.4}

    from pending_approvals import load_pending_approvals
    pending = load_pending_approvals(app_module.GROWTH_PROFILE.pending_approvals_path)
    assert pending["items"] == []  # already executed -- nothing left pending


def test_run_and_persist_scan_autopilot_defers_instructions_whose_market_is_closed(tmp_path, monkeypatch):
    """Regression test: autopilot used to submit every approved
    instruction regardless of whether ITS OWN market was open right
    now -- e.g. a scan running during HK/SG hours would still try to
    place a market order for a US candidate, which Tiger rejects
    outside US hours, aborting the whole batch (confirmed live). A
    closed-market instruction must now be deferred as a pending
    approval instead of being submitted or lost."""
    from scan_settings import ScanSettings, save_scan_settings

    result = _make_fake_scan_result()
    _stub_scan_dependencies(monkeypatch, tmp_path, result)
    save_scan_settings(app_module.GROWTH_PROFILE.scan_settings_path, ScanSettings(autopilot=True))

    monkeypatch.setattr(app_module, "is_any_market_open", lambda market_codes, now_utc: False)

    def fail_if_called(*a, **k):
        raise AssertionError("execute_instructions must not be called for a closed-market instruction")
    monkeypatch.setattr(app_module, "execute_instructions", fail_if_called)

    app_module._run_and_persist_scan(app_module.GROWTH_PROFILE)

    from pending_approvals import load_pending_approvals
    pending = load_pending_approvals(app_module.GROWTH_PROFILE.pending_approvals_path)
    assert len(pending["items"]) == 1
    assert pending["items"][0]["symbol"] == "NVDA"  # deferred, not lost


def test_run_and_persist_scan_autopilot_executes_open_market_defers_closed_market(tmp_path, monkeypatch):
    """Mixed batch: an open-market instruction is executed by autopilot;
    a closed-market one in the SAME batch is deferred as pending instead
    -- neither is lost, and the closed one doesn't abort the open one."""
    from scan_settings import ScanSettings, save_scan_settings
    from execution import OrderInstruction
    from universe import UniverseEntry

    result = _make_fake_scan_result(
        universe=[
            UniverseEntry("NVDA", "US", "USD", "", "satellite"),
            UniverseEntry("00700", "HK", "HKD", "SEHK", "satellite"),
        ],
        sleeve_by_symbol={"NVDA": "satellite", "00700": "satellite"},
        approved_instructions=[
            OrderInstruction("NVDA", "BUY", 1, 200.0, "US pick"),
            OrderInstruction("00700", "BUY", 1, 300.0, "HK pick"),
        ],
        confidence_by_symbol={"NVDA": 81.4, "00700": 75.0},
    )
    _stub_scan_dependencies(monkeypatch, tmp_path, result)
    save_scan_settings(app_module.GROWTH_PROFILE.scan_settings_path, ScanSettings(autopilot=True))

    monkeypatch.setattr(app_module, "effective_universe", lambda p: [
        UniverseEntry("NVDA", "US", "USD", "", "satellite"),
        UniverseEntry("00700", "HK", "HKD", "SEHK", "satellite"),
    ])
    # Only HK is open right now.
    monkeypatch.setattr(app_module, "is_any_market_open", lambda market_codes, now_utc: "HK" in market_codes)

    executed = {}

    def fake_execute_instructions(trade_client, client_config, universe_by_symbol, instructions,
                                   sleeve_by_symbol, capital, ledger_path=None, **kwargs):
        executed["instructions"] = instructions
    monkeypatch.setattr(app_module, "execute_instructions", fake_execute_instructions)

    app_module._run_and_persist_scan(app_module.GROWTH_PROFILE)

    assert [i.symbol for i in executed["instructions"]] == ["00700"]

    from pending_approvals import load_pending_approvals
    pending = load_pending_approvals(app_module.GROWTH_PROFILE.pending_approvals_path)
    assert [i["symbol"] for i in pending["items"]] == ["NVDA"]


def test_run_and_persist_scan_excludes_held_symbols_from_shortlist(tmp_path, monkeypatch):
    """Regression test for the bug where a held position with confidence
    in the shortlist band was being both force-sold AND never actually
    shown as shortlisted -- held symbols must never land on the
    watchlist, that's reserved for prospective new trades."""
    from execution import CurrentPosition

    result = _make_fake_scan_result(
        confidence_by_symbol={"NVDA": 60.0},  # shortlist-band confidence
        current_positions={"NVDA": CurrentPosition(symbol="NVDA", quantity=1, average_cost=190.0)},
    )
    _stub_scan_dependencies(monkeypatch, tmp_path, result)
    from scan_settings import ScanSettings, save_scan_settings
    save_scan_settings(app_module.GROWTH_PROFILE.scan_settings_path, ScanSettings(autopilot=False))
    monkeypatch.setattr(app_module, "execute_instructions", lambda *a, **k: None)

    app_module._run_and_persist_scan(app_module.GROWTH_PROFILE)

    from shortlist import load_shortlist
    assert load_shortlist(app_module.GROWTH_PROFILE.shortlist_path) == []


def test_run_and_persist_scan_dividend_profile_uses_its_own_settings_and_defaults_autopilot_off(tmp_path, monkeypatch):
    """Dividend now has its own confidence_scale (0.06) and its own
    scan_settings_path/shortlist_path -- completely isolated from
    growth's. Autopilot defaults to off for dividend too (manual
    approval unless the user explicitly flips the Settings checkbox),
    the same mechanism growth already uses -- no special default."""
    from scan_settings import ScanSettings, save_scan_settings

    result = _make_fake_scan_result(profile_name="dividend")
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "decision_log_path", str(tmp_path / "decision_log_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "pending_approvals_path", str(tmp_path / "pending_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings_dividend.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "shortlist_path", str(tmp_path / "shortlist_dividend.json"))
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: object())
    monkeypatch.setattr(app_module, "run_scan", lambda *a, **k: result)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)
    save_scan_settings(app_module.DIVIDEND_PROFILE.scan_settings_path, ScanSettings(autopilot=False))

    def fail_if_called(*a, **k):
        raise AssertionError("autopilot is off -- dividend must require manual approval by default, same as growth")
    monkeypatch.setattr(app_module, "execute_instructions", fail_if_called)

    app_module._run_and_persist_scan(app_module.DIVIDEND_PROFILE)

    from pending_approvals import load_pending_approvals
    pending = load_pending_approvals(app_module.DIVIDEND_PROFILE.pending_approvals_path)
    assert len(pending["items"]) == 1  # manual approval required, matching growth's default-off behavior


def test_update_settings_saves_valid_values_and_redirects(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings.json"))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)

    client = app_module.app.test_client()
    response = client.post("/settings", data={
        "autopilot": "on", "execute_threshold_pct": "75", "shortlist_threshold_pct": "55",
        "max_concurrent_trades": "6", "capital": "2500",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Settings saved." in response.data

    from scan_settings import load_scan_settings
    settings = load_scan_settings(app_module.GROWTH_PROFILE.scan_settings_path)
    assert settings.autopilot is True
    assert settings.execute_threshold_pct == 75.0
    assert settings.capital == 2500.0


def test_update_settings_rejects_invalid_thresholds(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings.json"))

    client = app_module.app.test_client()
    response = client.post("/settings", data={
        "execute_threshold_pct": "40", "shortlist_threshold_pct": "50",
        "max_concurrent_trades": "10", "capital": "1000",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Settings not saved" in response.data
    assert not os.path.exists(app_module.GROWTH_PROFILE.scan_settings_path)


def test_update_settings_available_for_dividend_portfolio_and_uses_its_own_path(tmp_path, monkeypatch):
    """Dividend now has confidence_scale set (0.06), so the settings panel
    and its POST route are available for it too -- and must write to
    dividend's own scan_settings_path, never growth's."""
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings_dividend.json"))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)

    client = app_module.app.test_client()
    response = client.post("/settings?portfolio=dividend", data={
        "autopilot": "on", "execute_threshold_pct": "75", "shortlist_threshold_pct": "55",
        "max_concurrent_trades": "6", "capital": "10000",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Settings saved." in response.data

    from scan_settings import load_scan_settings
    settings = load_scan_settings(app_module.DIVIDEND_PROFILE.scan_settings_path)
    assert settings.autopilot is True
    assert settings.capital == 10000.0


def test_reset_capital_refuses_without_github_credentials(monkeypatch):
    monkeypatch.setattr(app_module, "get_github_config", lambda: None)
    client = app_module.app.test_client()
    response = client.post("/settings/reset-capital", follow_redirects=True)
    assert response.status_code == 200
    assert b"Refusing to reset capital" in response.data


def test_reset_capital_reanchors_ledger_preserving_history(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings.json"))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)

    from strategy_ledger import load_or_init_ledger
    load_or_init_ledger(ledger_path, 1000.0)

    class FakeTradeClient:
        def get_positions(self):
            return []
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    from scan_settings import ScanSettings, save_scan_settings
    save_scan_settings(app_module.GROWTH_PROFILE.scan_settings_path, ScanSettings(capital=2000.0))

    client = app_module.app.test_client()
    response = client.post("/settings/reset-capital", follow_redirects=True)

    assert response.status_code == 200
    assert b"Capital reset to $2,000.00" in response.data

    with open(ledger_path) as f:
        import json as json_module
        ledger = json_module.load(f)
    assert len(ledger["history"]) == 2  # seed entry preserved, plus the reset
    assert ledger["history"][-1]["capital"] == 2000.0


def test_reset_capital_reanchors_dividend_ledger_using_its_own_settings(tmp_path, monkeypatch):
    """Same route, dividend portfolio -- must reanchor DIVIDEND_PROFILE's
    own ledger using DIVIDEND_PROFILE's own scan_settings_path, never
    growth's."""
    _stub_github_configured(monkeypatch)
    ledger_path = str(tmp_path / "ledger_dividend.json")
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "scan_settings_path", str(tmp_path / "scan_settings_dividend.json"))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)

    from strategy_ledger import load_or_init_ledger
    load_or_init_ledger(ledger_path, 30000.0)

    class FakeTradeClient:
        def get_positions(self):
            return []
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    from scan_settings import ScanSettings, save_scan_settings
    save_scan_settings(app_module.DIVIDEND_PROFILE.scan_settings_path, ScanSettings(capital=40000.0))

    client = app_module.app.test_client()
    response = client.post("/settings/reset-capital?portfolio=dividend", follow_redirects=True)

    assert response.status_code == 200
    assert b"Capital reset to $40,000.00" in response.data

    with open(ledger_path) as f:
        import json as json_module
        ledger = json_module.load(f)
    assert ledger["history"][-1]["capital"] == 40000.0


def test_universe_add_persists_a_new_symbol(tmp_path, monkeypatch):
    from universe_extra import load_extra_universe

    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: True)
    _stub_github_configured(monkeypatch)

    client = app_module.app.test_client()
    response = client.post("/universe/add?portfolio=growth", data={
        "symbol": "JPM", "market": "US", "source_sector": "Financials",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Added JPM" in response.data
    entries = load_extra_universe(path)
    assert len(entries) == 1
    assert entries[0].symbol == "JPM"
    assert entries[0].market == "US"
    assert entries[0].currency == "USD"
    assert entries[0].sleeve == "satellite"
    assert entries[0].source_sector == "Financials"


def test_universe_add_defaults_dividend_additions_to_core_sleeve(tmp_path, monkeypatch):
    from universe_extra import load_extra_universe

    path = str(tmp_path / "extra_universe_dividend.json")
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "extra_universe_path", path)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: True)
    _stub_github_configured(monkeypatch)

    client = app_module.app.test_client()
    client.post("/universe/add?portfolio=dividend", data={"symbol": "T", "market": "US"}, follow_redirects=True)

    entries = load_extra_universe(path)
    assert entries[0].sleeve == "core"


def test_universe_add_rejects_a_symbol_already_in_a_universe(monkeypatch):
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: True)
    _stub_github_configured(monkeypatch)
    existing_symbol = app_module.GROWTH_PROFILE.universe[0].symbol

    client = app_module.app.test_client()
    response = client.post("/universe/add?portfolio=growth", data={
        "symbol": existing_symbol, "market": "US",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Couldn&#39;t add" in response.data or b"Couldn't add" in response.data


def test_universe_add_rejects_missing_or_unknown_market(tmp_path, monkeypatch):
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)

    client = app_module.app.test_client()
    response = client.post("/universe/add?portfolio=growth", data={"symbol": "JPM", "market": "MOON"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"unrecognized market" in response.data
    assert not os.path.exists(path)


def test_universe_add_refuses_without_github_credentials(tmp_path, monkeypatch):
    """Regression test: reported live as "added symbols don't seem to
    track" -- an addition used to be written locally and reported as
    success even when GITHUB_TOKEN/GITHUB_REPO weren't configured,
    silently vanishing on the next restart (Render's disk is ephemeral)
    or the next scheduled_pull_state pull. Must now refuse up front,
    matching /approve's own existing refusal for the same reason."""
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    monkeypatch.setattr(app_module, "get_github_config", lambda: None)

    client = app_module.app.test_client()
    response = client.post("/universe/add?portfolio=growth", data={"symbol": "JPM", "market": "US"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Refusing to add" in response.data
    assert not os.path.exists(path)  # nothing written locally either -- no half-added state


def test_universe_add_reports_when_github_push_fails(tmp_path, monkeypatch):
    """github IS configured but the push itself fails (rate limit, SHA
    conflict, network blip) -- the local write already happened, so the
    user must be told clearly it may not survive a restart, not given
    the same success message as a real, synced addition."""
    from universe_extra import load_extra_universe

    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    _stub_github_configured(monkeypatch)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: False)

    client = app_module.app.test_client()
    response = client.post("/universe/add?portfolio=growth", data={"symbol": "JPM", "market": "US"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"GitHub sync failed" in response.data
    entries = load_extra_universe(path)
    assert entries[0].symbol == "JPM"  # local write still happened


def test_universe_add_reports_when_github_push_raises(tmp_path, monkeypatch):
    """push_state_to_github can raise (not just return False) on a non-
    404 GitHub API error -- must be caught, not surfaced as a 500."""
    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    _stub_github_configured(monkeypatch)

    def raise_error(p):
        raise RuntimeError("simulated GitHub API failure")
    monkeypatch.setattr(app_module, "push_state_to_github", raise_error)

    client = app_module.app.test_client()
    response = client.post("/universe/add?portfolio=growth", data={"symbol": "JPM", "market": "US"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"GitHub sync failed" in response.data


def test_universe_remove_drops_a_previously_added_symbol(tmp_path, monkeypatch):
    from universe_extra import ExtraUniverseEntry, save_extra_universe, load_extra_universe

    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: True)
    save_extra_universe(path, [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite", added_at="2026-08-16"),
    ])

    client = app_module.app.test_client()
    response = client.post("/universe/remove?portfolio=growth", data={"symbol": "JPM"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Removed JPM" in response.data
    assert load_extra_universe(path) == []


def test_universe_remove_reports_when_github_push_fails(tmp_path, monkeypatch):
    from universe_extra import ExtraUniverseEntry, save_extra_universe

    path = str(tmp_path / "extra_universe.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "extra_universe_path", path)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda p: False)
    save_extra_universe(path, [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite", added_at="2026-08-16"),
    ])

    client = app_module.app.test_client()
    response = client.post("/universe/remove?portfolio=growth", data={"symbol": "JPM"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"GitHub sync failed" in response.data


def test_review_route_renders_with_no_decision_log(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))
    client = app_module.app.test_client()
    response = client.get("/review")
    assert response.status_code == 200
    assert b"No scan has run yet" in response.data


def test_approve_confirm_get_redirects_when_item_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", str(tmp_path / "pending_approvals.json"))
    client = app_module.app.test_client()
    response = client.get("/approve/does-not-exist", follow_redirects=True)
    assert response.status_code == 200
    assert b"no longer exists" in response.data


def _sample_pending_item():
    return {
        "id": "2026-08-06-NVDA-BUY",
        "symbol": "NVDA",
        "action": "BUY",
        "quantity": 1,
        "notional": 100.0,
        "reason": "momentum breakout",
        "sleeve": "satellite",
        "strategy_key": "satellite_momentum",
        "score": 0.42,
        "currency": "USD",
        "exchange": "NASDAQ",
        "price_at_scan": 100.0,
        "current_position_qty": 0,
        "target_pct": 0.1,
        "capital_at_scan": 1000.0,
        "projected_position_pct": 0.1,
        "projected_total_utilization_pct": 0.3,
        "position_type": "long",
    }


def test_approve_confirm_get_renders_item(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

    path = str(tmp_path / "pending_approvals.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", path)
    write_pending_approvals(path, [PendingApproval(**_sample_pending_item())], scan_id="2026-08-06")

    client = app_module.app.test_client()
    response = client.get("/approve/2026-08-06-NVDA-BUY")
    assert response.status_code == 200
    assert b"NVDA" in response.data


def _stub_github_configured(monkeypatch):
    monkeypatch.setattr(app_module, "get_github_config", lambda: {"token": "t", "repo": "r", "branch": "main"})


def test_approve_execute_post_redirects_when_item_missing(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", str(tmp_path / "pending_approvals.json"))
    client = app_module.app.test_client()
    response = client.post("/approve/does-not-exist", follow_redirects=True)
    assert response.status_code == 200
    assert b"no longer exists" in response.data


def test_approve_execute_post_refuses_without_github_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "get_github_config", lambda: None)
    client = app_module.app.test_client()
    response = client.post("/approve/2026-08-06-NVDA-BUY", follow_redirects=True)
    assert response.status_code == 200
    assert b"Refusing to place a real order" in response.data


def test_approve_execute_post_places_order_and_clears_item(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

    _stub_github_configured(monkeypatch)
    pending_path = str(tmp_path / "pending_approvals.json")
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    write_pending_approvals(pending_path, [PendingApproval(**_sample_pending_item())], scan_id="2026-08-06")

    class FakeTradeClient:
        def get_positions(self):
            return []

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    executed = {}

    def fake_execute_instructions(trade_client, client_config, universe_by_symbol, instructions, sleeve_by_symbol, capital, ledger_path=None, **kwargs):
        executed["instructions"] = instructions
        return None

    monkeypatch.setattr(app_module, "execute_instructions", fake_execute_instructions)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)
    monkeypatch.setattr(app_module, "is_any_market_open", lambda market_codes, now_utc: True)

    client = app_module.app.test_client()
    response = client.post("/approve/2026-08-06-NVDA-BUY", follow_redirects=True)

    assert response.status_code == 200
    assert b"Placed BUY 1 NVDA" in response.data
    assert len(executed["instructions"]) == 1
    assert executed["instructions"][0].symbol == "NVDA"

    remaining = app_module.load_pending_approvals(pending_path)
    assert remaining["items"] == []


def test_approve_execute_post_refuses_when_symbols_market_is_closed(tmp_path, monkeypatch):
    """Regression test: manually clicking Approve for a symbol whose own
    market is currently closed used to let the Tiger ApiException
    propagate as an unhandled 500 -- now it's caught with a friendly
    message, execute_instructions is never called, and the approval
    stays pending (not lost) for the user to retry later."""
    from pending_approvals import write_pending_approvals, PendingApproval

    _stub_github_configured(monkeypatch)
    pending_path = str(tmp_path / "pending_approvals.json")
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    write_pending_approvals(pending_path, [PendingApproval(**_sample_pending_item())], scan_id="2026-08-06")

    class FakeTradeClient:
        def get_positions(self):
            return []

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())
    monkeypatch.setattr(app_module, "is_any_market_open", lambda market_codes, now_utc: False)

    def fail_if_called(*a, **k):
        raise AssertionError("execute_instructions must not be called when the symbol's market is closed")
    monkeypatch.setattr(app_module, "execute_instructions", fail_if_called)

    client = app_module.app.test_client()
    response = client.post("/approve/2026-08-06-NVDA-BUY", follow_redirects=True)

    assert response.status_code == 200
    assert b"market is closed" in response.data

    remaining = app_module.load_pending_approvals(pending_path)
    assert len(remaining["items"]) == 1  # still pending, not lost
    assert remaining["items"][0]["symbol"] == "NVDA"


def test_approve_execute_post_blocked_by_risk_engine(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

    _stub_github_configured(monkeypatch)
    pending_path = str(tmp_path / "pending_approvals.json")
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)

    item = _sample_pending_item()
    item["notional"] = 100000.0  # far beyond the risk cap, must be rejected
    write_pending_approvals(pending_path, [PendingApproval(**item)], scan_id="2026-08-06")

    class FakeTradeClient:
        def get_positions(self):
            return []

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    def fail_if_called(*a, **k):
        raise AssertionError("execute_instructions must not be called when risk engine blocks the trade")
    monkeypatch.setattr(app_module, "execute_instructions", fail_if_called)

    client = app_module.app.test_client()
    response = client.post("/approve/2026-08-06-NVDA-BUY", follow_redirects=True)

    assert response.status_code == 200
    assert b"Approval blocked by risk engine" in response.data

    remaining = app_module.load_pending_approvals(pending_path)
    assert len(remaining["items"]) == 1  # not removed, since it was never executed


def test_approve_execute_post_short_uses_short_direction_for_risk_check(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

    _stub_github_configured(monkeypatch)
    pending_path = str(tmp_path / "pending_approvals.json")
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)

    item = _sample_pending_item()
    item.update(action="SELL", strategy_key="satellite_short", position_type="short", notional=100.0)
    write_pending_approvals(pending_path, [PendingApproval(**item)], scan_id="2026-08-06")

    class FakeTradeClient:
        def get_positions(self):
            return []

    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    captured = {}

    def fake_validate_trade(self, state, strategy, notional, direction="long"):
        captured["direction"] = direction
        captured["strategy"] = strategy
        return True
    monkeypatch.setattr(app_module.RiskEngine, "validate_trade", fake_validate_trade)
    monkeypatch.setattr(app_module, "execute_instructions", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)
    monkeypatch.setattr(app_module, "is_any_market_open", lambda market_codes, now_utc: True)

    client = app_module.app.test_client()
    response = client.post("/approve/2026-08-06-NVDA-BUY", follow_redirects=True)

    assert response.status_code == 200
    assert captured["direction"] == "short"
    assert captured["strategy"] == "satellite_short"


def _fake_position(symbol, quantity, market_price=100.0):
    class FakeContract:
        pass
    contract = FakeContract()
    contract.symbol = symbol

    class FakePosition:
        pass
    p = FakePosition()
    p.contract = contract
    p.quantity = quantity
    p.market_price = market_price
    return p


def test_position_close_confirm_redirects_when_no_position(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))

    class FakeTradeClient:
        def get_positions(self):
            return []
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    response = client.get("/positions/NVDA/close", follow_redirects=True)
    assert response.status_code == 200
    assert b"No open position for NVDA" in response.data


def test_position_close_confirm_full_close_of_a_long(monkeypatch):
    class FakeTradeClient:
        def get_positions(self):
            return [_fake_position("NVDA", 5, market_price=200.0)]
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    response = client.get("/positions/NVDA/close")
    assert response.status_code == 200
    assert b"SELL" in response.data
    assert b"full close" in response.data


def test_position_close_confirm_partial_reduce_capped_at_holding(monkeypatch):
    class FakeTradeClient:
        def get_positions(self):
            return [_fake_position("NVDA", 5, market_price=200.0)]
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    # requesting more than currently held -- must cap at 5, not error
    response = client.get("/positions/NVDA/close?quantity=999")
    assert response.status_code == 200
    assert b"full close" in response.data  # capped request == the whole position


def test_position_close_confirm_cover_of_a_short(monkeypatch):
    class FakeTradeClient:
        def get_positions(self):
            return [_fake_position("AMD", -3, market_price=150.0)]
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    response = client.get("/positions/AMD/close")
    assert response.status_code == 200
    assert b"COVER" in response.data
    assert b"(short)" in response.data


def test_position_close_execute_refuses_without_github_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module, "get_github_config", lambda: None)

    class FakeTradeClient:
        def get_positions(self):
            return []
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    response = client.post("/positions/NVDA/close", follow_redirects=True)
    assert response.status_code == 200
    assert b"Refusing to place a real order" in response.data


def test_position_close_execute_redirects_when_no_position(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))

    class FakeTradeClient:
        def get_positions(self):
            return []
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    client = app_module.app.test_client()
    response = client.post("/positions/NVDA/close", follow_redirects=True)
    assert response.status_code == 200
    assert b"No open position for NVDA" in response.data


def test_position_close_execute_full_close_places_order(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))

    class FakeTradeClient:
        def get_positions(self):
            return [_fake_position("NVDA", 5, market_price=40.0)]
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    executed = {}

    def fake_execute_instructions(trade_client, client_config, universe_by_symbol, instructions, sleeve_by_symbol, capital, ledger_path=None, **kwargs):
        executed["instructions"] = instructions
        return None
    monkeypatch.setattr(app_module, "execute_instructions", fake_execute_instructions)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)

    client = app_module.app.test_client()
    response = client.post("/positions/NVDA/close", follow_redirects=True)

    assert response.status_code == 200
    assert b"Closed NVDA: SELL 5 share(s)." in response.data
    assert len(executed["instructions"]) == 1
    assert executed["instructions"][0].action == "SELL"
    assert executed["instructions"][0].quantity == 5


def test_position_close_execute_partial_reduce_uses_requested_quantity(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))

    class FakeTradeClient:
        def get_positions(self):
            return [_fake_position("NVDA", 5, market_price=40.0)]
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    executed = {}

    def fake_execute_instructions(trade_client, client_config, universe_by_symbol, instructions, sleeve_by_symbol, capital, ledger_path=None, **kwargs):
        executed["instructions"] = instructions
        return None
    monkeypatch.setattr(app_module, "execute_instructions", fake_execute_instructions)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)

    client = app_module.app.test_client()
    response = client.post("/positions/NVDA/close", data={"quantity": "2"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Reduced NVDA: SELL 2 share(s)." in response.data
    assert executed["instructions"][0].quantity == 2


def test_position_close_execute_cover_of_a_short(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))

    class FakeTradeClient:
        def get_positions(self):
            return [_fake_position("AMD", -3, market_price=80.0)]
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    executed = {}

    def fake_execute_instructions(trade_client, client_config, universe_by_symbol, instructions, sleeve_by_symbol, capital, ledger_path=None, **kwargs):
        executed["instructions"] = instructions
        return None
    monkeypatch.setattr(app_module, "execute_instructions", fake_execute_instructions)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: None)

    client = app_module.app.test_client()
    response = client.post("/positions/AMD/close", follow_redirects=True)

    assert response.status_code == 200
    assert executed["instructions"][0].action == "BUY"
    assert executed["instructions"][0].quantity == 3


def test_position_close_execute_blocked_by_risk_engine(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "snapshot_path", str(tmp_path / "snapshot.json"))

    class FakeTradeClient:
        def get_positions(self):
            return [_fake_position("NVDA", 5, market_price=200.0)]
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    def raise_violation(self, state, strategy, notional, direction="long"):
        raise app_module.RiskViolation("drawdown halt active")
    monkeypatch.setattr(app_module.RiskEngine, "validate_trade", raise_violation)

    def fail_if_called(*a, **k):
        raise AssertionError("execute_instructions must not be called when risk engine blocks the trade")
    monkeypatch.setattr(app_module, "execute_instructions", fail_if_called)

    client = app_module.app.test_client()
    response = client.post("/positions/NVDA/close", follow_redirects=True)

    assert response.status_code == 200
    assert b"Close/reduce blocked by risk engine" in response.data
