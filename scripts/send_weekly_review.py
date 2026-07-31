"""
Run with:
    python scripts/send_weekly_review.py
Intended to run every Saturday.

Computes this week's stats from strategy_ledger.json, checks
config/decision_log.json for any real activity in the past 7 days, and
sends a Telegram weekly digest: Total Capital, Gains for the week, Lessons
observed, Changes to strategy (if any).

Until the order-execution module exists there's no real trading activity to
review -- this script detects that (no decision-log entries in the past 7
days) and reports it honestly rather than inventing "lessons" or proposing
strategy tweaks based on zero real trades. Once execution ships and trades
start appearing in the decision log, propose_strategy_adjustments starts
actually running.
"""
import sys
import os
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from strategy_ledger import load_or_init_ledger, latest_capital, capital_n_entries_ago
from weekly_review import compute_week_stats, propose_strategy_adjustments, append_to_changelog
from telegram_notifier import get_telegram_config, send_message, format_weekly_update

INITIAL_CAPITAL = 1000.0
TARGET_MONTHLY_PCT = 0.10
LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "strategy_ledger.json")
DECISION_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "decision_log.json")
CHANGELOG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "strategy_changelog.json")

CURRENT_WEIGHTS = {"momentum": 0.6, "div_yield": 0.3, "news_tilt": 0.1}


def load_recent_decisions(days: int = 7):
    if not os.path.exists(DECISION_LOG_PATH):
        return []
    with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [e for e in entries if e["date"] >= cutoff]


def main():
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
            "No real trading activity this week -- the order-execution module "
            "isn't built yet, so nothing has actually been bought or sold. This "
            "digest is confirming the weekly-review and Telegram pipeline works."
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

    gain_amount = current_capital - week_ago_capital
    gain_pct = gain_amount / week_ago_capital if week_ago_capital > 0 else 0.0
    text = format_weekly_update(
        current_capital, gain_amount, gain_pct, lessons,
        [f"{c.parameter}: {c.old_value} -> {c.new_value} ({c.reason})" for c in proposed_changes],
    )
    print(text)

    try:
        config = get_telegram_config()
    except FileNotFoundError as e:
        print(f"\nTelegram not configured yet, skipping send: {e}")
        return

    send_message(text, config.bot_token, config.chat_id)
    print("\nSent to Telegram.")


if __name__ == "__main__":
    main()
