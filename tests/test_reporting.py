"""
Run with:
    pytest tests/test_reporting.py -v

GitHub sync and Telegram sending are stubbed out -- these tests are about
reporting.py's own logic (extracted from the CLI scripts), not the network.
"""
import sys
import os
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import reporting
from strategy_ledger import record_snapshot
from decision_log import DecisionRecord, write_decision_log


def _stub_no_github(monkeypatch):
    monkeypatch.setattr(reporting, "pull_state_from_github", lambda: 0)
    monkeypatch.setattr(reporting, "push_state_to_github", lambda p: False)


def _stub_telegram_unconfigured(monkeypatch):
    def raise_not_found():
        raise FileNotFoundError("not configured")
    monkeypatch.setattr(reporting, "get_telegram_config", raise_not_found)


def _stub_telegram_configured(monkeypatch, sent_messages):
    class FakeConfig:
        bot_token = "tok"
        chat_id = "chat"
    monkeypatch.setattr(reporting, "get_telegram_config", lambda: FakeConfig())
    monkeypatch.setattr(reporting, "send_message", lambda text, token, chat_id: sent_messages.append(text))


def _stub_mark_to_market(monkeypatch, total_invested):
    """Bypasses the real Tiger calls -- refresh_snapshot is the only thing
    run_daily_update needs from that path, so stub it directly rather than
    mocking get_client_config/TradeClient individually."""
    monkeypatch.setattr(reporting, "get_client_config", lambda: object())
    monkeypatch.setattr(reporting, "TradeClient", lambda config: object())
    monkeypatch.setattr(reporting, "refresh_snapshot", lambda *a, **k: {"total_invested": total_invested})


def _stub_mark_to_market_unavailable(monkeypatch):
    def raise_error():
        raise RuntimeError("Tiger unreachable")
    monkeypatch.setattr(reporting, "get_client_config", raise_error)


def test_run_daily_update_seeds_ledger_and_reports_flat_on_first_run(tmp_path, monkeypatch):
    _stub_no_github(monkeypatch)
    _stub_telegram_unconfigured(monkeypatch)
    _stub_mark_to_market(monkeypatch, total_invested=0.0)
    monkeypatch.setattr(reporting.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))

    text = reporting.run_daily_update()
    assert "Total Capital: $1,000.00" in text
    assert "Gains for the day: $0.00" in text


def test_run_daily_update_falls_back_to_flat_carry_forward_when_tiger_unavailable(tmp_path, monkeypatch):
    _stub_no_github(monkeypatch)
    _stub_telegram_unconfigured(monkeypatch)
    _stub_mark_to_market_unavailable(monkeypatch)
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(reporting.GROWTH_PROFILE, "ledger_path", str(ledger_path))

    record_snapshot(str(ledger_path), 1000.0, as_of="2026-07-30")
    record_snapshot(str(ledger_path), 950.0, as_of="2026-07-31")

    text = reporting.run_daily_update()
    assert "Total Capital: $950.00" in text


def test_run_daily_update_marks_to_market_against_real_positions(tmp_path, monkeypatch):
    _stub_no_github(monkeypatch)
    _stub_telegram_unconfigured(monkeypatch)
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(reporting.GROWTH_PROFILE, "ledger_path", str(ledger_path))

    from strategy_ledger import load_or_init_ledger, apply_trade_and_snapshot
    load_or_init_ledger(str(ledger_path), 1000.0)
    apply_trade_and_snapshot(str(ledger_path), cash_delta=-500.0, positions_value_now=500.0, as_of="2026-08-01")

    # Next day: no trade, but the position is now worth more.
    _stub_mark_to_market(monkeypatch, total_invested=540.0)
    text = reporting.run_daily_update()

    assert "Total Capital: $1,040.00" in text  # cash_reserve 500 + repriced 540
    assert "Gains for the day: $40.00" in text


def test_run_daily_update_sends_when_telegram_configured(tmp_path, monkeypatch):
    _stub_no_github(monkeypatch)
    sent = []
    _stub_telegram_configured(monkeypatch, sent)
    _stub_mark_to_market(monkeypatch, total_invested=0.0)
    monkeypatch.setattr(reporting.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))

    reporting.run_daily_update()
    assert len(sent) == 1
    assert "Total Capital" in sent[0]


def test_run_weekly_review_reports_no_activity_when_decision_log_empty(tmp_path, monkeypatch):
    _stub_no_github(monkeypatch)
    _stub_telegram_unconfigured(monkeypatch)
    monkeypatch.setattr(reporting.GROWTH_PROFILE, "ledger_path", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(reporting, "DECISION_LOG_PATH", str(tmp_path / "decision_log.json"))
    monkeypatch.setattr(reporting, "CHANGELOG_PATH", str(tmp_path / "changelog.json"))

    text = reporting.run_weekly_review()
    assert "No real trading activity this week" in text
    assert "Changes to strategy (if any):\nNone" in text


def test_run_weekly_review_proposes_changes_when_activity_exists(tmp_path, monkeypatch):
    _stub_no_github(monkeypatch)
    _stub_telegram_unconfigured(monkeypatch)
    ledger_path = tmp_path / "ledger.json"
    decision_log_path = tmp_path / "decision_log.json"
    changelog_path = tmp_path / "changelog.json"
    monkeypatch.setattr(reporting.GROWTH_PROFILE, "ledger_path", str(ledger_path))
    monkeypatch.setattr(reporting, "DECISION_LOG_PATH", str(decision_log_path))
    monkeypatch.setattr(reporting, "CHANGELOG_PATH", str(changelog_path))

    week_ago = (date.today() - timedelta(days=7)).isoformat()
    recent = (date.today() - timedelta(days=2)).isoformat()
    record_snapshot(str(ledger_path), 1000.0, as_of=week_ago)
    record_snapshot(str(ledger_path), 950.0, as_of=date.today().isoformat())
    write_decision_log(
        str(decision_log_path), recent,
        [DecisionRecord(recent, "buy", "NVDA", "satellite", "top pick", score=0.3)],
    )

    text = reporting.run_weekly_review()
    assert "No real trading activity" not in text
    assert os.path.exists(changelog_path)
    with open(changelog_path) as f:
        entries = json.load(f)
    assert len(entries) == 1


def test_load_recent_decisions_filters_by_cutoff(tmp_path, monkeypatch):
    decision_log_path = tmp_path / "decision_log.json"
    monkeypatch.setattr(reporting, "DECISION_LOG_PATH", str(decision_log_path))
    write_decision_log(str(decision_log_path), "2020-01-01", [
        DecisionRecord("2020-01-01", "buy", "OLD", "core", "stale", score=0.1),
    ])
    assert reporting.load_recent_decisions(days=7) == []


def test_load_recent_decisions_returns_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, "DECISION_LOG_PATH", str(tmp_path / "does_not_exist.json"))
    assert reporting.load_recent_decisions() == []
