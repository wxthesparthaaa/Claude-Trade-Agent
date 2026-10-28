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
from telegram_notifier import (
    format_daily_update, format_weekly_summary, format_order_placed_update, get_telegram_config,
    format_holdings_line, format_trades_since, explain_order_reason,
)
from execution import OrderInstruction


def test_removed_noise_formatters_are_gone():
    """The pending-approvals alert and the shortlist digest were removed
    from Telegram on purpose -- importing them again would mean the noise
    came back."""
    import telegram_notifier
    assert not hasattr(telegram_notifier, "format_pending_approvals_alert")
    assert not hasattr(telegram_notifier, "format_shortlist_telegram")


def test_format_daily_update_contains_required_fields():
    text = format_daily_update(capital=1023.45, gain_amount=23.45, gain_pct=0.0235)
    assert "Daily summary" in text
    assert "Total Capital: $1,023.45" in text
    assert "Change since the last update: +$23.45 (+2.35%)" in text


def test_format_daily_update_handles_negative_gain():
    text = format_daily_update(capital=950.0, gain_amount=-50.0, gain_pct=-0.05)
    assert "Change since the last update: -$50.00 (-5.00%)" in text


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
    assert text.startswith("[Dividend Portfolio] Daily summary")


def test_format_daily_update_omits_news_summary_by_default():
    text = format_daily_update(capital=1000.0, gain_amount=0.0, gain_pct=0.0)
    assert "Notable news" not in text


def test_format_daily_update_includes_news_summary_when_given():
    text = format_daily_update(capital=1000.0, gain_amount=0.0, gain_pct=0.0,
                                news_summary_text="Notable news today:\n  NVDA (+0.60): tailwind")
    assert "Notable news today:" in text
    assert "NVDA (+0.60): tailwind" in text


def test_format_daily_update_includes_holdings_and_trades_in_order():
    text = format_daily_update(
        capital=4874.23, gain_amount=165.93, gain_pct=0.0352,
        holdings_text="Holdings: 5 positions, 85% invested / 15% cash",
        trades_text="Trades since the last update: none",
    )
    assert text.index("Holdings:") < text.index("Trades since the last update")


def test_format_daily_update_has_no_macro_regime_jargon():
    text = format_daily_update(capital=1000.0, gain_amount=0.0, gain_pct=0.0)
    for jargon in ("Futures positioning", "tilt=", "Short-selling gate", "breadth"):
        assert jargon not in text


def test_format_holdings_line_two_sleeve_portfolio_shows_targets():
    positions = [
        {"sleeve": "core", "market_value": 800.0},
        {"sleeve": "satellite", "market_value": 2000.0},
        {"sleeve": "satellite", "market_value": 1000.0},
    ]
    text = format_holdings_line(positions, total_capital=5000.0, sleeve_targets={"core": 0.40, "satellite": 0.60})
    assert "Holdings: 3 positions, 76% invested / 24% cash" in text
    assert "Core 16% (target 40%)" in text
    assert "Satellite 60% (target 60%)" in text


def test_format_holdings_line_single_sleeve_skips_sleeve_breakdown():
    positions = [{"sleeve": "core", "market_value": 4000.0}]
    text = format_holdings_line(positions, total_capital=5000.0)
    assert text == "Holdings: 1 position, 80% invested / 20% cash"


def test_format_holdings_line_empty_for_nonpositive_capital():
    assert format_holdings_line([], total_capital=0.0) == ""


def test_format_trades_since_groups_buys_and_sells_and_totals_commission():
    fills = [
        {"action": "BUY", "symbol": "ASX", "quantity": 24, "commission": 2.98},
        {"action": "SELL", "symbol": "AEHR", "quantity": 6, "commission": 2.98},
        {"action": "BUY", "symbol": "MU", "quantity": 1, "commission": 2.98},
    ]
    text = format_trades_since(fills)
    assert "3 orders, $8.94 in commissions" in text
    assert "  BUY: ASX 24, MU 1" in text
    assert "  SELL: AEHR 6" in text


def test_format_trades_since_none():
    assert format_trades_since([]) == "Trades since the last update: none"


def test_explain_order_reason_translates_strategy_jargon():
    assert explain_order_reason("stop_loss: down -39.5% from entry") == "stop-loss hit (-39.5% from entry)"
    assert explain_order_reason("momentum_reversal: momentum at -8.0%, below -5.0% threshold") == \
        "trend turned negative -- exiting"
    assert explain_order_reason("no longer a target position -- full exit") == "no longer one of the top picks -- selling out"
    assert explain_order_reason("increase toward target 21% of capital (satellite)") == \
        "buying up to its target size (21% of capital)"
    assert explain_order_reason("reduce toward target 14% of capital (core)") == \
        "trimming back to its target size (14% of capital)"
    assert explain_order_reason("manual full close") == "manual full close"  # unknown reasons pass through


def test_format_weekly_summary_shows_pnl_and_realized_per_symbol():
    text = format_weekly_summary(
        capital=1080.0, gain_amount=80.0, gain_pct=0.08,
        realized_by_symbol={"NVDA": 87.9, "AEHR": -165.39},
    )
    assert "Weekly summary" in text
    assert "P&L for the week: +$80.00 (+8.00%), net of commissions" in text
    assert "Total Capital: $1,080.00" in text
    assert "Realized on trades closed this week: -$77.49" in text
    assert text.index("NVDA: +$87.90") < text.index("AEHR: -$165.39")  # best first


def test_format_weekly_summary_no_closed_trades_and_no_review_sections():
    text = format_weekly_summary(capital=1000.0, gain_amount=-12.5, gain_pct=-0.0125, realized_by_symbol={})
    assert "P&L for the week: -$12.50 (-1.25%)" in text
    assert "No trades closed this week." in text
    assert "Auto-pause changes" not in text
    assert "Lessons" not in text and "Changes to strategy" not in text


def test_format_weekly_summary_shows_label_and_pause_changes():
    text = format_weekly_summary(
        capital=1000.0, gain_amount=0.0, gain_pct=0.0, realized_by_symbol={},
        portfolio_label="Dividend Portfolio",
        pause_changes=["Auto-paused NVDA for 2 weeks: net-negative 3 weeks running"],
    )
    assert text.startswith("[Dividend Portfolio]\nWeekly summary")
    assert "Auto-paused NVDA for 2 weeks: net-negative 3 weeks running" in text


def test_format_order_placed_update_shows_label_per_order_pct_reason_and_utilization():
    orders = [
        OrderInstruction(symbol="AEHR", action="SELL", quantity=6, notional=323.10, reason="stop_loss: down -39.5% from entry"),
        OrderInstruction(symbol="ASX", action="BUY", quantity=24, notional=932.88,
                         reason="increase toward target 21% of capital (satellite)"),
    ]
    text = format_order_placed_update(orders, total_capital=4640.01, total_invested_after=3914.67,
                                      portfolio_label="Growth Portfolio")

    assert text.startswith("[Growth Portfolio] Orders placed:")
    assert "SELL 6 AEHR = $323.10 (7.0% of capital) -- stop-loss hit (-39.5% from entry)" in text
    assert "BUY 24 ASX = $932.88 (20.1% of capital) -- buying up to its target size (21% of capital)" in text
    assert "Invested: $3,914.67 of $4,640.01 (84.4%) | cash: $725.34 (15.6%)" in text
    assert "margin" not in text  # this account doesn't trade on margin; "margin used" was misleading


def test_format_order_placed_update_handles_sell_orders_without_a_reason():
    orders = [OrderInstruction(symbol="AMD", action="SELL", quantity=3, notional=450.0, reason="")]
    text = format_order_placed_update(orders, total_capital=1000.0, total_invested_after=200.0)
    assert "SELL 3 AMD = $450.00 (45.0% of capital)" in text
    assert " -- " not in text
    assert "Invested: $200.00 of $1,000.00 (20.0%) | cash: $800.00 (80.0%)" in text


def test_format_order_placed_update_empty_orders_still_reports_utilization():
    text = format_order_placed_update([], total_capital=1000.0, total_invested_after=0.0)
    assert "Invested: $0.00 of $1,000.00 (0.0%) | cash: $1,000.00 (100.0%)" in text


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
