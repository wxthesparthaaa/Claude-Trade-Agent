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

from strategy_ledger import load_or_init_ledger, record_snapshot, latest_capital, capital_n_entries_ago
from weekly_review import compute_week_stats, propose_strategy_adjustments, append_to_changelog
from telegram_notifier import get_telegram_config, send_message, format_daily_update, format_weekly_update
from state_paths import LEDGER_PATH, DECISION_LOG_PATH, CHANGELOG_PATH
from github_state_sync import pull_state_from_github, push_state_to_github

INITIAL_CAPITAL = 1000.0
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


def run_daily_update() -> str:
    pull_state_from_github()
    load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)

    ledger = load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)
    current_capital = latest_capital(ledger)
    ledger = record_snapshot(LEDGER_PATH, current_capital)
    push_state_to_github(LEDGER_PATH)

    previous_capital = capital_n_entries_ago(ledger, 1)
    gain_amount = current_capital - previous_capital
    gain_pct = gain_amount / previous_capital if previous_capital > 0 else 0.0

    text = format_daily_update(current_capital, gain_amount, gain_pct)
    print(text)
    sent = _send_or_skip(text)
    print("Sent to Telegram." if sent else "Not sent (Telegram unconfigured).")
    return text


def run_weekly_review() -> str:
    pull_state_from_github()
    ledger = load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)
    current_capital = latest_capital(ledger)
    week_ago_capital = capital_n_entries_ago(ledger, 7)

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
