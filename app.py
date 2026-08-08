"""
Run locally with:
    python app.py
On Render, gunicorn runs this via `gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app`
-- workers MUST stay at 1, since each worker would start its own copy of
the background scheduler and duplicate every Telegram send.

Serves the "Claude Trading Agent" dashboard for TWO portfolios -- the
existing $1,000 growth/momentum portfolio and a new dividend/income
portfolio (dormant until funded, see portfolio_profiles.py) -- and runs
the daily/weekly Telegram reports, a daily automated scan per active
portfolio (scoring/decisions, no order placement), a weekly CFTC
positioning refresh, a daily market-breadth (RSP/SPY) refresh, a daily
news-sentiment refresh, a periodic position-snapshot refresh, and a
periodic GitHub state re-pull -- all on a schedule, independent of any
laptop being on. Every route defaults to the growth portfolio
(?portfolio=growth) so existing bookmarks, the UptimeRobot /health
check, and Telegram links keep working unchanged.

The one exception to "nothing here places an order automatically": a
human can click Approve on a specific pending item, which places that one
real order via /approve/<id>. That is a direct result of the user's own
HTTP request (their click), never triggered by the scheduler or any
autonomous code path -- see order_execution.py's docstring for the same
boundary stated from the execution side. Every other route/job here is
read-only or decision-logging only. This is unchanged by shorting: a
short is opened/covered through the exact same approval gate as a long,
see scan_workflow.py's docstring for how shorting fits the existing
BUY/SELL pipeline with no new order type.
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

from state_paths import REGIME_PATH, NEWS_PATH, CHANGELOG_PATH
from github_state_sync import pull_state_from_github, push_state_to_github, get_github_config
from strategy_ledger import load_or_init_ledger, latest_capital, get_cash_reserve
from portfolio_snapshot import refresh_snapshot, load_snapshot
from portfolio_profiles import GROWTH_PROFILE, DIVIDEND_PROFILE, ACTIVE_PROFILES, get_profile
from risk_engine import RiskEngine, RiskViolation, DailyState, Position as RiskPosition
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
from market_breadth import fetch_breadth_prices, compute_ratio_series, compute_breadth_signal
from macro_regime import update_positioning_tilt, update_breadth_signal
from news_scanner import write_news_signal, SymbolNewsSignal
from alpha_vantage_news_adapter import fetch_news_sentiment, parse_news_sentiment

app = Flask(__name__)


def _run_and_persist_scan(profile):
    """Shared by the daily automated job (per active profile) and the /scan route."""
    client_config = get_client_config()
    quote_client = QuoteClient(client_config)
    trade_client = TradeClient(client_config)

    result = run_scan(quote_client, trade_client, profile)
    write_decision_log(profile.decision_log_path, result.as_of, result.decisions)
    push_state_to_github(profile.decision_log_path)

    items = build_pending_approvals(result, max_capital_at_risk=profile.risk_config.max_capital_at_risk)
    write_pending_approvals(profile.pending_approvals_path, items, scan_id=result.as_of)
    push_state_to_github(profile.pending_approvals_path)
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
        for profile in ACTIVE_PROFILES:
            refresh_snapshot(trade_client, profile.universe, profile.ledger_path, path=profile.snapshot_path)
        print("Portfolio snapshot(s) refreshed.")
    except Exception as e:
        print(f"Snapshot refresh failed: {type(e).__name__}: {e}")


def scheduled_daily_update():
    for profile in ACTIVE_PROFILES:
        try:
            run_daily_update(profile)
        except Exception as e:
            print(f"Daily update failed for '{profile.name}': {type(e).__name__}: {e}")


def scheduled_weekly_review():
    try:
        run_weekly_review()
    except Exception as e:
        print(f"Weekly review failed: {type(e).__name__}: {e}")


def scheduled_scan():
    """Daily automated scan, once per active portfolio: scoring and
    decision-logging only, never places an order -- see run_scan()'s and
    this module's docstrings."""
    for profile in ACTIVE_PROFILES:
        try:
            result = _run_and_persist_scan(profile)
            print(f"'{profile.name}' scan complete: {len(result.approved_instructions)} instruction(s) pending approval.")
        except Exception as e:
            print(f"Scheduled scan failed for '{profile.name}': {type(e).__name__}: {e}")


def scheduled_cot_update():
    """Weekly CFTC positioning refresh -- public, free, mechanical (no
    judgment call), unlike the qualitative regime research. Shared across
    portfolios (a macro fact, not portfolio-specific)."""
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


def scheduled_breadth_update():
    """Daily RSP/SPY market-breadth refresh (see market_breadth.py) --
    shared across portfolios, same as COT. Skips cleanly (rather than
    writing anything) if there isn't enough price history yet."""
    try:
        client_config = get_client_config()
        quote_client = QuoteClient(client_config)
        rsp_prices, spy_prices = fetch_breadth_prices(quote_client)
        ratio_series = compute_ratio_series(rsp_prices, spy_prices)
        signal = compute_breadth_signal(ratio_series)
        if signal is None:
            print("Not enough RSP/SPY history yet for a breadth signal, skipping.")
            return
        notes = f"RSP/SPY ratio={signal.ratio}, trend={signal.trend}, roc_zscore={signal.roc_zscore:+.2f}"
        update_breadth_signal(REGIME_PATH, signal.tilt, signal.trend, signal.at_edge, signal.as_of, notes)
        push_state_to_github(REGIME_PATH)
        print(f"Market breadth updated: trend={signal.trend}, at_edge={signal.at_edge}, tilt={signal.tilt:.4f}")
    except Exception as e:
        print(f"Breadth update failed: {type(e).__name__}: {e}")


def scheduled_news_scan():
    """
    Daily news-sentiment refresh via Alpha Vantage (free tier) -- a
    structured data fetch plus arithmetic, no LLM/agent in this loop, so
    there's no prompt-injection surface in this automated path. Skips
    cleanly if ALPHA_VANTAGE_API_KEY isn't set. Covers every active
    portfolio's universe (a shared news signal file, symbols are
    disjoint across portfolios so there's no collision).
    """
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("ALPHA_VANTAGE_API_KEY not set, skipping automated news scan.")
        return
    try:
        symbols = [e.symbol for profile in ACTIVE_PROFILES for e in profile.universe]
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
    scheduler.add_job(scheduled_breadth_update, CronTrigger(hour=8, minute=30, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_news_scan, CronTrigger(hour=8, minute=0, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_refresh_snapshot, IntervalTrigger(minutes=30))
    scheduler.add_job(scheduled_pull_state, IntervalTrigger(minutes=10))
    scheduler.start()
    return scheduler


@app.route("/health")
def health():
    return {"status": "ok"}, 200


def _resolve_profile():
    return get_profile(request.args.get("portfolio", "growth"))


@app.route("/")
def dashboard():
    profile = _resolve_profile()

    if not profile.active:
        return render_template(
            "dashboard.html", profile=profile, active=False,
            message=request.args.get("message"),
        )

    ledger = load_or_init_ledger(profile.ledger_path, profile.initial_capital)
    cash_reserve = get_cash_reserve(ledger)

    # Live on every page load, not just the 30-minute scheduled refresh --
    # this hits Tiger directly so positions/capital reflect right now, not
    # a stale cache. Falls back to the last cached snapshot (and the last
    # persisted ledger capital) if Tiger is unreachable, same resilience
    # pattern as run_daily_update. Deliberately does NOT call
    # mark_to_market_snapshot here -- that would append a new ledger
    # history entry on every page view and spam the equity curve; only the
    # once-daily scheduled job and real trades persist history.
    stale = False
    try:
        client_config = get_client_config()
        trade_client = TradeClient(client_config)
        snapshot = refresh_snapshot(trade_client, profile.universe, profile.ledger_path, path=profile.snapshot_path)
        positions = snapshot["positions"]
        total_invested = snapshot["total_invested"]
        total_capital = cash_reserve + total_invested
    except Exception as e:
        print(f"Live snapshot fetch failed, showing cached data: {type(e).__name__}: {e}")
        stale = True
        try:
            snapshot = load_snapshot(profile.snapshot_path)
            positions = snapshot["positions"]
            total_invested = sum(p["market_value"] for p in positions)
        except FileNotFoundError:
            positions = []
            total_invested = 0.0
        total_capital = latest_capital(ledger)

    decisions = []
    if os.path.exists(profile.decision_log_path):
        with open(profile.decision_log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        decisions = entries[-1]["decisions"] if entries else []

    # Weekly review (and its changelog) stays growth-only for now (see
    # reporting.run_weekly_review's docstring) -- only show it on the
    # growth dashboard, not a stale/irrelevant panel on the dividend one.
    changelog = []
    if profile.name == "growth" and os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            changelog = json.load(f)

    pending = load_pending_approvals(profile.pending_approvals_path)

    max_cap = profile.risk_config.max_capital_at_risk
    utilization_pct = total_invested / max_cap if max_cap else 0.0

    return render_template(
        "dashboard.html",
        profile=profile,
        active=True,
        total_capital=total_capital,
        cash_reserve=cash_reserve,
        total_invested=total_invested,
        utilization_pct=utilization_pct,
        max_capital_at_risk=max_cap,
        positions=positions,
        equity_history=ledger["history"],
        decisions=decisions,
        changelog=list(reversed(changelog))[:5],
        pending_items=pending["items"],
        message=request.args.get("message"),
        stale=stale,
    )


@app.route("/scan", methods=["POST"])
def scan_now():
    profile = _resolve_profile()
    if not profile.active:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message=f"'{profile.name}' portfolio isn't funded yet."))
    try:
        _run_and_persist_scan(profile)
    except Exception as e:
        return redirect(url_for("dashboard", portfolio=profile.name, message=f"Scan failed: {type(e).__name__}: {e}"))
    return redirect(url_for("dashboard", portfolio=profile.name, message="Scan complete."))


@app.route("/review")
def review():
    profile = _resolve_profile()
    decisions = []
    as_of = None
    if os.path.exists(profile.decision_log_path):
        with open(profile.decision_log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if entries:
            as_of = entries[-1]["date"]
            decisions = entries[-1]["decisions"]
    return render_template("review.html", profile=profile, decisions=decisions, as_of=as_of)


@app.route("/approve/<approval_id>", methods=["GET"])
def approve_confirm(approval_id):
    profile = _resolve_profile()
    item = find_pending_approval(profile.pending_approvals_path, approval_id)
    if item is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="That pending approval no longer exists (a newer scan may have superseded it)."))
    return render_template("approve_confirm.html", profile=profile, item=item)


@app.route("/approve/<approval_id>", methods=["POST"])
def approve_execute(approval_id):
    profile = _resolve_profile()

    if get_github_config() is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="Refusing to place a real order: GITHUB_TOKEN/GITHUB_REPO "
                                         "aren't set in this environment, so the ledger update couldn't "
                                         "be synced afterward. This exact gap already caused a real "
                                         "cash_reserve drift once."))

    item = find_pending_approval(profile.pending_approvals_path, approval_id)
    if item is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="That pending approval no longer exists (a newer scan may have superseded it)."))

    client_config = get_client_config()
    trade_client = TradeClient(client_config)

    # Re-validate risk with FRESH state -- positions/drawdown may have
    # moved since the scan that proposed this item.
    raw_positions = trade_client.get_positions() or []
    sleeve_by_symbol = {e.symbol: e.sleeve for e in profile.universe}
    open_positions = [
        RiskPosition(
            symbol=p.contract.symbol,
            strategy=item["strategy_key"] if p.contract.symbol == item["symbol"] else "core_hold",
            notional=abs((p.quantity or 0) * (p.market_price or 0.0)),
            premium_collected=0.0, opened_on=date.today(),
            direction="short" if (p.quantity or 0) < 0 else "long",
        )
        for p in raw_positions if p.contract.symbol in sleeve_by_symbol and p.quantity
    ]
    fresh_state = DailyState(date=date.today(), realized_pnl_today=0.0, open_positions=open_positions)

    ledger = load_or_init_ledger(profile.ledger_path, profile.initial_capital)
    risk_engine = RiskEngine(profile.risk_config)
    direction = "short" if item.get("position_type") == "short" else "long"
    try:
        risk_engine.check_max_drawdown([h["capital"] for h in ledger["history"]])
        risk_engine.validate_trade(fresh_state, item["strategy_key"], item["notional"], direction=direction)
    except RiskViolation as e:
        return redirect(url_for("dashboard", portfolio=profile.name, message=f"Approval blocked by risk engine: {e}"))

    universe_by_symbol = {e.symbol: e for e in profile.universe}
    instr = OrderInstruction(item["symbol"], item["action"], item["quantity"], item["notional"], item["reason"])
    execute_instructions(
        trade_client, client_config, universe_by_symbol, [instr],
        sleeve_by_symbol, item["capital_at_scan"], ledger_path=profile.ledger_path,
    )

    remove_pending_approval(profile.pending_approvals_path, approval_id)
    push_state_to_github(profile.pending_approvals_path)
    return redirect(url_for("dashboard", portfolio=profile.name,
                             message=f"Placed {item['action']} {item['quantity']} {item['symbol']}."))


if os.environ.get("RUN_SCHEDULER", "true") == "true":
    pull_state_from_github()
    start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
