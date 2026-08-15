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
    response = client.get("/")
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
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Monthly Gain" in text
    assert "+12.0%" in text
    assert "vs 10% target" in text


def test_dashboard_omits_monthly_gain_for_dividend_portfolio(monkeypatch):
    client = app_module.app.test_client()
    response = client.get("/?portfolio=dividend")
    assert response.status_code == 200
    assert "Monthly Gain" not in response.get_data(as_text=True)


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
    response = client.get("/")
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


def test_dashboard_defaults_to_growth_portfolio():
    client = app_module.app.test_client()
    response = client.get("/")
    assert response.status_code == 200


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


def test_scheduled_scan_swallows_errors_per_profile(monkeypatch, capsys):
    def raise_error(profile):
        raise RuntimeError("tiger api down")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", raise_error)

    app_module.scheduled_scan()  # must not raise
    assert "Scheduled scan failed for 'growth'" in capsys.readouterr().out


def test_scheduled_scan_reports_pending_count(monkeypatch, capsys):
    class FakeResult:
        approved_instructions = ["a", "b"]
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: FakeResult())

    app_module.scheduled_scan()
    assert "'growth' scan complete: 2 instruction(s) pending approval" in capsys.readouterr().out


def test_scheduled_scan_only_runs_active_profiles(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    class FakeResult:
        approved_instructions = []

    def fake_scan(profile):
        calls.append(profile.name)
        return FakeResult()
    monkeypatch.setattr(app_module, "_run_and_persist_scan", fake_scan)

    app_module.scheduled_scan()
    assert calls == ["growth"]


def test_scheduled_asia_hours_scan_sends_telegram_when_items_pending(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

    pending_path = str(tmp_path / "pending.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", pending_path)
    monkeypatch.setattr(app_module, "SHORTLIST_PATH", str(tmp_path / "shortlist.json"))  # isolate from real disk state
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
    monkeypatch.setattr(app_module, "SHORTLIST_PATH", str(tmp_path / "shortlist.json"))  # isolate from real disk state
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
    monkeypatch.setattr(app_module, "SHORTLIST_PATH", shortlist_path)
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
    monkeypatch.setattr(app_module, "SHORTLIST_PATH", str(tmp_path / "shortlist.json"))
    monkeypatch.setattr(app_module, "ACTIVE_PROFILES", [app_module.GROWTH_PROFILE])

    def fake_scan(profile):
        write_pending_approvals(pending_path, [PendingApproval(**_sample_pending_item())], scan_id="2026-08-12")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", fake_scan)

    def raise_not_found():
        raise FileNotFoundError("not configured")
    monkeypatch.setattr(app_module, "get_telegram_config", raise_not_found)

    app_module.scheduled_asia_hours_scan()  # must not raise


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
    response = client.get("/")
    assert response.status_code == 200


def test_scan_now_route_redirects_with_success_message(monkeypatch):
    monkeypatch.setattr(app_module, "_run_and_persist_scan", lambda profile: None)
    client = app_module.app.test_client()
    response = client.post("/scan", follow_redirects=True)
    assert response.status_code == 200
    assert b"Scan complete." in response.data


def test_scan_now_route_redirects_with_failure_message(monkeypatch):
    def raise_error(profile):
        raise RuntimeError("tiger down")
    monkeypatch.setattr(app_module, "_run_and_persist_scan", raise_error)
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
    monkeypatch.setattr(app_module, "SCAN_SETTINGS_PATH", str(tmp_path / "scan_settings.json"))
    monkeypatch.setattr(app_module, "SHORTLIST_PATH", str(tmp_path / "shortlist.json"))
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: object())
    monkeypatch.setattr(app_module, "run_scan", lambda *a, **k: scan_result)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)


def test_run_and_persist_scan_autopilot_off_leaves_items_pending(tmp_path, monkeypatch):
    from scan_settings import ScanSettings, save_scan_settings

    result = _make_fake_scan_result()
    _stub_scan_dependencies(monkeypatch, tmp_path, result)
    save_scan_settings(app_module.SCAN_SETTINGS_PATH, ScanSettings(autopilot=False))

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
    save_scan_settings(app_module.SCAN_SETTINGS_PATH, ScanSettings(autopilot=True))

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
    save_scan_settings(app_module.SCAN_SETTINGS_PATH, ScanSettings(autopilot=False))
    monkeypatch.setattr(app_module, "execute_instructions", lambda *a, **k: None)

    app_module._run_and_persist_scan(app_module.GROWTH_PROFILE)

    from shortlist import load_shortlist
    assert load_shortlist(app_module.SHORTLIST_PATH) == []


def test_run_and_persist_scan_dividend_profile_ignores_autopilot(tmp_path, monkeypatch):
    """Dividend has confidence_scale=None -- settings/autopilot must never
    apply to it, regardless of what's saved in scan_settings.json."""
    from scan_settings import ScanSettings, save_scan_settings

    result = _make_fake_scan_result(profile_name="dividend", confidence_by_symbol={})
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "decision_log_path", str(tmp_path / "decision_log.json"))
    monkeypatch.setattr(app_module.DIVIDEND_PROFILE, "pending_approvals_path", str(tmp_path / "pending.json"))
    monkeypatch.setattr(app_module, "SCAN_SETTINGS_PATH", str(tmp_path / "scan_settings.json"))
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "QuoteClient", lambda config: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: object())
    monkeypatch.setattr(app_module, "run_scan", lambda *a, **k: result)
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)
    save_scan_settings(app_module.SCAN_SETTINGS_PATH, ScanSettings(autopilot=True))  # would matter if misapplied

    def fail_if_called(*a, **k):
        raise AssertionError("autopilot must never fire for a profile with confidence_scale=None")
    monkeypatch.setattr(app_module, "execute_instructions", fail_if_called)

    app_module._run_and_persist_scan(app_module.DIVIDEND_PROFILE)

    from pending_approvals import load_pending_approvals
    pending = load_pending_approvals(app_module.DIVIDEND_PROFILE.pending_approvals_path)
    assert len(pending["items"]) == 1  # normal pending-approval behavior, unaffected


def test_update_settings_saves_valid_values_and_redirects(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "SCAN_SETTINGS_PATH", str(tmp_path / "scan_settings.json"))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)

    client = app_module.app.test_client()
    response = client.post("/settings", data={
        "autopilot": "on", "execute_threshold_pct": "75", "shortlist_threshold_pct": "55",
        "max_concurrent_trades": "6", "capital": "2500",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Settings saved." in response.data

    from scan_settings import load_scan_settings
    settings = load_scan_settings(app_module.SCAN_SETTINGS_PATH)
    assert settings.autopilot is True
    assert settings.execute_threshold_pct == 75.0
    assert settings.capital == 2500.0


def test_update_settings_rejects_invalid_thresholds(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "SCAN_SETTINGS_PATH", str(tmp_path / "scan_settings.json"))

    client = app_module.app.test_client()
    response = client.post("/settings", data={
        "execute_threshold_pct": "40", "shortlist_threshold_pct": "50",
        "max_concurrent_trades": "10", "capital": "1000",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Settings not saved" in response.data
    assert not os.path.exists(app_module.SCAN_SETTINGS_PATH)


def test_update_settings_unavailable_for_dividend_portfolio():
    client = app_module.app.test_client()
    response = client.post("/settings?portfolio=dividend", data={}, follow_redirects=True)
    assert response.status_code == 200
    assert b"aren&#39;t available for this portfolio" in response.data or b"aren't available for this portfolio" in response.data


def test_reset_capital_refuses_without_github_credentials(monkeypatch):
    monkeypatch.setattr(app_module, "get_github_config", lambda: None)
    client = app_module.app.test_client()
    response = client.post("/settings/reset-capital", follow_redirects=True)
    assert response.status_code == 200
    assert b"Refusing to reset capital" in response.data


def test_reset_capital_unavailable_for_dividend_portfolio():
    client = app_module.app.test_client()
    response = client.post("/settings/reset-capital?portfolio=dividend", follow_redirects=True)
    assert response.status_code == 200
    assert b"Not available for this portfolio" in response.data


def test_reset_capital_reanchors_ledger_preserving_history(tmp_path, monkeypatch):
    _stub_github_configured(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "ledger_path", ledger_path)
    monkeypatch.setattr(app_module, "SCAN_SETTINGS_PATH", str(tmp_path / "scan_settings.json"))
    monkeypatch.setattr(app_module, "push_state_to_github", lambda path: True)

    from strategy_ledger import load_or_init_ledger
    load_or_init_ledger(ledger_path, 1000.0)

    class FakeTradeClient:
        def get_positions(self):
            return []
    monkeypatch.setattr(app_module, "get_client_config", lambda: object())
    monkeypatch.setattr(app_module, "TradeClient", lambda config: FakeTradeClient())

    from scan_settings import ScanSettings, save_scan_settings
    save_scan_settings(app_module.SCAN_SETTINGS_PATH, ScanSettings(capital=2000.0))

    client = app_module.app.test_client()
    response = client.post("/settings/reset-capital", follow_redirects=True)

    assert response.status_code == 200
    assert b"Capital reset to $2,000.00" in response.data

    with open(ledger_path) as f:
        import json as json_module
        ledger = json_module.load(f)
    assert len(ledger["history"]) == 2  # seed entry preserved, plus the reset
    assert ledger["history"][-1]["capital"] == 2000.0


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

    client = app_module.app.test_client()
    response = client.post("/approve/2026-08-06-NVDA-BUY", follow_redirects=True)

    assert response.status_code == 200
    assert b"Placed BUY 1 NVDA" in response.data
    assert len(executed["instructions"]) == 1
    assert executed["instructions"][0].symbol == "NVDA"

    remaining = app_module.load_pending_approvals(pending_path)
    assert remaining["items"] == []


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
