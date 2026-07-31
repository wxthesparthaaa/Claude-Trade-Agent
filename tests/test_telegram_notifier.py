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
from telegram_notifier import format_daily_update, format_weekly_update, get_telegram_config


def test_format_daily_update_contains_required_fields():
    text = format_daily_update(capital=1023.45, gain_amount=23.45, gain_pct=0.0235)
    assert "Total Capital: $1,023.45" in text
    assert "Gains for the day: $23.45" in text
    assert "2.35%" in text


def test_format_daily_update_handles_negative_gain():
    text = format_daily_update(capital=950.0, gain_amount=-50.0, gain_pct=-0.05)
    assert "$-50.00" in text
    assert "-5.00%" in text


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


def test_get_telegram_config_raises_when_not_configured(tmp_path, monkeypatch):
    import telegram_notifier
    monkeypatch.setattr(telegram_notifier, "CONFIG_PATH", str(tmp_path / "does_not_exist.properties"))
    with pytest.raises(FileNotFoundError):
        telegram_notifier.get_telegram_config()


def test_get_telegram_config_parses_file(tmp_path, monkeypatch):
    import telegram_notifier
    config_file = tmp_path / "telegram_config.properties"
    config_file.write_text("bot_token=123456:ABC-DEF\nchat_id=987654321\n", encoding="utf-8")
    monkeypatch.setattr(telegram_notifier, "CONFIG_PATH", str(config_file))

    config = telegram_notifier.get_telegram_config()
    assert config.bot_token == "123456:ABC-DEF"
    assert config.chat_id == "987654321"
