"""
SEC 8-K event guard (growth only).

A fresh 8-K carrying one of four items means the company itself has just
disclosed something that breaks a trend-following entry thesis, often
hours before the price shows it:
  1.03  bankruptcy or receivership
  2.04  triggering event that accelerates a debt obligation
  3.01  delisting notice / failure to satisfy a listing rule
  4.02  non-reliance on previously issued financial statements
A name with one of these filed in the last few days gets NO NEW entry
(a held name is never force-sold by this: the 20% stop is the exit, and the
pre-open Telegram alert tells you about it). Item 5.02 (a director or
officer leaving or joining, e.g. a CEO resigning) is far more common and
usually not an emergency, so it is reported in the alert only and never
blocks.

Free, official, no key: EDGAR's per-company submissions feed, through the
existing sec_edgar_adapter (same generic User-Agent, nothing personal is
sent). US-listed SEC filers only -- ETFs and HK/SG names have no 8-Ks and
are skipped. Fetched once per weekday before the US open (preopen_check.py)
and persisted to event_flags.json, so a scan reads a small file instead of
making ~100 SEC calls.

Pure logic plus one thin fetch function.
"""
import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import sec_edgar_adapter

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
BLOCKING_ITEMS = {
    "1.03": "bankruptcy or receivership",
    "2.04": "debt acceleration (triggering event)",
    "3.01": "delisting notice / listing-rule failure",
    "4.02": "non-reliance on prior financial statements",
}
INFO_ITEMS = {"5.02": "director/officer departure or appointment"}
DEFAULT_BLOCK_DAYS = 5      # calendar days a blocking filing keeps a name out of NEW entries
DEFAULT_LOOKBACK_DAYS = 7   # how far back a scan looks for filings to persist
REQUEST_PAUSE_SECONDS = 0.15  # SEC fair access allows 10 requests/second; stay well under


@dataclass
class EightK:
    filed: str                 # "YYYY-MM-DD"
    items: List[str]           # e.g. ["4.02", "9.01"]
    accession: str


def parse_recent_8ks(submissions: Optional[dict], since: date) -> List[EightK]:
    """Pure. submissions: EDGAR's CIK##########.json. Returns the 8-K / 8-K/A
    filings on or after `since` that carry at least one item we care about
    (blocking or informational), newest first. A malformed or empty payload
    gives []."""
    if not submissions:
        return []
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms, dates = recent.get("form") or [], recent.get("filingDate") or []
    items_col, accessions = recent.get("items") or [], recent.get("accessionNumber") or []
    wanted = set(BLOCKING_ITEMS) | set(INFO_ITEMS)
    found: List[EightK] = []
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A") or i >= len(dates):
            continue
        try:
            filed = date.fromisoformat(dates[i])
        except ValueError:
            continue
        if filed < since:
            continue
        raw_items = items_col[i] if i < len(items_col) else ""
        items = [x.strip() for x in str(raw_items).split(",") if x.strip()]
        if not wanted.intersection(items):
            continue
        found.append(EightK(filed=dates[i], items=items, accession=accessions[i] if i < len(accessions) else ""))
    found.sort(key=lambda f: f.filed, reverse=True)
    return found


def fetch_submissions(cik: str) -> Optional[dict]:
    """The only network call in this module (None on any failure)."""
    return sec_edgar_adapter._sec_get(SUBMISSIONS_URL.format(cik=cik))


def scan_universe(symbols: List[str], today: date, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                  ticker_cik_map: Optional[Dict[str, str]] = None, fetch=fetch_submissions,
                  pause: float = REQUEST_PAUSE_SECONDS) -> Dict[str, List[EightK]]:
    """Symbols with a relevant 8-K in the lookback window -> their filings.
    ticker_cik_map defaults to SEC's directory (one fetch for the whole run);
    a symbol with no CIK (ETF, HK/SG) is skipped; one failed lookup never
    aborts the rest."""
    if ticker_cik_map is None:
        ticker_cik_map = sec_edgar_adapter.parse_ticker_cik_map(sec_edgar_adapter.fetch_ticker_cik_map())
    since = today - timedelta(days=lookback_days)
    out: Dict[str, List[EightK]] = {}
    for symbol in symbols:
        cik = ticker_cik_map.get(symbol.upper())
        if cik is None:
            continue
        try:
            filings = parse_recent_8ks(fetch(cik), since)
        except Exception as e:  # one bad company must not sink the run
            print(f"  Event guard: lookup failed for {symbol} ({type(e).__name__}: {e})")
            filings = []
        if filings:
            out[symbol] = filings
        if pause:
            time.sleep(pause)
    return out


def save_event_flags(path: str, flags: Dict[str, List[EightK]], as_of: str) -> None:
    data = {"as_of": as_of, "events": {
        s: [{"filed": f.filed, "items": f.items, "accession": f.accession} for f in fs] for s, fs in flags.items()}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def load_event_flags(path: str) -> Dict[str, List[EightK]]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {s: [EightK(filed=e["filed"], items=e.get("items", []), accession=e.get("accession", "")) for e in es]
            for s, es in (data.get("events") or {}).items()}


def describe_items(items: List[str]) -> str:
    """'Item 4.02 (non-reliance ...)' for the items we know, in the order given."""
    labels = {**BLOCKING_ITEMS, **INFO_ITEMS}
    known = [i for i in items if i in labels]
    return ", ".join(f"Item {i} ({labels[i]})" for i in known)


def blocked_symbols(flags: Dict[str, List[EightK]], today: date, block_days: int = DEFAULT_BLOCK_DAYS) -> Dict[str, str]:
    """Pure. symbol -> the reason shown in the decision log, for every name with a BLOCKING-item 8-K filed within
    `block_days` calendar days of today. Informational items (5.02) never block."""
    cutoff = today - timedelta(days=block_days)
    blocked: Dict[str, str] = {}
    for symbol, filings in flags.items():
        for f in sorted(filings, key=lambda x: x.filed, reverse=True):
            try:
                filed = date.fromisoformat(f.filed)
            except ValueError:
                continue
            hits = [i for i in f.items if i in BLOCKING_ITEMS]
            if hits and filed >= cutoff:
                blocked[symbol] = (f"event guard: 8-K filed {f.filed} -- {describe_items(hits)}; "
                                   f"no new entry for {block_days} days")
                break
    return blocked
