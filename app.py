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
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, render_template, redirect, url_for, request

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import Market

from state_paths import (
    REGIME_PATH, NEWS_PATH, SECTOR_ROTATION_PATH, INVESTMENT_CLOCK_PATH, SECTOR_TAGS_PATH, MOVERS_PATH,
    DIVIDENDS_EARNED_PATH,
)
from github_state_sync import pull_state_from_github, push_state_to_github, get_github_config, github_file_url
from strategy_ledger import (
    load_or_init_ledger, latest_capital, get_cash_reserve, reanchor_capital, capital_as_of, gain_baseline_date,
    most_recent_reset_date,
)
from portfolio_snapshot import refresh_snapshot, load_snapshot
from portfolio_profiles import (
    GROWTH_PROFILE, DIVIDEND_PROFILE, ACTIVE_PROFILES, ALL_PROFILES, get_profile,
    effective_universe, validate_new_universe_entry,
)
from risk_engine import RiskEngine, RiskViolation, DailyState, Position as RiskPosition
from reporting import run_daily_update, run_weekly_review, TARGET_MONTHLY_PCT, TARGET_ANNUAL_PCT, target_monthly_equivalent_pct
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
from market_hours import all_market_statuses, format_market_status, is_any_market_open
from scan_settings import ScanSettings, load_scan_settings, save_scan_settings, validate_scan_settings
from shortlist import load_shortlist, save_shortlist, update_shortlist
from telegram_notifier import get_telegram_config, send_message, format_pending_approvals_alert, format_shortlist_telegram
from universe import SYMBOL_NAMES
from universe_extra import ExtraUniverseEntry, load_extra_universe, add_entry, remove_entry
from self_improvement import load_self_improvement_state, resumes_on
from trade_journal import load_journal
from sector_rotation import refresh_sector_rotation, load_sector_rotation, save_sector_rotation, get_sector_tilt, distinct_industries
from investment_clock import (
    refresh_investment_clock, load_investment_clock, save_investment_clock, hk_sg_unavailable_signal,
)
from sector_suggestions import fetch_suggestions_for_sector, build_suggestions, load_suggestions, save_suggestions
from tiger_industry_adapter import load_sector_tags, fetch_industry_stocks, parse_industry_stocks
from movers import refresh_movers, load_movers, save_movers
from dividend_tracker import refresh_dividends_earned, load_dividends_earned, save_dividends_earned

app = Flask(__name__)

_SLEEVE_TO_STRATEGY = {"core": "core_hold", "satellite": "satellite_momentum"}
_SHORT_STRATEGY_KEY = "satellite_short"

# Shown in the dashboard's collapsed "Developer Notes" panel -- the 5 MOST
# RECENT entries only (single-liner each), most-recent-first. The full
# history lives in DEVELOPMENT_LOG.md (linked below this list on the
# dashboard) -- add one line here per notable change when it ships, and a
# fuller Problem/Solution entry there.
DEVELOPER_NOTES = [
    ("2026-08-21", "Fixed overbuying past the capital cap (risk checks used a stale committed-capital snapshot within one scan) and reverted to 3 scans/day at each market's own open, dropping the 2-hourly interval scan."),
    ("2026-08-20", "Added real dividend tracking (Tiger's own dividend schedule x shares actually held) and a weekly gain progress chart above Scan Now on both dashboards."),
    ("2026-08-19", "Added Tiger's own real-time movers ranking and growth-only auto-add to universe -- up to 3 sector/mover-matched symbols per run, no click, capped so the universe can't grow unbounded."),
    ("2026-08-18", "Fixed universe-add silently not persisting (GitHub sync failures were never surfaced) and added a 2-hourly scan with an explicit per-run log line to confirm it's firing."),
    ("2026-08-17", "Fixed autopilot/approve submitting orders outside a symbol's own market hours -- a US candidate found during HK/SG hours used to abort the entire scan when Tiger rejected it, losing every other candidate too."),
    ("2026-08-16", "Added sector rotation ranking (US via SPDR ETFs, HK via GICS aggregation), a real FRED-driven US Investment Clock, and sector-sourced trade suggestions with a human-approved add-to-universe flow."),
    ("2026-08-15", "Fixed the daily Telegram update firing on weekends -- it now checks whether any relevant market actually trades today, not just a fixed clock time."),
][:5]

DEVELOPMENT_LOG_PATH = "DEVELOPMENT_LOG.md"


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

    settings = (
        load_scan_settings(profile.scan_settings_path, default_capital=profile.initial_capital)
        if profile.confidence_scale is not None else ScanSettings()
    )
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
            existing=load_shortlist(profile.shortlist_path),
            confidence_by_symbol=result.confidence_by_symbol,
            score_by_symbol=score_by_symbol, price_by_symbol=price_by_symbol,
            sleeve_by_symbol=result.sleeve_by_symbol,
            execute_threshold_pct=settings.execute_threshold_pct,
            shortlist_threshold_pct=settings.shortlist_threshold_pct,
            as_of=result.as_of,
            held_symbols=set(result.current_positions.keys()),
        )
        save_shortlist(profile.shortlist_path, shortlist_entries)
        push_state_to_github(profile.shortlist_path)

    items = build_pending_approvals(result, max_capital_at_risk=scan_profile.risk_config.max_capital_at_risk)

    if profile.confidence_scale is not None and settings.autopilot and result.approved_instructions:
        # Autopilot: place every risk-approved instruction immediately,
        # no manual click -- this includes stop-loss exits, not just new
        # entries (see the plan: a defensive sell that already passed
        # every risk_engine check firing automatically is strictly safer
        # than requiring a click to protect capital). Nothing loosens
        # any risk check; this only removes the human click for
        # instructions that already passed every existing gate.
        #
        # is_any_market_open (the /scan pre-check above) only guarantees
        # SOME market the profile trades is open -- e.g. it correctly lets
        # a scan run during HK/SG hours even though the US is asleep. But
        # a US-market instruction found during that same scan would still
        # get submitted to Tiger, which rejects a market order placed
        # outside THAT symbol's own regular hours. That used to blow up
        # the whole autopilot batch (confirmed live: one HK-hours scan
        # aborted with "Market order is only available during regular
        # trading hours (09:30-16:00 ET)", losing the pending-approval
        # record for every candidate in the run, not just the US one).
        # Filter per-instruction instead: only execute what's tradeable
        # RIGHT NOW; anything else stays a pending approval rather than
        # being submitted and rejected, or silently dropped -- a later
        # scan (scheduled or manual) picks it up again once its own
        # market is open, same as any other unapproved item.
        universe_by_symbol = {e.symbol: e for e in effective_universe(profile)}
        now_utc = datetime.now(timezone.utc)
        executable_now = [
            instr for instr in result.approved_instructions
            if is_any_market_open({universe_by_symbol[instr.symbol].market}, now_utc)
        ]
        if executable_now:
            execute_instructions(
                trade_client, client_config, universe_by_symbol, executable_now,
                result.sleeve_by_symbol, result.capital, ledger_path=profile.ledger_path,
                journal_path=profile.journal_path, confidence_by_symbol=result.confidence_by_symbol,
            )
        executed_symbols = {instr.symbol for instr in executable_now}
        items = [item for item in items if item.symbol not in executed_symbols]

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
            refresh_snapshot(trade_client, effective_universe(profile), profile.ledger_path, path=profile.snapshot_path)
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
    for profile in ACTIVE_PROFILES:
        try:
            run_weekly_review(profile)
        except Exception as e:
            print(f"Weekly review failed for '{profile.name}': {type(e).__name__}: {e}")


def scheduled_us_open_scan():
    """One of the three daily automated scans, this one timed right at
    US market open (see start_scheduler's America/New_York-timezone
    trigger, which handles DST automatically) -- scoring and decision-
    logging only, never places an order -- see run_scan()'s and this
    module's docstrings. Reverted from a 2-hourly interval scan (too
    much churn -- every re-rank was a chance to force-sell a position
    that hadn't hit stop-loss/momentum-reversal, just because a
    different candidate scored higher that cycle) back to exactly
    three scans a day, one at each market's own open (see also
    scheduled_asia_hours_scan, registered twice for SG and HK)."""
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


# (profile_name, message_type) -> last text sent this process's lifetime.
# In-memory only (not persisted/synced) -- gunicorn is pinned to a single
# worker (see this file's module docstring), so one process really does
# see both of a day's Asia-hours scans, and a rare redeploy landing
# between them just costs one duplicate message rather than a wrong one.
_last_sent_telegram = {}


def _send_telegram_if_changed(key: tuple, text: str) -> bool:
    """Skips a resend when the exact same text already went out for this
    key. Exists because scheduled_asia_hours_scan runs twice a day (SG
    open, then HK open 30 minutes later) and momentum scores are built
    from daily bars that don't move until close -- so absent any real
    change, both runs compute the identical shortlist and find the same
    still-unactioned pending approvals, and were sending the same two
    Telegram messages twice."""
    if _last_sent_telegram.get(key) == text:
        return False
    sent = _send_telegram(text)
    if sent:
        _last_sent_telegram[key] = text
    return sent


def scheduled_asia_hours_scan():
    """
    Two of the three daily automated scans -- this same function is
    registered TWICE in start_scheduler (once right at SG's own open,
    once right at HK's own open), rather than the single 10:00 SGT
    compromise time this used to run at. Scoring itself doesn't care
    about market hours -- momentum scores are built from daily bars
    that don't change until close, so this finds the same candidates
    either way -- but ORDER EXECUTION does: an SG/HK approval can only
    realistically fill if it's reviewed and approved while that market
    is open. Sends up to two Telegram messages, each only when there's
    something to say AND it differs from what was already sent this
    process's lifetime (see _send_telegram_if_changed) -- since scoring
    is unchanged between the two runs whenever nothing real has moved,
    without this the SG-open and HK-open runs would send the identical
    pending-approvals alert and shortlist digest twice, 30 minutes
    apart. Pending approvals is distinct from the once-daily
    capital/gains update, which never mentions them at all; the
    shortlist digest is "Claude Stock Trading Shortlist" -- a
    Telegram-only presentation, the dashboard's own shortlist panel is
    unchanged.
    """
    for profile in ACTIVE_PROFILES:
        try:
            _run_and_persist_scan(profile)
            portfolio_label = profile.name.capitalize() if profile.name != "growth" else ""

            pending = load_pending_approvals(profile.pending_approvals_path)
            if pending["items"]:
                _send_telegram_if_changed(
                    (profile.name, "pending_approvals"),
                    format_pending_approvals_alert(portfolio_label, pending["items"]),
                )

            if profile.confidence_scale is not None:
                shortlist_entries = load_shortlist(profile.shortlist_path)
                if shortlist_entries:
                    _send_telegram_if_changed(
                        (profile.name, "shortlist"),
                        format_shortlist_telegram(shortlist_entries, SYMBOL_NAMES),
                    )

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


MAX_AUTO_ADDS_PER_RUN = 3   # growth only -- caps how many NEW symbols one run can add with no human click
MAX_EXTRA_UNIVERSE_SIZE = 15  # growth only -- auto-add stops entirely once the extra universe reaches this size


def _mover_based_suggestions(quote_client, gics_id, name, market_enum, movers_signal, excluded):
    """Sibling of sector_suggestions.fetch_suggestions_for_sector, but
    intersects the top sector/industry's membership against TODAY'S REAL
    Tiger movers ranking (see movers.py) instead of a generic liquidity-
    floor screener -- "hot sector AND actually moving today," a
    genuinely more specific signal than "hot sector AND merely liquid."
    Reuses build_suggestions as-is (it doesn't care where the "liquid"
    list came from); only the reason text is rewritten afterward so the
    suggestion is honest about which signal produced it."""
    if not movers_signal or not movers_signal.entries:
        return []
    member_raw = fetch_industry_stocks(quote_client, gics_id, market_enum)
    members = parse_industry_stocks(member_raw)
    mover_symbols = [m.symbol for m in movers_signal.entries]
    market_str = market_enum.value if hasattr(market_enum, "value") else str(market_enum)
    suggestions = build_suggestions(gics_id, name, market_str, members, mover_symbols, excluded)
    return [
        dataclasses.replace(
            s, reason=f"{name} is one of today's most actively-traded groups on Tiger's own ranking; "
                      f"{s.symbol} is in it and you don't currently track."
        )
        for s in suggestions
    ]


def _dedupe_by_symbol(suggestions):
    seen = set()
    deduped = []
    for s in suggestions:
        if s.symbol in seen:
            continue
        seen.add(s.symbol)
        deduped.append(s)
    return deduped


def _auto_add_candidates(profile, suggestions):
    """Growth-only: automatically adds up to MAX_AUTO_ADDS_PER_RUN
    sector/mover-matched suggestions to the universe with no human
    click -- goes through the SAME validate_new_universe_entry
    disjointness check a manual /universe/add would, this only skips
    the click, not the safety guarantee. Bounded two ways so the
    universe can't grow unbounded run after run: at most
    MAX_AUTO_ADDS_PER_RUN new symbols per run, and auto-adding stops
    entirely once the extra universe already has MAX_EXTRA_UNIVERSE_SIZE
    entries (a human can still add more manually past that ceiling).
    Returns (added, remaining) -- remaining is whatever didn't get
    auto-added (past the cap, or failed validation), still saved as a
    manual-override suggestion same as before this existed."""
    if len(load_extra_universe(profile.extra_universe_path)) >= MAX_EXTRA_UNIVERSE_SIZE:
        return [], suggestions

    added, remaining = [], []
    for s in suggestions:
        if len(added) >= MAX_AUTO_ADDS_PER_RUN:
            remaining.append(s)
            continue
        try:
            validate_new_universe_entry(s.symbol, profile)
        except ValueError:
            remaining.append(s)
            continue
        currency, exchange = _MARKET_TO_CURRENCY_EXCHANGE[s.market]
        sleeve = "core" if profile.name == "dividend" else "satellite"
        add_entry(profile.extra_universe_path, ExtraUniverseEntry(
            symbol=s.symbol, market=s.market, currency=currency, exchange=exchange, sleeve=sleeve,
            added_at=date.today().isoformat(), source_sector=s.sector_name, auto_added=True,
        ))
        added.append(s)

    if added:
        push_state_to_github(profile.extra_universe_path)
    return added, remaining


def scheduled_sector_rotation_update():
    """Daily sector-rotation ranking + US Investment Clock + movers
    refresh, all shared across profiles (market-wide facts, not
    portfolio-specific -- see sector_rotation.py, investment_clock.py,
    movers.py) -- then, per active profile, screener-sourced "sector
    opportunities" suggestions off the freshly-ranked top sector (see
    sector_suggestions.py), PLUS mover-matched suggestions for growth
    specifically (see _mover_based_suggestions). For growth only, up to
    MAX_AUTO_ADDS_PER_RUN of those suggestions are added to the universe
    automatically, no human click (see _auto_add_candidates) -- dividend
    keeps the existing manual-approval-only flow. Each stage is
    independent -- one failing (e.g. FRED unreachable) never blocks the
    others, same tolerance as every other scheduled job here."""
    try:
        client_config = get_client_config()
        quote_client = QuoteClient(client_config)
    except Exception as e:
        print(f"Sector rotation update skipped -- Tiger client unavailable: {type(e).__name__}: {e}")
        return

    rotation_signals = {}
    try:
        us_symbols = sorted({e.symbol for p in ALL_PROFILES for e in effective_universe(p) if e.market == "US"})
        hk_symbols = sorted({e.symbol for p in ALL_PROFILES for e in effective_universe(p) if e.market == "HK"})
        rotation_signals = refresh_sector_rotation(quote_client, us_symbols, hk_symbols, SECTOR_TAGS_PATH)
        save_sector_rotation(SECTOR_ROTATION_PATH, rotation_signals)
        push_state_to_github(SECTOR_ROTATION_PATH)
        push_state_to_github(SECTOR_TAGS_PATH)
        us_top = rotation_signals["US"].entries[0].sector_name if rotation_signals["US"].entries else "n/a"
        print(f"Sector rotation updated: US top sector = {us_top}")
    except Exception as e:
        print(f"Sector rotation ranking failed: {type(e).__name__}: {e}")

    try:
        clock_signal = refresh_investment_clock()
        save_investment_clock(INVESTMENT_CLOCK_PATH, clock_signal)
        push_state_to_github(INVESTMENT_CLOCK_PATH)
        print(f"Investment Clock updated: {clock_signal.quadrant}")
    except Exception as e:
        print(f"Investment Clock update failed: {type(e).__name__}: {e}")

    movers_signals = {}
    try:
        movers_signals = refresh_movers(quote_client)
        save_movers(MOVERS_PATH, movers_signals)
        push_state_to_github(MOVERS_PATH)
        us_top_mover = movers_signals["US"].entries[0].symbol if movers_signals["US"].entries else "n/a"
        print(f"Movers updated: US top = {us_top_mover}")
    except Exception as e:
        print(f"Movers update failed: {type(e).__name__}: {e}")

    for profile in ACTIVE_PROFILES:
        try:
            excluded = {e.symbol for e in effective_universe(profile)}
            suggestions = []
            for region, market_enum in (("US", Market.US), ("HK", Market.HK)):
                region_signal = rotation_signals.get(region)
                if not region_signal:
                    continue
                # Prefer the finer top-ranked industry group (e.g. "Semiconductors
                # & Semiconductor Equipment") when available -- more targeted than
                # the whole top-ranked sector; fall back to the sector level if the
                # industry breakdown hasn't populated yet (e.g. before the first
                # tagging pass has enough coverage).
                if region_signal.industries:
                    top_industry = region_signal.industries[0]
                    gics_id, name = top_industry.gics_group_id, top_industry.industry_name
                elif region_signal.entries:
                    top_sector = region_signal.entries[0]
                    gics_id, name = top_sector.gics_sector_id, top_sector.sector_name
                else:
                    continue
                suggestions += fetch_suggestions_for_sector(quote_client, gics_id, name, market_enum, excluded)
                if profile.name == "growth":
                    suggestions += _mover_based_suggestions(
                        quote_client, gics_id, name, market_enum, movers_signals.get(region), excluded,
                    )
            suggestions = _dedupe_by_symbol(suggestions)

            if profile.name == "growth":
                added, suggestions = _auto_add_candidates(profile, suggestions)
                if added:
                    print(f"Auto-added {len(added)} symbol(s) to 'growth' universe: "
                          f"{', '.join(s.symbol for s in added)}.")

            save_suggestions(profile.sector_suggestions_path, suggestions)
            push_state_to_github(profile.sector_suggestions_path)
            print(f"Sector opportunities updated for '{profile.name}': {len(suggestions)} suggestion(s).")
        except Exception as e:
            print(f"Sector opportunities update failed for '{profile.name}': {type(e).__name__}: {e}")


def scheduled_dividends_update():
    """Daily, dividend-portfolio-only: refreshes how much has actually
    been earned in dividends this calendar year (see dividend_tracker.py
    for the real Tiger-data-vs-journal cross-reference and its stated
    approximation). Independent of every other job here -- a failure
    only affects this one panel, never blocks scans/sector rotation/
    anything else."""
    if not DIVIDEND_PROFILE.active:
        return
    try:
        client_config = get_client_config()
        quote_client = QuoteClient(client_config)
    except Exception as e:
        print(f"Dividends update skipped -- Tiger client unavailable: {type(e).__name__}: {e}")
        return

    try:
        journal_entries = load_journal(DIVIDEND_PROFILE.journal_path)
        market_by_symbol = {e.symbol: e.market for e in effective_universe(DIVIDEND_PROFILE)}
        summary = refresh_dividends_earned(quote_client, journal_entries, market_by_symbol)
        save_dividends_earned(DIVIDENDS_EARNED_PATH, summary)
        push_state_to_github(DIVIDENDS_EARNED_PATH)
        totals = ", ".join(f"{amt:,.2f} {ccy}" for ccy, amt in summary.total_by_currency.items()) or "0"
        print(f"Dividends updated: {totals} earned in {summary.year} ({len(summary.payments)} payment(s)).")
    except Exception as e:
        print(f"Dividends update failed: {type(e).__name__}: {e}")


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

    symbols = [e.symbol for profile in ACTIVE_PROFILES for e in effective_universe(profile)]
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
    # day_of_week="mon-fri" -- no market this app trades is ever open on a
    # Sat/Sun, so a weekend run would mark-to-market against a stale
    # already-reported close, append a redundant no-information ledger
    # snapshot, and text a "Gains for the day: $0.00" that's misleading
    # (there was no trading day) rather than merely uninteresting. Same
    # reasoning as the scan jobs' own weekday-only guard below.
    scheduler.add_job(scheduled_daily_update, CronTrigger(day_of_week="mon-fri", hour=18, minute=0, timezone="Asia/Singapore"))
    # Saturday, deliberately NOT weekday-restricted -- this reports on the
    # week that just closed (Mon-Fri), the same "review right after the
    # week ends" timing the sibling Forex Agent project's own Friday
    # reflection uses, so it's expected to fire while the market is shut.
    scheduler.add_job(scheduled_weekly_review, CronTrigger(day_of_week="sat", hour=9, minute=0, timezone="Asia/Singapore"))
    # Exactly three scans a day, each timed right at one market's own
    # open (plus a 5-minute buffer for quotes to stabilize) -- reverted
    # from a 2-hourly interval scan, which caused far more churn than
    # intended: every re-rank was a fresh chance to force-sell a
    # position that hadn't actually hit stop-loss/momentum-reversal,
    # just because a different candidate scored higher that cycle.
    # day_of_week="mon-fri" on all three -- markets are closed all
    # weekend, so a Sat/Sun scan would just re-score Friday's closing
    # bars again (daily bars, no new data until a market re-opens),
    # producing identical, pointless results.
    #
    # SG opens 9:00 SGT.
    scheduler.add_job(scheduled_asia_hours_scan, CronTrigger(day_of_week="mon-fri", hour=9, minute=5, timezone="Asia/Singapore"))
    # HK opens 9:30 SGT -- same function as SG's, registered a second
    # time; see scheduled_asia_hours_scan's own docstring for why.
    scheduler.add_job(scheduled_asia_hours_scan, CronTrigger(day_of_week="mon-fri", hour=9, minute=35, timezone="Asia/Singapore"))
    # US opens 9:30am ET -- expressed in America/New_York (not a fixed
    # SGT offset) so DST is handled automatically, same convention
    # scheduled_cot_update below already uses.
    scheduler.add_job(scheduled_us_open_scan, CronTrigger(day_of_week="mon-fri", hour=9, minute=35, timezone="America/New_York"))
    scheduler.add_job(scheduled_cot_update, CronTrigger(day_of_week="fri", hour=16, minute=30, timezone="America/New_York"))
    # Before the SG/HK scans (9:05/9:35 SGT) and before breadth/news, so
    # the sector tilt/dashboard panels are fresh for the whole trading
    # day here -- weekday-only, same reasoning as the scan jobs above
    # (US/HK markets/FRED data don't move on a weekend either).
    scheduler.add_job(scheduled_sector_rotation_update, CronTrigger(day_of_week="mon-fri", hour=7, minute=0, timezone="Asia/Singapore"))
    # 7:30 SGT -- right after sector rotation's own 7:00 slot, avoiding
    # overlap. Daily is plenty -- dividend schedules don't change intraday.
    scheduler.add_job(scheduled_dividends_update, CronTrigger(day_of_week="mon-fri", hour=7, minute=30, timezone="Asia/Singapore"))
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


def _sector_rotation_for_display(path):
    """Same as load_sector_rotation, but each region's industries are
    filtered to the ones that actually differ from their parent sector
    (see sector_rotation.distinct_industries) -- display only. Doesn't
    touch the persisted file, and NOT used by
    scheduled_sector_rotation_update's suggestion-sourcing, which reads
    the full unfiltered ranking directly -- the single most specific
    classification is still the right thing to suggest from even when
    it happens to equal its sector's number."""
    signals = load_sector_rotation(path)
    return {
        region: dataclasses.replace(signal, industries=distinct_industries(signal.industries))
        for region, signal in signals.items()
    }


def _weekly_gain_chart_data(ledger):
    """Reset-aware day-by-day % gain for the CURRENT week (Monday
    through today, capped at Friday) -- same reset-skip logic as
    gain_baseline_date, so a capital reset mid-week doesn't show up as
    a fake huge jump: if a reset happened after this week's Monday, the
    chart starts from the reset date instead of Monday. Returns
    {"labels": [...], "values": [...]} (values as fractions, e.g. 0.02
    for +2%), ready for the dashboard's Chart.js line chart. Weekends
    are never included -- if the effective start date itself falls on
    one (a reset over the weekend), it rolls forward to the next
    Monday."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    reset_date = most_recent_reset_date(ledger)
    start = date.fromisoformat(reset_date) if reset_date and reset_date > monday.isoformat() else monday
    while start.weekday() >= 5:
        start += timedelta(days=1)

    baseline_capital = capital_as_of(ledger, start.isoformat())
    labels, values = [], []
    day = start
    while day.weekday() < 5 and day <= today:
        day_capital = capital_as_of(ledger, day.isoformat())
        gain_pct = (day_capital - baseline_capital) / baseline_capital if baseline_capital else 0.0
        labels.append(day.strftime("%a"))
        values.append(round(gain_pct, 4))
        day += timedelta(days=1)
    return {"labels": labels, "values": values}


def _investment_clock_by_region():
    """US comes from the last daily refresh (None if that hasn't run
    yet); HK/SG always get the explicit "unavailable" signal (see
    investment_clock.py's docstring) so the dashboard states the gap
    plainly rather than silently omitting those regions."""
    return {
        "US": load_investment_clock(INVESTMENT_CLOCK_PATH),
        "HK": hk_sg_unavailable_signal("HK"),
        "SG": hk_sg_unavailable_signal("SG"),
    }


def _build_overview_entry(profile):
    """One profile's snapshot for the combined home overview -- same live-
    fetch-with-cached-fallback resilience as the per-profile dashboard
    route, just condensed to what fits a one-line-per-position summary."""
    if not profile.active:
        return {"profile": profile, "active": False}

    ledger = load_or_init_ledger(profile.ledger_path, profile.initial_capital)
    cash_reserve = get_cash_reserve(ledger)

    stale = False
    try:
        client_config = get_client_config()
        trade_client = TradeClient(client_config)
        snapshot = refresh_snapshot(trade_client, effective_universe(profile), profile.ledger_path, path=profile.snapshot_path)
        positions = snapshot["positions"]
        total_invested = snapshot["total_invested"]
        total_capital = cash_reserve + total_invested
    except Exception as e:
        print(f"Overview snapshot fetch failed for '{profile.name}', showing cached data: {type(e).__name__}: {e}")
        stale = True
        try:
            snapshot = load_snapshot(profile.snapshot_path)
            positions = snapshot["positions"]
            total_invested = sum(p["market_value"] for p in positions)
        except FileNotFoundError:
            positions = []
            total_invested = 0.0
        total_capital = latest_capital(ledger)

    baseline_date = gain_baseline_date(ledger, lookback_days=30)
    month_ago_capital = capital_as_of(ledger, baseline_date)
    gain_pct = (total_capital - month_ago_capital) / month_ago_capital if month_ago_capital > 0 else 0.0

    pending = load_pending_approvals(profile.pending_approvals_path)
    paused_state = load_self_improvement_state(profile.paused_symbols_path)

    return {
        "profile": profile,
        "active": True,
        "stale": stale,
        "total_capital": total_capital,
        "cash_reserve": cash_reserve,
        "total_invested": total_invested,
        "gain_pct": gain_pct,
        "target_pct": TARGET_MONTHLY_PCT if profile.name == "growth" else TARGET_ANNUAL_PCT,
        "target_period_label": "month" if profile.name == "growth" else "year",
        "positions": positions,
        "pending_count": len(pending["items"]),
        "paused_count": len(paused_state.paused_symbols),
    }


@app.route("/")
def dashboard():
    # No ?portfolio= at all -- the combined home overview (both profiles,
    # one line per position) is the default landing page; growth is no
    # longer implicitly favored. Any explicit ?portfolio=growth|dividend
    # link (the switcher, Telegram links, bookmarks) still lands on that
    # profile's own full dashboard exactly as before.
    if request.args.get("portfolio") is None:
        overview = [_build_overview_entry(p) for p in ALL_PROFILES]
        return render_template(
            "home.html", overview=overview, message=request.args.get("message"),
            sector_rotation=_sector_rotation_for_display(SECTOR_ROTATION_PATH),
            investment_clock=_investment_clock_by_region(),
        )

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
        snapshot = refresh_snapshot(trade_client, effective_universe(profile), profile.ledger_path, path=profile.snapshot_path)
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

    # Distinct from `decisions` above (every scored candidate this scan,
    # including shortlisted/rejected ones -- see the "Most recent
    # decisions" panel) -- this is real fills only, straight from
    # trade_journal.json, which order_execution.py only ever writes to
    # AFTER an order actually placed against Tiger. Most recent first.
    recent_trades = sorted(
        load_journal(profile.journal_path), key=lambda e: e.opened_at, reverse=True
    )[:10]

    changelog = []
    if os.path.exists(profile.changelog_path):
        with open(profile.changelog_path, "r", encoding="utf-8") as f:
            changelog = json.load(f)

    # Monthly gain, trailing 30-day window (not calendar-month-to-date),
    # matching the weekly view's own trailing-7-day convention rather
    # than mixing two different window styles. Growth's target is 10%
    # per MONTH; dividend's is the much lower-turnover 10% per YEAR (see
    # reporting.TARGET_ANNUAL_PCT) -- both shown against the same
    # trailing-30-day realized gain, just against each profile's own
    # natural target period.
    # gain_baseline_date stops at a recent capital reset instead of
    # reaching past it -- otherwise a deliberate "Reset capital" action
    # (real money re-anchored, not trading P&L) reads as a huge fake
    # gain (verified live: a $1,000 -> $5,000 reset showed up as a
    # 400%+ "monthly gain" before this).
    baseline_date = gain_baseline_date(ledger, lookback_days=30)
    month_ago_capital = capital_as_of(ledger, baseline_date)
    monthly_gain_pct = (total_capital - month_ago_capital) / month_ago_capital if month_ago_capital > 0 else 0.0
    target_pct = TARGET_MONTHLY_PCT if profile.name == "growth" else TARGET_ANNUAL_PCT
    target_period_label = "month" if profile.name == "growth" else "year"

    pending = load_pending_approvals(profile.pending_approvals_path)
    news_summary = _load_news_summary(profile)

    settings = None
    shortlist_entries = []
    if profile.confidence_scale is not None:
        settings = load_scan_settings(profile.scan_settings_path, default_capital=profile.initial_capital)
        shortlist_entries = load_shortlist(profile.shortlist_path)

    max_cap = settings.capital if settings is not None else profile.risk_config.max_capital_at_risk
    utilization_pct = total_invested / max_cap if max_cap else 0.0
    journal_url = github_file_url(os.path.basename(profile.journal_path).replace(".json", ".xlsx"))

    # Self-improvement pauses (see self_improvement.py) -- both profiles,
    # not gated by confidence_scale, since a losing streak can happen to
    # either portfolio's own symbols.
    paused_state = load_self_improvement_state(profile.paused_symbols_path)
    paused_symbols = [
        {"symbol": symbol, "resumes_on": resumes_on(paused_iso)}
        for symbol, paused_iso in sorted(paused_state.paused_symbols.items())
    ]

    sector_rotation = _sector_rotation_for_display(SECTOR_ROTATION_PATH)
    investment_clock = _investment_clock_by_region()
    sector_suggestions = load_suggestions(profile.sector_suggestions_path)
    extra_universe = load_extra_universe(profile.extra_universe_path)
    # Growth-only, matching _mover_based_suggestions/_auto_add_candidates'
    # own scope in scheduled_sector_rotation_update -- movers feed
    # growth's suggestions specifically, so only growth's dashboard shows
    # the raw list.
    movers = load_movers(MOVERS_PATH) if profile.name == "growth" else {}
    # Dividend-only -- see dividend_tracker.py/scheduled_dividends_update.
    dividends_earned = load_dividends_earned(DIVIDENDS_EARNED_PATH) if profile.name == "dividend" else None
    weekly_gain_chart = _weekly_gain_chart_data(ledger)

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
        recent_trades=recent_trades,
        changelog=list(reversed(changelog))[:5],
        pending_items=pending["items"],
        news_summary=news_summary,
        message=request.args.get("message"),
        stale=stale,
        settings=settings,
        shortlist_entries=shortlist_entries,
        journal_url=journal_url,
        monthly_gain_pct=monthly_gain_pct,
        target_pct=target_pct,
        target_period_label=target_period_label,
        paused_symbols=paused_symbols,
        sector_rotation=sector_rotation,
        investment_clock=investment_clock,
        sector_suggestions=sector_suggestions,
        extra_universe=extra_universe,
        movers=movers,
        dividends_earned=dividends_earned,
        weekly_gain_chart=weekly_gain_chart,
        developer_notes=DEVELOPER_NOTES,
        development_log_url=github_file_url(DEVELOPMENT_LOG_PATH),
    )


@app.route("/scan", methods=["POST"])
def scan_now():
    profile = _resolve_profile()
    if not profile.active:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message=f"'{profile.name}' portfolio isn't funded yet."))

    relevant_markets = {e.market for e in effective_universe(profile)}
    if not is_any_market_open(relevant_markets, datetime.now(timezone.utc)):
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="All of this portfolio's markets are closed right now -- "
                                         "no trades can be placed, so the scan was skipped."))
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

    save_scan_settings(profile.scan_settings_path, settings)
    push_state_to_github(profile.scan_settings_path)
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

    settings = load_scan_settings(profile.scan_settings_path, default_capital=profile.initial_capital)
    client_config = get_client_config()
    trade_client = TradeClient(client_config)
    sleeve_by_symbol = {e.symbol: e.sleeve for e in effective_universe(profile)}
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


_MARKET_TO_CURRENCY_EXCHANGE = {
    "US": ("USD", ""),
    "HK": ("HKD", "SEHK"),
    "SG": ("SGD", "SGX"),
}


@app.route("/universe/add", methods=["POST"])
def universe_add():
    """Adds one screener-suggested symbol (see sector_suggestions.py) to
    this profile's tradeable universe -- a human-approved UNIVERSE
    change, not a trade: no order is placed and no risk_engine check
    runs (there's no notional/quantity to validate), it just becomes
    eligible for scoring starting with the next scan (see
    portfolio_profiles.effective_universe)."""
    profile = _resolve_profile()
    symbol = request.form.get("symbol", "").strip()
    market = request.form.get("market", "").strip().upper()
    source_sector = request.form.get("source_sector", "")

    if not symbol or market not in _MARKET_TO_CURRENCY_EXCHANGE:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="Couldn't add that symbol -- missing or unrecognized market."))

    # Render's disk is ephemeral -- a local-only write here survives only
    # until the next restart/redeploy, or until scheduled_pull_state's
    # 10-minute pull silently overwrites it with the stale GitHub copy.
    # Refuse up front rather than claiming success and having the
    # addition quietly vanish later (the exact bug this route used to
    # have -- confirmed by report: an added symbol "didn't seem to
    # track"). Same refusal /approve already uses for the same reason.
    if get_github_config() is None:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message="Refusing to add: GITHUB_TOKEN/GITHUB_REPO aren't set in this "
                                         "environment, so the addition couldn't be synced and would not "
                                         "have survived a restart."))

    try:
        validate_new_universe_entry(symbol, profile)
    except ValueError as e:
        return redirect(url_for("dashboard", portfolio=profile.name, message=f"Couldn't add {symbol}: {e}"))

    currency, exchange = _MARKET_TO_CURRENCY_EXCHANGE[market]
    sleeve = "core" if profile.name == "dividend" else "satellite"
    entry = ExtraUniverseEntry(
        symbol=symbol, market=market, currency=currency, exchange=exchange, sleeve=sleeve,
        added_at=date.today().isoformat(), source_sector=source_sector,
    )
    add_entry(profile.extra_universe_path, entry)
    try:
        pushed = push_state_to_github(profile.extra_universe_path)
    except Exception as e:
        pushed = False
        print(f"universe/add GitHub push raised for '{symbol}': {type(e).__name__}: {e}")

    if not pushed:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message=f"Added {symbol} locally, but the GitHub sync failed -- it may not "
                                         "survive a restart. Check the logs, then try adding it again."))

    return redirect(url_for("dashboard", portfolio=profile.name,
                             message=f"Added {symbol} to the {profile.name} universe -- "
                                     "it'll be considered starting with the next scan."))


@app.route("/universe/remove", methods=["POST"])
def universe_remove():
    """Reverses a /universe/add -- drops the symbol from this profile's
    approved-extras file. Does not touch any existing position; close
    that separately first if you hold one."""
    profile = _resolve_profile()
    symbol = request.form.get("symbol", "").strip()
    if not symbol:
        return redirect(url_for("dashboard", portfolio=profile.name, message="Nothing to remove."))

    remove_entry(profile.extra_universe_path, symbol)
    try:
        pushed = push_state_to_github(profile.extra_universe_path)
    except Exception as e:
        pushed = False
        print(f"universe/remove GitHub push raised for '{symbol}': {type(e).__name__}: {e}")

    if not pushed:
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message=f"Removed {symbol} locally, but the GitHub sync failed -- "
                                         "it may reappear after a restart. Check the logs."))
    return redirect(url_for("dashboard", portfolio=profile.name, message=f"Removed {symbol} from the universe."))


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
    sleeve_by_symbol = {e.symbol: e.sleeve for e in effective_universe(profile)}

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

    sleeve_by_symbol = {e.symbol: e.sleeve for e in effective_universe(profile)}
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

    universe_by_symbol = {e.symbol: e for e in effective_universe(profile)}
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
    sleeve_by_symbol = {e.symbol: e.sleeve for e in effective_universe(profile)}
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

    universe_by_symbol = {e.symbol: e for e in effective_universe(profile)}

    entry = universe_by_symbol.get(item["symbol"])
    if entry is not None and not is_any_market_open({entry.market}, datetime.now(timezone.utc)):
        return redirect(url_for("dashboard", portfolio=profile.name,
                                 message=f"Can't place this order right now -- {item['symbol']}'s "
                                         f"({entry.market}) market is closed. Try again during its "
                                         "regular trading hours; this approval is still pending."))

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
