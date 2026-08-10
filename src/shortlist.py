"""
Growth-only watchlist for candidates in the confidence middle band
(shortlist_threshold <= confidence < execute_threshold) -- re-scored on
every scan for up to a month, with the confidence delta since the last
test kept for the dashboard's color-coded badge. Candidates that
graduate (confidence rises to execute_threshold+) or fall out
(confidence drops below shortlist_threshold) are removed, not archived
-- a graduated candidate becomes a normal pending approval instead, and
a dropped one is just a rejection, same as any other candidate.
"""
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

MAX_AGE_DAYS = 30  # "over the course of a month" -- a documented constant, not a setting


@dataclass
class ShortlistEntry:
    symbol: str
    sleeve: str
    first_seen: str
    last_updated: str
    confidence_pct: float
    previous_confidence_pct: Optional[float]
    score: float
    price: float
    reason: str


def load_shortlist(path: str) -> List[ShortlistEntry]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [ShortlistEntry(**entry) for entry in data]


def save_shortlist(path: str, entries: List[ShortlistEntry]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in entries], f, indent=2)


def prune_expired_shortlist(entries: List[ShortlistEntry], as_of: str, max_age_days: int = MAX_AGE_DAYS) -> List[ShortlistEntry]:
    today = datetime.fromisoformat(as_of).date()
    kept = []
    for entry in entries:
        first_seen = datetime.fromisoformat(entry.first_seen).date()
        if (today - first_seen) <= timedelta(days=max_age_days):
            kept.append(entry)
    return kept


def update_shortlist(
    existing: List[ShortlistEntry],
    confidence_by_symbol: Dict[str, float],
    score_by_symbol: Dict[str, float],
    price_by_symbol: Dict[str, float],
    sleeve_by_symbol: Dict[str, str],
    execute_threshold_pct: float,
    shortlist_threshold_pct: float,
    as_of: Optional[str] = None,
    held_symbols: Optional[set] = None,
) -> List[ShortlistEntry]:
    """
    Symbols scored this run that fall in [shortlist_threshold,
    execute_threshold) are upserted (rolling the old confidence_pct into
    previous_confidence_pct so the dashboard can show the delta);
    symbols that graduated or dropped out are removed. A symbol that
    already has an entry but wasn't scored this run (e.g. missing price
    history today) is left untouched -- it still ages out via
    prune_expired_shortlist on a future run.

    held_symbols: symbols you already hold a position in are always
    removed/excluded, regardless of confidence -- the shortlist is a
    watchlist of PROSPECTIVE new trades, not a place for something
    you've already bought (an existing position's fate is decided by
    the normal rebalance ranking and exit rules, not this list).
    """
    as_of = as_of or date.today().isoformat()
    held_symbols = held_symbols or set()
    by_symbol = {e.symbol: e for e in prune_expired_shortlist(existing, as_of)}

    for symbol, confidence in confidence_by_symbol.items():
        if symbol in held_symbols or confidence >= execute_threshold_pct or confidence < shortlist_threshold_pct:
            by_symbol.pop(symbol, None)
            continue

        prior = by_symbol.get(symbol)
        by_symbol[symbol] = ShortlistEntry(
            symbol=symbol,
            sleeve=sleeve_by_symbol.get(symbol, "unknown"),
            first_seen=prior.first_seen if prior else as_of,
            last_updated=as_of,
            confidence_pct=confidence,
            previous_confidence_pct=prior.confidence_pct if prior else None,
            score=score_by_symbol.get(symbol, 0.0),
            price=price_by_symbol.get(symbol, 0.0),
            reason=f"confidence {confidence:.1f}% -- watching for {execute_threshold_pct:.0f}%+ to become a trade proposal",
        )

    return sorted(by_symbol.values(), key=lambda e: e.confidence_pct, reverse=True)
