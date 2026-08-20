"""
Dividends actually earned by the dividend portfolio, computed by cross-
referencing Tiger's own corporate-dividend schedule
(QuoteClient.get_corporate_dividend: ex-date/record-date/pay-date/amount
per share -- confirmed live it returns real data for US and HK; SG
raised an unhandled TypeError from Tiger's own SDK on an empty result
rather than a clean rejection, so it's treated as "no data" per market
rather than a hard-coded unsupported gap like the GICS/movers ones) --
against this portfolio's own trade journal.

Approximation, stated plainly: trade_journal.py deliberately keeps only
ONE aggregated entry per symbol (current quantity, averaged entry price
-- no multi-lot fill history, see its own docstring), so there's no way
to know the EXACT share count held on every historical date if a
position was partially added to or reduced mid-holding. This module
instead assumes a journal entry's quantity was held for its entire
opened_at -> closed_at (or opened_at -> today, if still open) window --
exact for a pure buy-and-hold position (the common case for this
portfolio's core-only sleeve), approximate for one that was partially
traded mid-holding. Only long positions accrue dividends; shorts are
skipped.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, List, Optional

from tigeropen.common.consts import Market

_MARKET_ENUM = {"US": Market.US, "HK": Market.HK, "SG": Market.SG}


@dataclass
class DividendPayment:
    symbol: str
    amount_per_share: float
    shares_held: int
    total_amount: float
    currency: str
    ex_date: str
    pay_date: str


@dataclass
class DividendSummary:
    as_of: str
    year: int
    total_by_currency: Dict[str, float] = field(default_factory=dict)
    payments: List[DividendPayment] = field(default_factory=list)
    note: str = ""


def fetch_corporate_dividend(quote_client, symbols: List[str], market, begin_date: str, end_date: str):
    """The only function here that calls get_corporate_dividend."""
    return quote_client.get_corporate_dividend(symbols, market, begin_date, end_date)


def parse_corporate_dividend(df) -> List[dict]:
    """Pure -- df is fetch_corporate_dividend's return: a pandas
    DataFrame with symbol/action_type/amount/currency/execute_date/
    pay_date columns (among others). Only actual "DIVIDEND" rows are
    kept (the endpoint can carry other corporate-action types)."""
    if df is None or len(df) == 0:
        return []
    return [
        {
            "symbol": row["symbol"], "amount": float(row["amount"]), "currency": row["currency"],
            "execute_date": row["execute_date"], "pay_date": row.get("pay_date") or "",
        }
        for _, row in df.iterrows()
        if row.get("action_type") == "DIVIDEND"
    ]


def fetch_dividend_events(
    quote_client, symbols_by_market: Dict[str, List[str]], begin_date: str, end_date: str,
) -> Dict[str, List[dict]]:
    """One fetch per market (Tiger's own batching unit), tolerant of a
    single market's failure -- one bad market must not lose every other
    market's real data. See module docstring for the SG caveat found
    live."""
    events_by_symbol: Dict[str, List[dict]] = {}
    for market_code, symbols in symbols_by_market.items():
        if not symbols or market_code not in _MARKET_ENUM:
            continue
        try:
            df = fetch_corporate_dividend(quote_client, symbols, _MARKET_ENUM[market_code], begin_date, end_date)
            events = parse_corporate_dividend(df)
        except Exception as e:
            print(f"Dividend fetch failed for {market_code}: {type(e).__name__}: {e}")
            continue
        for ev in events:
            events_by_symbol.setdefault(ev["symbol"], []).append(ev)
    return events_by_symbol


def compute_dividends_earned(journal_entries, events_by_symbol: Dict[str, List[dict]], year: int) -> DividendSummary:
    """Pure -- no network. See module docstring for the held-quantity
    approximation. journal_entries: trade_journal.JournalEntry list,
    open and closed both included."""
    payments = []
    for entry in journal_entries:
        if entry.position_type != "long":
            continue
        opened = date.fromisoformat(entry.opened_at[:10])
        closed = date.fromisoformat(entry.closed_at[:10]) if entry.closed_at else None
        for ev in events_by_symbol.get(entry.symbol, []):
            ex_date = date.fromisoformat(ev["execute_date"][:10])
            if ex_date.year != year or ex_date < opened or (closed and ex_date > closed):
                continue
            total = round(entry.quantity * ev["amount"], 2)
            payments.append(DividendPayment(
                symbol=entry.symbol, amount_per_share=ev["amount"], shares_held=entry.quantity,
                total_amount=total, currency=ev["currency"], ex_date=ev["execute_date"], pay_date=ev["pay_date"],
            ))

    totals: Dict[str, float] = {}
    for p in payments:
        totals[p.currency] = round(totals.get(p.currency, 0.0) + p.total_amount, 2)

    payments.sort(key=lambda p: p.ex_date)
    return DividendSummary(
        as_of=date.today().isoformat(), year=year, total_by_currency=totals, payments=payments,
        note="" if payments else "No dividend events found yet for this year's holdings.",
    )


def refresh_dividends_earned(
    quote_client, journal_entries, market_by_symbol: Dict[str, str], year: Optional[int] = None,
) -> DividendSummary:
    """Orchestrates a full refresh -- what the daily scheduled job
    calls. market_by_symbol: e.g. {e.symbol: e.market for e in
    effective_universe(profile)} -- symbols missing from it default to
    "US" (this portfolio's overwhelmingly common case)."""
    year = year or date.today().year
    long_symbols = sorted({e.symbol for e in journal_entries if e.position_type == "long"})
    if not long_symbols:
        return DividendSummary(as_of=date.today().isoformat(), year=year,
                                note="No long positions in the journal yet.")

    symbols_by_market: Dict[str, List[str]] = {}
    for symbol in long_symbols:
        market = market_by_symbol.get(symbol, "US")
        symbols_by_market.setdefault(market, []).append(symbol)

    events_by_symbol = fetch_dividend_events(
        quote_client, symbols_by_market, f"{year}-01-01", date.today().isoformat(),
    )
    return compute_dividends_earned(journal_entries, events_by_symbol, year)


def load_dividends_earned(path: str) -> Optional[DividendSummary]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return DividendSummary(
        as_of=data["as_of"], year=data["year"], total_by_currency=data.get("total_by_currency", {}),
        payments=[DividendPayment(**p) for p in data.get("payments", [])], note=data.get("note", ""),
    )


def save_dividends_earned(path: str, summary: DividendSummary) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(summary), f, indent=2)
