"""
Run with:
    python scripts/send_daily_update.py

Records today's strategy-capital snapshot (see strategy_ledger.py -- this
is NOT Tiger's paper account balance, which defaults to $1,000,000 in
sandbox cash and has nothing to do with this strategy's $1,000) and sends
a Telegram update: Total Capital, Gains for the day (amount + %).

Until the order-execution module exists, nothing is actually trading, so
this will show $0.00 / 0.00% every day -- that's expected and honestly
reported, not a bug. This script's job right now is proving the daily
notification pipeline works end-to-end.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from strategy_ledger import load_or_init_ledger, record_snapshot, latest_capital, capital_n_entries_ago
from telegram_notifier import get_telegram_config, send_message, format_daily_update

INITIAL_CAPITAL = 1000.0
LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "strategy_ledger.json")


def main():
    load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)

    # No execution module yet -- carry the same capital forward. Once real
    # (paper) trades exist, replace this with the actual post-trade equity.
    ledger = load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)
    current_capital = latest_capital(ledger)
    ledger = record_snapshot(LEDGER_PATH, current_capital)

    previous_capital = capital_n_entries_ago(ledger, 1)
    gain_amount = current_capital - previous_capital
    gain_pct = gain_amount / previous_capital if previous_capital > 0 else 0.0

    text = format_daily_update(current_capital, gain_amount, gain_pct)
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
