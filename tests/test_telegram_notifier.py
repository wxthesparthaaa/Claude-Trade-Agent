"""
Run with:
    pytest tests/test_telegram_notifier.py -v

Only the formatting functions and config loading are tested here -- no real
HTTP call is made (send_message isn't exercised against the network).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from telegram_notifier import format_daily_update, format_weekly_update, format_order_placed_update, get_telegram_config
from execution import OrderInstruction


def test_format_daily_update_contains_required_fields():
    text = format_daily_update(capital=1023.45, gain_amount=23.45, gain_pct=0.0235)
    assert "Total Capital: $1,023.45" in text
    assert "Gains for the day: $23.45" in text
    assert "2.35%" in text


def test_format_daily_update_handles_negative_gain():
    text = format_daily_update(capital=950.0, gain_amount=-50.0, gain_pct=-0.05)
    assert "$-50.00" in text
    assert "-5.00%" in text


def test_format_daily_update_omits_fomc_note_by_default():
    text = format_daily_update(capital=1000.0, gain_amount=0.0, gain_pct=0.0)
    assert "FOMC" not in text


def test_format_daily_update_includes_fomc_note_when_given():
    text = format_daily_update(capital=1000.0, gain_amount=0.0, gain_pct=0.0, fomc_note="FOMC meeting in 2 days.")
    assert "FOMC meeting in 2 days." in text


def test_format_daily_update_omits_portfolio_label_by_default():
    text = format_daily_update(capital=1000.0, gain_amount=0.0, gain_pct=0.0)
    assert "[" not in text


def test_format_daily_update_includes_portfolio_label_when_given():
    text = format_daily_update(capital=30000.0, gain_amount=0.0, gain_pct=0.0, portfolio_label="Dividend Portfolio")
    assert text.startswith("[Dividend Portfolio]")


def test_format_weekly_update_contains_all_required_sections():
    text = format_weekly_update(
        capital=1080.0, gain_amount=80.0, gain_pct=0.08,
        lessons="Momentum picks outperformed core this week.",
        strategy_changes=["Increased momentum weight from 0.60 to 0.65"],
    )
    assert "Total Capital: $1,080.00" in text
    assert "Gains for the week: $80.00" in text
    assert "Lessons observed:" in text
    assert "Momentum picks outperformed core this week." in text
    assert "Changes to strategy (if any):" in text
    assert "Increased momentum weight from 0.60 to 0.65" in text


def test_format_weekly_update_no_changes_says_none():
    text = format_weekly_update(capital=1000.0, gain_amount=0.0, gain_pct=0.0, lessons="Flat week.", strategy_changes=[])
    assert "Changes to strategy (if any):\nNone" in text


def test_format_order_placed_update_shows_per_order_pct_and_utilization():
    orders = [
        OrderInstruction(symbol="SCHD", action="BUY", quantity=5, notional=166.92, reason="core"),
        OrderInstruction(symbol="VYM", action="BUY", quantity=1, notional=161.79, reason="core"),
        OrderInstruction(symbol="NVDA", action="BUY", quantity=1, notional=196.22, reason="satellite"),
    ]
    text = format_order_placed_update(orders, total_capital=1000.0, total_invested_after=524.93)

    assert "BUY 5 SCHD = $166.92 (16.7% of $1,000)" in text
    assert "BUY 1 VYM = $161.79 (16.2% of $1,000)" in text
    assert "BUY 1 NVDA = $196.22 (19.6% of $1,000)" in text
    assert "Total invested: $524.93 of $1,000.00 (52.5% margin used)" in text
    assert "Cash remaining: $475.07 (47.5%)" in text


def test_format_order_placed_update_handles_sell_orders():
    orders = [OrderInstruction(symbol="AMD", action="SELL", quantity=3, notional=450.0, reason="exit")]
    text = format_order_placed_update(orders, total_capital=1000.0, total_invested_after=200.0)
    assert "SELL 3 AMD = $450.00 (45.0% of $1,000)" in text
    assert "Total invested: $200.00 of $1,000.00 (20.0% margin used)" in text


def test_format_order_placed_update_empty_orders_still_reports_utilization():
    text = format_order_placed_update([], total_capital=1000.0, total_invested_after=0.0)
    assert "Total invested: $0.00 of $1,000.00 (0.0% margin used)" in text
    assert "Cash remaining: $1,000.00 (100.0%)" in text


def test_get_telegram_config_raises_when_not_configured(tmp_path, monkeypatch):
    import telegram_notifier
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(telegram_notifier, "CONFIG_PATH", str(tmp_path / "does_not_exist.properties"))
    with pytest.raises(FileNotFoundError):
        telegram_notifier.get_telegram_config()


def test_get_telegram_config_parses_file(tmp_path, monkeypatch):
    import telegram_notifier
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    config_file = tmp_path / "telegram_config.properties"
    config_file.write_text("bot_token=123456:ABC-DEF\nchat_id=987654321\n", encoding="utf-8")
    monkeypatch.setattr(telegram_notifier, "CONFIG_PATH", str(config_file))

    config = telegram_notifier.get_telegram_config()
    assert config.bot_token == "123456:ABC-DEF"
    assert config.chat_id == "987654321"


def test_get_telegram_config_prefers_env_vars_over_file(tmp_path, monkeypatch):
    import telegram_notifier
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat-id")
    config_file = tmp_path / "telegram_config.properties"
    config_file.write_text("bot_token=file-token\nchat_id=file-chat-id\n", encoding="utf-8")
    monkeypatch.setattr(telegram_notifier, "CONFIG_PATH", str(config_file))

    config = telegram_notifier.get_telegram_config()
    assert config.bot_token == "env-token"
    assert config.chat_id == "env-chat-id"


def test_get_telegram_config_env_vars_work_without_local_file(tmp_path, monkeypatch):
    import telegram_notifier
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat-id")
    monkeypatch.setattr(telegram_notifier, "CONFIG_PATH", str(tmp_path / "does_not_exist.properties"))

    config = telegram_notifier.get_telegram_config()
    assert config.bot_token == "env-token"
    assert config.chat_id == "env-chat-id"
