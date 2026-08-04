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


def test_no_order_placement_routes_exist():
    rules = [str(r) for r in app_module.app.url_map.iter_rules()]
    assert set(rules) == {"/static/<path:filename>", "/health", "/"}


def test_dashboard_renders_with_no_state_present(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(app_module, "SNAPSHOT_PATH", str(tmp_path / "portfolio_snapshot.json"))
    monkeypatch.setattr(app_module, "DECISION_LOG_PATH", str(tmp_path / "decision_log.json"))
    monkeypatch.setattr(app_module, "CHANGELOG_PATH", str(tmp_path / "changelog.json"))

    client = app_module.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Total Capital" in text
    assert "$1000.00" in text or "$1,000.00" in text


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


def test_scheduled_daily_update_swallows_errors(monkeypatch, capsys):
    def raise_error():
        raise RuntimeError("telegram down")
    monkeypatch.setattr(app_module, "run_daily_update", raise_error)

    app_module.scheduled_daily_update()  # must not raise
    assert "Daily update failed" in capsys.readouterr().out


def test_scheduled_weekly_review_swallows_errors(monkeypatch, capsys):
    def raise_error():
        raise RuntimeError("telegram down")
    monkeypatch.setattr(app_module, "run_weekly_review", raise_error)

    app_module.scheduled_weekly_review()  # must not raise
    assert "Weekly review failed" in capsys.readouterr().out
