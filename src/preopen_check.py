"""
Weekday pre-open check for the growth portfolio (09:00 New York, 35 minutes
before the US open scan).

Three jobs, all free and keyless except the optional Finnhub news key:
  1. Refresh the SEC 8-K event flags for the growth universe (event_guard.py)
     and persist them, so the 09:35 scan can keep new money out of a name with
     a fresh bankruptcy / delisting / debt-acceleration / non-reliance filing.
  2. For every HELD name, look for a fresh 8-K (any watched item, including a
     director/officer change) and, if a Finnhub key is set, for a severe
     headline published since the previous close.
  3. Send ONE Telegram heads-up if there is anything to say. Silence means a
     clean check -- no daily "all clear" message.

It is an alert, not a trading rule: nothing is sold or bought here. The
20% stop remains the only exit on a held name. Pure logic plus an
orchestrator whose network/Telegram dependencies are injected, so the tests
never touch the network.
"""
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Set
from zoneinfo import ZoneInfo

import event_guard
from event_guard import EightK
from news_relevance import severe_headlines

NEW_YORK = ZoneInfo("America/New_York")
HEADLINE_CHARS = 140
MAX_HEADLINES_PER_SYMBOL = 2


@dataclass
class PreopenAlert:
    symbol: str
    reasons: List[str]
    accessions: List[str] = field(default_factory=list)   # 8-K accession numbers reported, for de-duplication


@dataclass
class PreopenResult:
    flags: Dict[str, List[EightK]]
    held_alerts: List[PreopenAlert]
    new_blocks: Dict[str, str]           # universe names (not held) newly blocked from entry -> reason
    sent: bool = False
    notes: List[str] = field(default_factory=list)


def previous_close(today: date) -> datetime:
    """4pm New York on the previous weekday: the cut-off for 'fresh' news (so Monday looks back over the weekend)."""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, time(16, 0), tzinfo=NEW_YORK)


def build_held_alerts(
    held: Iterable[str],
    events: Dict[str, List[EightK]],
    headlines: Dict[str, List[dict]],
    since: datetime,
    already_reported: Set[str],
) -> List[PreopenAlert]:
    """Pure. One alert per held symbol that has (a) a watched 8-K filed on/after since's date that has not been
    reported before, or (b) a severe headline published after `since`. Sorted by symbol."""
    alerts: List[PreopenAlert] = []
    for symbol in sorted(set(held)):
        reasons: List[str] = []
        accessions: List[str] = []
        for f in events.get(symbol, []):
            try:
                filed = date.fromisoformat(f.filed)
            except ValueError:
                continue
            if filed >= since.date() and f.accession not in already_reported:
                reasons.append(f"SEC 8-K filed {f.filed}: {event_guard.describe_items(f.items)}")
                accessions.append(f.accession)
        for article in severe_headlines(headlines.get(symbol, []), since_ts=since.timestamp(),
                                        limit=MAX_HEADLINES_PER_SYMBOL):
            text = (article.get("headline") or "").strip()
            if len(text) > HEADLINE_CHARS:
                text = text[:HEADLINE_CHARS - 1].rstrip() + "…"
            reasons.append(f"Headline: {text}")
        if reasons:
            alerts.append(PreopenAlert(symbol=symbol, reasons=reasons, accessions=accessions))
    return alerts


def load_reported(path: str) -> Set[str]:
    """8-K accession numbers already announced (kept inside the flags file so no extra state file is needed)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return set(json.load(fh).get("reported", []))
    except (OSError, ValueError):
        return set()


def save_flags_with_reported(path: str, flags: Dict[str, List[EightK]], as_of: str, reported: Set[str]) -> None:
    event_guard.save_event_flags(path, flags, as_of)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Only remember accession numbers still inside the lookback window, so the list cannot grow forever.
    live = {f.accession for fs in flags.values() for f in fs}
    data["reported"] = sorted(reported & live)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def run_preopen_check(
    *,
    today: date,
    flags_path: str,
    universe_symbols: List[str],
    held_symbols: List[str],
    finnhub_key: Optional[str],
    send: Callable[[str], bool],
    format_message: Callable[[List[PreopenAlert], Dict[str, str]], str],
    fetch_cik_map: Callable[[], Dict[str, str]],
    scan_events: Callable[..., Dict[str, List[EightK]]] = event_guard.scan_universe,
    fetch_news: Optional[Callable[[str, str], List[dict]]] = None,
) -> PreopenResult:
    """Orchestrates the three jobs. Every external dependency is a parameter. Failures degrade, they never raise:
    no SEC directory -> the previous flags file is kept untouched; a news failure for one symbol skips just that one."""
    notes: List[str] = []
    reported = load_reported(flags_path)
    symbols = sorted(set(universe_symbols) | set(held_symbols))

    cik_map = fetch_cik_map()
    if cik_map:
        flags = scan_events(symbols, today, ticker_cik_map=cik_map)
    else:
        notes.append("SEC ticker directory unavailable -- kept the previous event flags")
        try:
            flags = event_guard.load_event_flags(flags_path)
        except (OSError, ValueError):
            flags = {}

    since = previous_close(today)
    headlines: Dict[str, List[dict]] = {}
    if finnhub_key and fetch_news is not None:
        for symbol in sorted(set(held_symbols)):
            try:
                headlines[symbol] = fetch_news(symbol, finnhub_key)
            except Exception as e:
                notes.append(f"news fetch failed for {symbol} ({type(e).__name__})")
    elif not finnhub_key:
        notes.append("FINNHUB_API_KEY not set -- headlines skipped, SEC filings only")

    held_alerts = build_held_alerts(held_symbols, flags, headlines, since, reported)

    # Universe names (not held) newly blocked from entry: tell the user once per filing.
    held_set = set(held_symbols)
    new_blocks: Dict[str, str] = {}
    for symbol, reason in event_guard.blocked_symbols(flags, today).items():
        accessions = {f.accession for f in flags.get(symbol, [])}
        if symbol not in held_set and not accessions <= reported:
            new_blocks[symbol] = reason

    result = PreopenResult(flags=flags, held_alerts=held_alerts, new_blocks=new_blocks, notes=notes)
    if cik_map:
        newly_reported = set(reported)
        for a in held_alerts:
            newly_reported.update(a.accessions)
        for symbol in new_blocks:
            newly_reported.update(f.accession for f in flags.get(symbol, []))
        save_flags_with_reported(flags_path, flags, today.isoformat(), newly_reported)
    if held_alerts or new_blocks:
        try:
            result.sent = bool(send(format_message(held_alerts, new_blocks)))
        except Exception as e:
            notes.append(f"Telegram send failed ({type(e).__name__}: {e})")
    return result
