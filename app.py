"""
Run locally with:
    python app.py
On Render, gunicorn runs this via `gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app`
-- workers MUST stay at 1, since each worker would start its own copy of
the background scheduler and duplicate every Telegram send.

Serves a read-only portfolio dashboard and runs the daily/weekly Telegram
reports, a periodic position-snapshot refresh, and a periodic GitHub
state re-pull (so a local trade shows up here without a manual restart)
on a schedule, so they keep running regardless of whether any laptop is
on. Nothing here ever places an order -- see portfolio_snapshot.py's
module docstring for the hard boundary this file also respects (no import
of tiger_order_adapter.place_market_order or execute_trades.main anywhere).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient

from state_paths import LEDGER_PATH, DECISION_LOG_PATH, CHANGELOG_PATH, SNAPSHOT_PATH
from github_state_sync import pull_state_from_github
from strategy_ledger import load_or_init_ledger, latest_capital, get_cash_reserve
from portfolio_snapshot import refresh_snapshot, load_snapshot, INITIAL_CAPITAL
from universe import DEFAULT_UNIVERSE
from risk_engine import RiskConfig
from reporting import run_daily_update, run_weekly_review

import json

app = Flask(__name__)


def scheduled_pull_state():
    """
    Re-pulls state from GitHub periodically so the dashboard picks up
    local trades (execute_trades.py --live) without needing a manual
    Render restart -- the app only pulled once at startup before this.
    Cheap (a handful of small GitHub API GETs), so this runs more often
    than the Tiger snapshot refresh below.
    """
    try:
        pulled = pull_state_from_github()
        if pulled:
            print(f"Pulled {pulled} state file(s) from GitHub.")
    except Exception as e:
        print(f"State pull failed: {type(e).__name__}: {e}")


def scheduled_refresh_snapshot():
    try:
        client_config = get_client_config()
        trade_client = TradeClient(client_config)
        refresh_snapshot(trade_client, DEFAULT_UNIVERSE, LEDGER_PATH)
        print("Portfolio snapshot refreshed.")
    except Exception as e:
        print(f"Snapshot refresh failed: {type(e).__name__}: {e}")


def scheduled_daily_update():
    try:
        run_daily_update()
    except Exception as e:
        print(f"Daily update failed: {type(e).__name__}: {e}")


def scheduled_weekly_review():
    try:
        run_weekly_review()
    except Exception as e:
        print(f"Weekly review failed: {type(e).__name__}: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_daily_update, CronTrigger(hour=18, minute=0, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_weekly_review, CronTrigger(day_of_week="sat", hour=9, minute=0, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_refresh_snapshot, IntervalTrigger(minutes=30))
    scheduler.add_job(scheduled_pull_state, IntervalTrigger(minutes=10))
    scheduler.start()
    return scheduler


@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.route("/")
def dashboard():
    ledger = load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)
    total_capital = latest_capital(ledger)
    cash_reserve = get_cash_reserve(ledger)

    try:
        snapshot = load_snapshot(SNAPSHOT_PATH)
        positions = snapshot["positions"]
    except FileNotFoundError:
        positions = []

    decisions = []
    if os.path.exists(DECISION_LOG_PATH):
        with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
            entries = json.load(f)
        decisions = entries[-1]["decisions"] if entries else []

    changelog = []
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            changelog = json.load(f)

    risk_config = RiskConfig()
    total_invested = sum(p["market_value"] for p in positions)
    utilization_pct = total_invested / risk_config.max_capital_at_risk if risk_config.max_capital_at_risk else 0.0

    return render_template(
        "dashboard.html",
        total_capital=total_capital,
        cash_reserve=cash_reserve,
        total_invested=total_invested,
        utilization_pct=utilization_pct,
        max_capital_at_risk=risk_config.max_capital_at_risk,
        positions=positions,
        equity_history=ledger["history"],
        decisions=decisions,
        changelog=list(reversed(changelog))[:5],
    )


if os.environ.get("RUN_SCHEDULER", "true") == "true":
    pull_state_from_github()
    start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
