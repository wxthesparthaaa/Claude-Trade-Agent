"""
Daily/weekly Telegram reporting logic, shared between the CLI scripts
(scripts/send_daily_update.py, scripts/send_weekly_review.py) and the
Flask app's in-process scheduler (app.py) -- one implementation, two
callers, so local runs and scheduled cloud runs behave identically.

Both entry points pull the latest state from GitHub first (so a run on
one side picks up whatever the other side last wrote) and push back
whatever they update.
"""
import json
import os
from datetime import date, timedelta

from strategy_ledger import (
    load_or_init_ledger, record_snapshot, mark_to_market_snapshot, latest_capital, capital_n_entries_ago,
    capital_as_of, gain_baseline_date,
)
from weekly_review import compute_week_stats, propose_strategy_adjustments, append_to_changelog
from telegram_notifier import get_telegram_config, send_message, format_daily_update, format_weekly_update
from state_paths import DECISION_LOG_PATH, CHANGELOG_PATH, NEWS_PATH, REGIME_PATH
from github_state_sync import pull_state_from_github, push_state_to_github
from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient
from portfolio_snapshot import refresh_snapshot, load_snapshot
from portfolio_profiles import GROWTH_PROFILE
from fomc_calendar import fomc_flag_text
from news_scanner import load_news_signal
from macro_regime import load_regime_signal
from news_analysis import build_daily_news_summary, format_news_summary_for_telegram

TARGET_MONTHLY_PCT = 0.10
CURRENT_WEIGHTS = {"momentum": 0.6, "div_yield": 0.3, "news_tilt": 0.1}


def _send_or_skip(text: str) -> bool:
    """Returns True if actually sent, False if Telegram isn't configured."""
    try:
        config = get_telegram_config()
    except FileNotFoundError as e:
        print(f"Telegram not configured, skipping send: {e}")
        return False
    send_message(text, config.bot_token, config.chat_id)
    return True


def load_recent_decisions(days: int = 7):
    if not os.path.exists(DECISION_LOG_PATH):
        return []
    with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [e for e in entries if e["date"] >= cutoff]


def _news_summary_text(profile) -> str:
    """
    Pure read of already-persisted state (never fetches live), same
    pattern as app.py's _load_news_summary -- the daily Telegram digest
    gets whatever news_signal.json currently holds, not a fresh fetch of
    its own (that's the scheduled/button-triggered news scan's job).
    """
    news_signals = {}
    if os.path.exists(NEWS_PATH):
        try:
            news_signals = load_news_signal(NEWS_PATH)
        except Exception as e:
            print(f"Failed to load news signal for digest: {type(e).__name__}: {e}")

    held_symbols = set()
    try:
        snapshot = load_snapshot(profile.snapshot_path)
        held_symbols = {p["symbol"] for p in snapshot["positions"]}
    except FileNotFoundError:
        pass

    regime = None
    if os.path.exists(REGIME_PATH):
        try:
            regime = load_regime_signal(REGIME_PATH)
        except Exception as e:
            print(f"Failed to load regime signal for digest: {type(e).__name__}: {e}")

    summary = build_daily_news_summary(news_signals, held_symbols, date.today().isoformat(), regime=regime)
    return format_news_summary_for_telegram(summary)


def run_daily_update(profile=None) -> str:
    profile = profile or GROWTH_PROFILE
    portfolio_label = profile.name.capitalize() + " Portfolio" if profile.name != "growth" else ""

    pull_state_from_github()
    load_or_init_ledger(profile.ledger_path, profile.initial_capital)

    # Mark to market against real current prices, so capital actually moves
    # day to day instead of only at trade time -- falls back to a flat
    # carry-forward if Tiger isn't reachable, same as the old behavior.
    try:
        client_config = get_client_config()
        trade_client = TradeClient(client_config)
        snapshot = refresh_snapshot(trade_client, profile.universe, profile.ledger_path, path=profile.snapshot_path)
        ledger = mark_to_market_snapshot(profile.ledger_path, snapshot["total_invested"])
    except Exception as e:
        print(f"Mark-to-market failed, carrying capital forward flat: {type(e).__name__}: {e}")
        ledger = load_or_init_ledger(profile.ledger_path, profile.initial_capital)
        ledger = record_snapshot(profile.ledger_path, latest_capital(ledger))

    current_capital = latest_capital(ledger)
    push_state_to_github(profile.ledger_path)

    previous_capital = capital_n_entries_ago(ledger, 1)
    gain_amount = current_capital - previous_capital
    gain_pct = gain_amount / previous_capital if previous_capital > 0 else 0.0

    fomc_note = fomc_flag_text(date.today())
    news_summary_text = _news_summary_text(profile)
    text = format_daily_update(
        current_capital, gain_amount, gain_pct, fomc_note=fomc_note,
        portfolio_label=portfolio_label, news_summary_text=news_summary_text,
    )
    print(text)
    sent = _send_or_skip(text)
    print("Sent to Telegram." if sent else "Not sent (Telegram unconfigured).")
    return text


def run_weekly_review() -> str:
    """
    Growth portfolio only for now -- the dividend portfolio is inactive
    until funded, and CURRENT_WEIGHTS' proposed adjustments are specific
    to growth's momentum-first scoring config, not dividend's yield-first
    one. Revisit once the dividend portfolio has real trading history.
    """
    pull_state_from_github()
    ledger = load_or_init_ledger(GROWTH_PROFILE.ledger_path, GROWTH_PROFILE.initial_capital)
    current_capital = latest_capital(ledger)
    # Date-based and reset-aware (not capital_n_entries_ago's entry-count
    # basis) -- stops at a recent "Reset capital" action instead of
    # reaching past it, so a deliberate capital re-anchor never reads as
    # a huge fake weekly gain. See gain_baseline_date's docstring.
    week_ago_capital = capital_as_of(ledger, gain_baseline_date(ledger, lookback_days=7))

    stats = compute_week_stats(
        equity_curve=[week_ago_capital, current_capital],
        position_returns={},
        target_monthly_pct=TARGET_MONTHLY_PCT,
        week_start=(date.today() - timedelta(days=7)).isoformat(),
        week_end=date.today().isoformat(),
    )

    recent_decisions = load_recent_decisions()
    if not recent_decisions:
        lessons = (
            "No real trading activity this week -- nothing has actually been "
            "bought or sold. This digest is confirming the weekly-review and "
            "Telegram pipeline works."
        )
        proposed_changes = []
    else:
        proposed_changes = propose_strategy_adjustments(CURRENT_WEIGHTS, stats)
        lessons = (
            f"Realized {stats.realized_pct:+.2%} this week against a "
            f"{stats.vs_target_pct:+.2%} gap to the weekly-equivalent target. "
            f"Best: {stats.best_position or 'n/a'}, worst: {stats.worst_position or 'n/a'}."
        )

    append_to_changelog(CHANGELOG_PATH, stats, proposed_changes, lessons)
    push_state_to_github(CHANGELOG_PATH)

    gain_amount = current_capital - week_ago_capital
    gain_pct = gain_amount / week_ago_capital if week_ago_capital > 0 else 0.0
    text = format_weekly_update(
        current_capital, gain_amount, gain_pct, lessons,
        [f"{c.parameter}: {c.old_value} -> {c.new_value} ({c.reason})" for c in proposed_changes],
    )
    print(text)
    sent = _send_or_skip(text)
    print("Sent to Telegram." if sent else "Not sent (Telegram unconfigured).")
    return text
