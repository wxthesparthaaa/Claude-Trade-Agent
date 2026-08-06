"""
Run locally with:
    python app.py
On Render, gunicorn runs this via `gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app`
-- workers MUST stay at 1, since each worker would start its own copy of
the background scheduler and duplicate every Telegram send.

Serves the "Claude Trading Agent" dashboard and runs the daily/weekly
Telegram reports, a daily automated scan (scoring/decisions, no order
placement), a weekly CFTC positioning refresh, a daily news-sentiment
refresh, a periodic position-snapshot refresh, and a periodic GitHub
state re-pull -- all on a schedule, independent of any laptop being on.

The one exception to "nothing here places an order automatically": a
human can click Approve on a specific pending item, which places that one
real order via /approve/<id>. That is a direct result of the user's own
HTTP request (their click), never triggered by the scheduler or any
autonomous code path -- see order_execution.py's docstring for the same
boundary stated from the execution side. Every other route/job here is
read-only or decision-logging only.
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, render_template, redirect, url_for, request

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient

from state_paths import (
    LEDGER_PATH, DECISION_LOG_PATH, CHANGELOG_PATH, SNAPSHOT_PATH, REGIME_PATH, NEWS_PATH, PENDING_APPROVALS_PATH,
)
from github_state_sync import pull_state_from_github, push_state_to_github
from strategy_ledger import load_or_init_ledger, latest_capital, get_cash_reserve
from portfolio_snapshot import refresh_snapshot, load_snapshot, INITIAL_CAPITAL
from universe import DEFAULT_UNIVERSE
from risk_engine import RiskConfig, RiskEngine, RiskViolation, DailyState, Position as RiskPosition
from reporting import run_daily_update, run_weekly_review
from scan_workflow import run_scan
from decision_log import write_decision_log
from pending_approvals import (
    build_pending_approvals, write_pending_approvals, load_pending_approvals,
    find_pending_approval, remove_pending_approval,
)
from order_execution import execute_instructions
from execution import OrderInstruction
from cot_adapter import fetch_positioning_signals, positioning_to_tilt
from macro_regime import update_positioning_tilt
from news_scanner import write_news_signal, SymbolNewsSignal
from alpha_vantage_news_adapter import fetch_news_sentiment, parse_news_sentiment

app = Flask(__name__)

_SLEEVE_TO_STRATEGY = {"core": "core_hold", "satellite": "satellite_momentum"}


def _run_and_persist_scan():
    """Shared by the daily automated job and the /scan route."""
    client_config = get_client_config()
    quote_client = QuoteClient(client_config)
    trade_client = TradeClient(client_config)

    result = run_scan(quote_client, trade_client)
    write_decision_log(DECISION_LOG_PATH, result.as_of, result.decisions)
    push_state_to_github(DECISION_LOG_PATH)

    items = build_pending_approvals(result)
    write_pending_approvals(PENDING_APPROVALS_PATH, items, scan_id=result.as_of)
    push_state_to_github(PENDING_APPROVALS_PATH)
    return result


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


def scheduled_scan():
    """Daily automated scan: scoring and decision-logging only, never
    places an order -- see run_scan()'s and this module's docstrings."""
    try:
        result = _run_and_persist_scan()
        print(f"Scan complete: {len(result.approved_instructions)} instruction(s) pending approval.")
    except Exception as e:
        print(f"Scheduled scan failed: {type(e).__name__}: {e}")


def scheduled_cot_update():
    """Weekly CFTC positioning refresh -- public, free, mechanical (no
    judgment call), unlike the qualitative regime research."""
    try:
        metrics = fetch_positioning_signals()
        tilt = positioning_to_tilt(metrics)
        notes = "; ".join(
            f"{label}: net={m.net_position_pct_oi:+.1%} z={m.z_score:+.2f} (as of {m.as_of[:10]})"
            for label, m in metrics.items()
        )
        update_positioning_tilt(REGIME_PATH, tilt, date.today().isoformat(), notes)
        push_state_to_github(REGIME_PATH)
        print(f"COT positioning updated: tilt={tilt:.4f}")
    except Exception as e:
        print(f"COT update failed: {type(e).__name__}: {e}")


def scheduled_news_scan():
    """
    Daily news-sentiment refresh via Alpha Vantage (free tier) -- a
    structured data fetch plus arithmetic, no LLM/agent in this loop, so
    there's no prompt-injection surface in this automated path. Skips
    cleanly if ALPHA_VANTAGE_API_KEY isn't set.
    """
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("ALPHA_VANTAGE_API_KEY not set, skipping automated news scan.")
        return
    try:
        symbols = [e.symbol for e in DEFAULT_UNIVERSE]
        raw = fetch_news_sentiment(symbols, api_key)
        signals = parse_news_sentiment(raw, symbols, as_of=date.today().isoformat())
        write_news_signal(NEWS_PATH, list(signals.values()))
        push_state_to_github(NEWS_PATH)
        print(f"News sentiment updated for {len(signals)} symbol(s).")
    except Exception as e:
        print(f"News scan failed: {type(e).__name__}: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_daily_update, CronTrigger(hour=18, minute=0, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_weekly_review, CronTrigger(day_of_week="sat", hour=9, minute=0, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_scan, CronTrigger(hour=17, minute=30, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_cot_update, CronTrigger(day_of_week="fri", hour=16, minute=30, timezone="America/New_York"))
    scheduler.add_job(scheduled_news_scan, CronTrigger(hour=8, minute=0, timezone="Asia/Singapore"))
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

    pending = load_pending_approvals(PENDING_APPROVALS_PATH)

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
        pending_items=pending["items"],
        message=request.args.get("message"),
    )


@app.route("/scan", methods=["POST"])
def scan_now():
    try:
        _run_and_persist_scan()
    except Exception as e:
        return redirect(url_for("dashboard", message=f"Scan failed: {type(e).__name__}: {e}"))
    return redirect(url_for("dashboard", message="Scan complete."))


@app.route("/review")
def review():
    decisions = []
    as_of = None
    if os.path.exists(DECISION_LOG_PATH):
        with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if entries:
            as_of = entries[-1]["date"]
            decisions = entries[-1]["decisions"]
    return render_template("review.html", decisions=decisions, as_of=as_of)


@app.route("/approve/<approval_id>", methods=["GET"])
def approve_confirm(approval_id):
    item = find_pending_approval(PENDING_APPROVALS_PATH, approval_id)
    if item is None:
        return redirect(url_for("dashboard", message="That pending approval no longer exists (a newer scan may have superseded it)."))
    return render_template("approve_confirm.html", item=item)


@app.route("/approve/<approval_id>", methods=["POST"])
def approve_execute(approval_id):
    item = find_pending_approval(PENDING_APPROVALS_PATH, approval_id)
    if item is None:
        return redirect(url_for("dashboard", message="That pending approval no longer exists (a newer scan may have superseded it)."))

    client_config = get_client_config()
    trade_client = TradeClient(client_config)

    # Re-validate risk with FRESH state -- positions/drawdown may have
    # moved since the scan that proposed this item.
    raw_positions = trade_client.get_positions() or []
    sleeve_by_symbol = {e.symbol: e.sleeve for e in DEFAULT_UNIVERSE}
    open_positions = [
        RiskPosition(
            symbol=p.contract.symbol,
            strategy=_SLEEVE_TO_STRATEGY.get(sleeve_by_symbol.get(p.contract.symbol), "core_hold"),
            notional=(p.quantity or 0) * (p.market_price or 0.0),
            premium_collected=0.0, opened_on=date.today(),
        )
        for p in raw_positions if p.contract.symbol in sleeve_by_symbol and p.quantity
    ]
    fresh_state = DailyState(date=date.today(), realized_pnl_today=0.0, open_positions=open_positions)

    ledger = load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)
    risk_engine = RiskEngine(RiskConfig())
    try:
        risk_engine.check_max_drawdown([h["capital"] for h in ledger["history"]])
        risk_engine.validate_trade(fresh_state, item["strategy_key"], item["notional"])
    except RiskViolation as e:
        return redirect(url_for("dashboard", message=f"Approval blocked by risk engine: {e}"))

    universe_by_symbol = {e.symbol: e for e in DEFAULT_UNIVERSE}
    instr = OrderInstruction(item["symbol"], item["action"], item["quantity"], item["notional"], item["reason"])
    execute_instructions(
        trade_client, client_config, universe_by_symbol, [instr],
        sleeve_by_symbol, item["capital_at_scan"], ledger_path=LEDGER_PATH,
    )

    remove_pending_approval(PENDING_APPROVALS_PATH, approval_id)
    push_state_to_github(PENDING_APPROVALS_PATH)
    return redirect(url_for("dashboard", message=f"Placed {item['action']} {item['quantity']} {item['symbol']}."))


if os.environ.get("RUN_SCHEDULER", "true") == "true":
    pull_state_from_github()
    start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
