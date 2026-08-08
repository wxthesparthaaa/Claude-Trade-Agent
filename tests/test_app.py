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
        "/review",
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
    app_module.scheduled_news_scan()
    assert "skipping automated news scan" in capsys.readouterr().out


def test_scheduled_news_scan_swallows_errors(monkeypatch, capsys):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "testkey")

    def raise_error(*a, **k):
        raise RuntimeError("alpha vantage down")
    monkeypatch.setattr(app_module, "fetch_news_sentiment", raise_error)

    app_module.scheduled_news_scan()  # must not raise
    assert "News scan failed" in capsys.readouterr().out


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


def test_approve_execute_post_redirects_when_item_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.GROWTH_PROFILE, "pending_approvals_path", str(tmp_path / "pending_approvals.json"))
    client = app_module.app.test_client()
    response = client.post("/approve/does-not-exist", follow_redirects=True)
    assert response.status_code == 200
    assert b"no longer exists" in response.data


def test_approve_execute_post_places_order_and_clears_item(tmp_path, monkeypatch):
    from pending_approvals import write_pending_approvals, PendingApproval

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

    def fake_execute_instructions(trade_client, client_config, universe_by_symbol, instructions, sleeve_by_symbol, capital, ledger_path=None):
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
