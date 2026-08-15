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
import dataclasses
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, render_template, redirect, url_for, request

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient

from state_paths import REGIME_PATH, NEWS_PATH, CHANGELOG_PATH, SCAN_SETTINGS_PATH, SHORTLIST_PATH
from github_state_sync import pull_state_from_github, push_state_to_github, get_github_config, github_file_url
from strategy_ledger import (
    load_or_init_ledger, latest_capital, get_cash_reserve, reanchor_capital, capital_as_of, gain_baseline_date,
)
from portfolio_snapshot import refresh_snapshot, load_snapshot
from portfolio_profiles import GROWTH_PROFILE, DIVIDEND_PROFILE, ACTIVE_PROFILES, get_profile
from risk_engine import RiskEngine, RiskViolation, DailyState, Position as RiskPosition
from reporting import run_daily_update, run_weekly_review, TARGET_MONTHLY_PCT
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
from macro_regime import update_positioning_tilt, update_breadth_signal, load_regime_signal
from news_scanner import write_news_signal, load_news_signal, SymbolNewsSignal
from alpha_vantage_news_adapter import fetch_news_sentiment, parse_news_sentiment
from finnhub_adapter import fetch_news_for_universe
from news_analysis import build_daily_news_summary
from market_hours import all_market_statuses, format_market_status
from scan_settings import ScanSettings, load_scan_settings, save_scan_settings, validate_scan_settings
from shortlist import load_shortlist, save_shortlist, update_shortlist
from telegram_notifier import get_telegram_config, send_message, format_pending_approvals_alert, format_shortlist_telegram
from universe import SYMBOL_NAMES

app = Flask(__name__)

_SLEEVE_TO_STRATEGY = {"core": "core_hold", "satellite": "satellite_momentum"}
_SHORT_STRATEGY_KEY = "satellite_short"


@app.context_processor
def inject_market_status():
    """
    Available in every template automatically (base.html's footer) --
    purely informational (regular trading hours only, no holiday
    calendar), never consulted by any actual trading logic.
    """
    now_utc = datetime.now(timezone.utc)
    statuses = all_market_statuses(now_utc)
    return {"market_status_lines": [format_market_status(s, now_utc) for s in statuses]}


def _effective_risk_config(profile, settings):
    """settings.capital/max_concurrent_trades only ever REPLACE the static
    risk-config ceiling (max_capital_at_risk is already independent of
    the ledger's live tracked capital -- see risk_engine.py) -- position
    SIZING still uses the real, live ledger capital untouched. A fresh
    copy via dataclasses.replace, never mutates the shared profile
    singleton (GROWTH_PROFILE), which every request reuses."""
    if profile.confidence_scale is None:
        return profile.risk_config
    return dataclasses.replace(
        profile.risk_config,
        max_capital_at_risk=settings.capital,
        max_concurrent_positions=settings.max_concurrent_trades,
    )


def _run_and_persist_scan(profile):
    """Shared by the daily automated job (per active profile) and the /scan route."""
    client_config = get_client_config()
    quote_client = QuoteClient(client_config)
    trade_client = TradeClient(client_config)

    settings = load_scan_settings(SCAN_SETTINGS_PATH) if profile.confidence_scale is not None else ScanSettings()
    scan_profile = dataclasses.replace(profile, risk_config=_effective_risk_config(profile, settings))

    result = run_scan(
        quote_client, trade_client, scan_profile,
        execute_threshold_pct=settings.execute_threshold_pct,
        shortlist_threshold_pct=settings.shortlist_threshold_pct,
    )
    write_decision_log(profile.decision_log_path, result.as_of, result.decisions)
    push_state_to_github(profile.decision_log_path)

    if profile.confidence_scale is not None:
        score_by_symbol = {c.symbol: c.score for c in result.all_candidates}
        price_by_symbol = {c.symbol: c.price for c in result.all_candidates}
        shortlist_entries = update_shortlist(
            existing=load_shortlist(SHORTLIST_PATH),
            confidence_by_symbol=result.confidence_by_symbol,
            score_by_symbol=score_by_symbol, price_by_symbol=price_by_symbol,
            sleeve_by_symbol=result.sleeve_by_symbol,
            execute_threshold_pct=settings.execute_threshold_pct,
            shortlist_threshold_pct=settings.shortlist_threshold_pct,
            as_of=result.as_of,
            held_symbols=set(result.current_positions.keys()),
        )
        save_shortlist(SHORTLIST_PATH, shortlist_entries)
        push_state_to_github(SHORTLIST_PATH)

    items = build_pending_approvals(result, max_capital_at_risk=scan_profile.risk_config.max_capital_at_risk)

    if profile.confidence_scale is not None and settings.autopilot and result.approved_instructions:
        # Autopilot: place every risk-approved instruction immediately,
        # no manual click -- this includes stop-loss exits, not just new
        # entries (see the plan: a defensive sell that already passed
        # every risk_engine check firing automatically is strictly safer
        # than requiring a click to protect capital). Nothing loosens
        # any risk check; this only removes the human click for
        # instructions that already passed every existing gate.
        universe_by_symbol = {e.symbol: e for e in profile.universe}
        execute_instructions(
            trade_client, client_config, universe_by_symbol, result.approved_instructions,
            result.sleeve_by_symbol, result.capital, ledger_path=profile.ledger_path,
            journal_path=profile.journal_path, confidence_by_symbol=result.confidence_by_symbol,
        )
        items = []  # already executed -- nothing left pending from this scan

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


def _send_telegram(text: str) -> bool:
    """Best-effort send -- silently no-ops if Telegram isn't configured,
    same tolerance every other Telegram send in this codebase already has."""
    try:
        telegram_config = get_telegram_config()
        send_message(text, telegram_config.bot_token, telegram_config.chat_id)
        return True
    except FileNotFoundError:
        return False


def scheduled_asia_hours_scan():
    """
    A second daily scan, timed while SG/HK markets are actually open
    (unlike the main scheduled_scan at 17:30 SGT, which runs after both
    have already closed for the day). Scoring itself doesn't care about
    market hours -- momentum scores are built from daily bars that don't
    change until close, so this finds the same candidates either way --
    but ORDER EXECUTION does: an SG/HK approval can only realistically
    fill if it's reviewed and approved while that market is open. Sends
    up to two Telegram messages, each only when there's something to
    say: pending approvals (distinct from the once-daily capital/gains
    update, which never mentions them at all) and, growth only, a
    "Claude Stock Trading Shortlist" digest -- a Telegram-only
    presentation, the dashboard's own shortlist panel is unchanged.
    """
    for profile in ACTIVE_PROFILES:
        try:
            _run_and_persist_scan(profile)
            portfolio_label = profile.name.capitalize() if profile.name != "growth" else ""

            pending = load_pending_approvals(profile.pending_approvals_path)
            if pending["items"]:
                _send_telegram(format_pending_approvals_alert(portfolio_label, pending["items"]))

            if profile.confidence_scale is not None:
                shortlist_entries = load_shortlist(SHORTLIST_PATH)
                if shortlist_entries:
                    _send_telegram(format_shortlist_telegram(shortlist_entries, SYMBOL_NAMES))

            print(f"Asia-hours scan for '{profile.name}' complete: {len(pending['items'])} pending approval(s).")
        except Exception as e:
            print(f"Asia-hours scan failed for '{profile.name}': {type(e).__name__}: {e}")


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


def _run_and_persist_news_scan():
    """
    Shared by the daily scheduled job and the dashboard's "Refresh News"
    button (POST /news/refresh). A structured data fetch plus arithmetic,
    no LLM/agent in this loop, so there's no prompt-injection surface
    even though this path can now also be triggered on-demand. Covers
    every active portfolio's universe (a shared news signal file,
    symbols are disjoint across portfolios so there's no collision).

    Finnhub is the primary source (60 calls/min free tier, one call per
    symbol) -- Alpha Vantage (25 requests/day) is used only as a manual
    fallback when FINNHUB_API_KEY isn't set. Raises if neither key is
    set -- callers decide how to report that (the scheduled job skips
    quietly since it runs whether or not a key exists yet; the button
    surfaces it as a message).
    """
    finnhub_key = os.environ.get("FINNHUB_API_KEY")
    alpha_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not finnhub_key and not alpha_key:
        raise RuntimeError("Neither FINNHUB_API_KEY nor ALPHA_VANTAGE_API_KEY is set")

    symbols = [e.symbol for profile in ACTIVE_PROFILES for e in profile.universe]
    as_of = date.today().isoformat()
    if finnhub_key:
        signals = fetch_news_for_universe(symbols, finnhub_key, as_of)
    else:
        raw = fetch_news_sentiment(symbols, alpha_key)
        signals = parse_news_sentiment(raw, symbols, as_of=as_of)

    write_news_signal(NEWS_PATH, list(signals.values()))
    push_state_to_github(NEWS_PATH)
    return signals


def scheduled_news_scan():
    """
    Daily news-sentiment refresh, Finnhub primary / Alpha Vantage
    fallback (both free tiers). Skips cleanly if neither key is set.
    """
    if not os.environ.get("FINNHUB_API_KEY") and not os.environ.get("ALPHA_VANTAGE_API_KEY"):
        print("Neither FINNHUB_API_KEY nor ALPHA_VANTAGE_API_KEY set, skipping automated news scan.")
        return
    try:
        signals = _run_and_persist_news_scan()
        print(f"News sentiment updated for {len(signals)} symbol(s).")
    except Exception as e:
        print(f"News scan failed: {type(e).__name__}: {e}")


def _load_news_summary(profile):
    """
    Pure read of already-persisted state (news_signal.json, the
    profile's cached position snapshot, regime.json) -- never makes a
    live Tiger or Alpha Vantage call itself, so viewing the dashboard or
    /news never burns Alpha Vantage's 25-request/day quota. Only the
    explicit "Refresh News" button (_run_and_persist_news_scan) touches
    that API.
    """
    news_signals = {}
    if os.path.exists(NEWS_PATH):
        try:
            news_signals = load_news_signal(NEWS_PATH)
        except Exception as e:
            print(f"Failed to load news signal: {type(e).__name__}: {e}")

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
            print(f"Failed to load regime signal: {type(e).__name__}: {e}")

    return build_daily_news_summary(news_signals, held_symbols, date.today().isoformat(), regime=regime)


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_daily_update, CronTrigger(hour=18, minute=0, timezone="Asia/Singapore"))
    scheduler.add_job(scheduled_weekly_review, CronTrigger(day_of_week="sat", hour=9, minute=0, timezone="Asia/Singapore"))
    # day_of_week="mon-fri" on both scan jobs -- markets are closed all
    # weekend, so a Sat/Sun scan would just re-score Friday's closing
    # bars again (daily bars, no new data until a market re-opens),
    # producing identical, pointless results. Both times are already
    # expressed in the same Asia/Singapore timezone the day-of-week is
    # evaluated in, so this doesn't shift any of the existing SG/HK/US
    # session-boundary timing, only removes the weekend firings.
    scheduler.add_job(scheduled_scan, CronTrigger(day_of_week="mon-fri", hour=17, minute=30, timezone="Asia/Singapore"))
    # 10:00 SGT -- after HK's 9:30am open and SG's 9:00am open, comfortably
    # before HK's 12:00pm lunch break -- see scheduled_asia_hours_scan's
    # docstring for why this is a separate job, not just a moved one.
    scheduler.add_job(scheduled_asia_hours_scan, CronTrigger(day_of_week="mon-fri", hour=10, minute=0, timezone="Asia/Singapore"))
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

    # Monthly gain vs the 10% target -- growth only, same scoping as the
    # weekly review above (dividend's target/cadence is different, see
    # run_weekly_review's docstring). Trailing 30-day window (not
    # calendar-month-to-date), matching the weekly view's own trailing-
    # 7-day convention rather than mixing two different window styles.
    monthly_gain_pct = None
    if profile.name == "growth":
        # gain_baseline_date stops at a recent capital reset instead of
        # reaching past it -- otherwise a deliberate "Reset capital"
        # action (real money re-anchored, not trading P&L) reads as a
        # huge fake gain (verified live: a $1,000 -> $5,000 reset showed
        # up as a 400%+ "monthly gain" before this).
        baseline_date = gain_baseline_date(ledger, lookback_days=30)
        month_ago_capital = capital_as_of(ledger, baseline_date)
        monthly_gain_pct = (total_capital - month_ago_capital) / month_ago_capital if month_ago_capital > 0 else 0.0

    pending = load_pending_approvals(profile.pending_approvals_path)
    news_summary = _load_news_summary(profile)

    settings = None
    shortlist_entries = []
    if profile.confidence_scale is not None:
        settings = load_scan_settings(SCAN_SETTINGS_PATH)
        shortlist_entries = load_shortlist(SHORTLIST_PATH)

    max_cap = settings.capital if settings is not None else profile.risk_config.max_capital_at_risk
    utilization_pct = total_invested / max_cap if max_cap else 0.0
    journal_url = github_file_url(os.path.basename(profile.journal_path).replace(".json", ".xlsx"))

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
        news_summary=news_summary,
        message=request.args.get("message"),
        stale=stale,
        settings=settings,
        shortlist_entries=shortlist_entries,
        journal_url=journal_url,
        monthly_gain_pct=monthly_gain_pct,
        target_monthly_pct=TARGET_MONTHLY_PCT,
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


@app.route("/settings", methods=["POST"])
def update_settings():
    """Growth-only (profile.confidence_scale is not None) -- the settings
    panel is hidden on the dividend dashboard, but this route is guarded
    server-side too since it's reachable directly."""
    profile = _resolve_profile()
    if profile.confidence_scale is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="Settings aren't available for this portfolio."))

    settings = ScanSettings(
        autopilot=request.form.get("autopilot") == "on",
        execute_threshold_pct=request.form.get("execute_threshold_pct", type=float) or 0.0,
        shortlist_threshold_pct=request.form.get("shortlist_threshold_pct", type=float) or 0.0,
        max_concurrent_trades=request.form.get("max_concurrent_trades", type=int) or 0,
        capital=request.form.get("capital", type=float) or 0.0,
    )
    try:
        validate_scan_settings(settings)
    except ValueError as e:
        return redirect(url_for("dashboard", portfolio=profile.name, message=f"Settings not saved: {e}"))

    save_scan_settings(SCAN_SETTINGS_PATH, settings)
    push_state_to_github(SCAN_SETTINGS_PATH)
    return redirect(url_for("dashboard", portfolio=profile.name, message="Settings saved."))


@app.route("/settings/reset-capital", methods=["POST"])
def reset_capital():
    """Applies the CURRENTLY SAVED settings.capital value to the real
    ledger -- re-anchors cash_reserve so cash_reserve + live positions
    value == settings.capital, preserving history (see
    strategy_ledger.reanchor_capital). Distinct from saving the setting
    itself, which only changes the risk ceiling used going forward."""
    profile = _resolve_profile()
    if profile.confidence_scale is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="Not available for this portfolio."))

    if get_github_config() is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="Refusing to reset capital: GITHUB_TOKEN/GITHUB_REPO "
                                         "aren't set in this environment, so the ledger update "
                                         "couldn't be synced afterward."))

    settings = load_scan_settings(SCAN_SETTINGS_PATH)
    client_config = get_client_config()
    trade_client = TradeClient(client_config)
    sleeve_by_symbol = {e.symbol: e.sleeve for e in profile.universe}
    raw_positions = trade_client.get_positions() or []
    positions_value_now = sum(
        p.market_value for p in raw_positions if p.contract.symbol in sleeve_by_symbol and p.market_value
    )

    try:
        reanchor_capital(profile.ledger_path, settings.capital, positions_value_now)
    except ValueError as e:
        return redirect(url_for("dashboard", portfolio=profile.name, message=f"Reset failed: {e}"))

    push_state_to_github(profile.ledger_path)
    return redirect(url_for("dashboard", portfolio=profile.name,
                             message=f"Capital reset to ${settings.capital:,.2f}."))


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


@app.route("/news")
def news():
    profile = _resolve_profile()
    summary = _load_news_summary(profile)
    return render_template("news.html", profile=profile, summary=summary,
                            message=request.args.get("message"))


@app.route("/news/refresh", methods=["POST"])
def news_refresh():
    profile = _resolve_profile()
    try:
        signals = _run_and_persist_news_scan()
        message = f"News refreshed: {len(signals)} symbol(s) updated."
    except Exception as e:
        message = f"News refresh failed: {type(e).__name__}: {e}"
    return redirect(url_for("news", portfolio=profile.name, message=message))


def _fetch_current_position(trade_client, sleeve_by_symbol, symbol):
    """Live lookup of one currently-held position (long or short) by
    symbol, or None if there's no open position for it right now."""
    raw_positions = trade_client.get_positions() or []
    for p in raw_positions:
        if p.contract.symbol == symbol and p.contract.symbol in sleeve_by_symbol and p.quantity:
            return p
    return None


def _build_close_instruction(position, requested_quantity):
    """
    position: a raw Tiger position object (has .quantity, .market_price).
    requested_quantity: None/0/negative means "close the whole thing";
    a positive int means "reduce by this many shares," capped at the
    current holding so a manual reduce can never accidentally flip a
    long into a short or vice versa.
    Returns (action, trade_qty, price, notional, is_full_close, current_qty).
    """
    current_qty = int(position.quantity)
    is_short = current_qty < 0
    max_reduce = abs(current_qty)
    trade_qty = max_reduce if not requested_quantity or requested_quantity <= 0 else min(requested_quantity, max_reduce)
    action = "BUY" if is_short else "SELL"
    price = float(position.market_price or 0.0)
    notional = trade_qty * price
    is_full_close = trade_qty >= max_reduce
    return action, trade_qty, price, notional, is_full_close, current_qty


@app.route("/positions/<symbol>/close", methods=["GET"])
def position_close_confirm(symbol):
    profile = _resolve_profile()
    sleeve_by_symbol = {e.symbol: e.sleeve for e in profile.universe}

    client_config = get_client_config()
    trade_client = TradeClient(client_config)
    position = _fetch_current_position(trade_client, sleeve_by_symbol, symbol)
    if position is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message=f"No open position for {symbol} -- it may have already been closed."))

    requested_quantity = request.args.get("quantity", type=int)
    action, trade_qty, price, notional, is_full_close, current_qty = _build_close_instruction(position, requested_quantity)

    item = {
        "symbol": symbol,
        "action": action,
        "quantity": trade_qty,
        "notional": notional,
        "price": price,
        "current_qty": current_qty,
        "is_full_close": is_full_close,
        "sleeve": sleeve_by_symbol.get(symbol, "unknown"),
        "position_type": "cover" if action == "BUY" else "long",
    }
    return render_template("position_close_confirm.html", profile=profile, item=item)


@app.route("/positions/<symbol>/close", methods=["POST"])
def position_close_execute(symbol):
    profile = _resolve_profile()

    if get_github_config() is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="Refusing to place a real order: GITHUB_TOKEN/GITHUB_REPO "
                                         "aren't set in this environment, so the ledger update couldn't "
                                         "be synced afterward. This exact gap already caused a real "
                                         "cash_reserve drift once."))

    sleeve_by_symbol = {e.symbol: e.sleeve for e in profile.universe}
    client_config = get_client_config()
    trade_client = TradeClient(client_config)

    # Re-fetch fresh, not whatever the confirm page happened to show --
    # price/quantity may have moved since then.
    position = _fetch_current_position(trade_client, sleeve_by_symbol, symbol)
    if position is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message=f"No open position for {symbol} -- it may have already been closed."))

    requested_quantity = request.form.get("quantity", type=int)
    action, trade_qty, price, notional, is_full_close, current_qty = _build_close_instruction(position, requested_quantity)
    if trade_qty <= 0:
        return redirect(url_for("dashboard", portfolio=profile.name, message=f"Nothing to close for {symbol}."))

    raw_positions = trade_client.get_positions() or []
    open_positions = [
        RiskPosition(
            symbol=p.contract.symbol,
            strategy=(_SHORT_STRATEGY_KEY if (p.quantity or 0) < 0
                      else _SLEEVE_TO_STRATEGY.get(sleeve_by_symbol.get(p.contract.symbol), "core_hold")),
            notional=abs((p.quantity or 0) * (p.market_price or 0.0)),
            premium_collected=0.0, opened_on=date.today(),
            direction="short" if (p.quantity or 0) < 0 else "long",
        )
        for p in raw_positions if p.contract.symbol in sleeve_by_symbol and p.quantity
    ]
    fresh_state = DailyState(date=date.today(), realized_pnl_today=0.0, open_positions=open_positions)

    sleeve = sleeve_by_symbol.get(symbol, "unknown")
    strategy_key = _SHORT_STRATEGY_KEY if current_qty < 0 else _SLEEVE_TO_STRATEGY.get(sleeve, "core_hold")

    ledger = load_or_init_ledger(profile.ledger_path, profile.initial_capital)
    risk_engine = RiskEngine(profile.risk_config)
    try:
        risk_engine.check_max_drawdown([h["capital"] for h in ledger["history"]])
        # direction="long" always -- closing/reducing a long is an ordinary
        # sell, and covering a short REDUCES exposure; neither should be
        # gated by the short-exposure cap, which only guards opening/adding
        # to a short. Matches the convention scan_workflow.py already
        # established for the automated pipeline.
        risk_engine.validate_trade(fresh_state, strategy_key, notional, direction="long")
    except RiskViolation as e:
        return redirect(url_for("dashboard", portfolio=profile.name, message=f"Close/reduce blocked by risk engine: {e}"))

    universe_by_symbol = {e.symbol: e for e in profile.universe}
    reason = "manual full close" if is_full_close else f"manual reduce by {trade_qty} share(s)"
    instr = OrderInstruction(symbol, action, trade_qty, notional, reason)
    execute_instructions(
        trade_client, client_config, universe_by_symbol, [instr],
        sleeve_by_symbol, latest_capital(ledger), ledger_path=profile.ledger_path,
        journal_path=profile.journal_path,  # no confidence_pct -- this is an ad-hoc manual action, not a scored candidate
    )

    verb = "Closed" if is_full_close else "Reduced"
    return redirect(url_for("dashboard", portfolio=profile.name,
                             message=f"{verb} {symbol}: {action} {trade_qty} share(s)."))


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
    confidence_by_symbol = (
        {item["symbol"]: item["confidence_pct"]} if item.get("confidence_pct") is not None else None
    )
    execute_instructions(
        trade_client, client_config, universe_by_symbol, [instr],
        sleeve_by_symbol, item["capital_at_scan"], ledger_path=profile.ledger_path,
        journal_path=profile.journal_path, confidence_by_symbol=confidence_by_symbol,
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
