"""
Screener-sourced "new candidate" suggestions for the currently hottest
GICS classification a profile doesn't already cover -- the part of this
feature that actually widens the tradeable universe, not just visualizes
rotation (see sector_rotation.py) or tilts scoring on symbols already
tracked (see the sector tilt wired into scan_workflow.py). Callers pass
whichever GICS id/name is currently top-ranked -- app.py prefers the
finer Industry Group level (e.g. "Semiconductors & Semiconductor
Equipment") when sector_rotation.py has one, falling back to the
broader top-level sector otherwise -- so the field names below
("sector_name"/"gics_sector_id") hold either, and the reason text is
deliberately worded to make sense for both. Suggestions are
informational only until a human approves one via app.py's
/universe/add route (see universe_extra.py) -- nothing here ever
executes a trade or mutates a profile's universe on its own.

Combines two GICS-taxonomy-only calls from tiger_industry_adapter.py
(never mixed with market_scanner's own, separate BK#### sector tags --
see that module's docstring for why): fetch_industry_stocks(gics_id,
market) for full membership at whichever GICS level was passed in
(confirmed live that Tiger accepts either level), intersected with
fetch_liquid_movers(market) for a liquidity floor, minus symbols the
profile already covers.
"""
import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from typing import List, Optional, Set

from tiger_industry_adapter import (
    fetch_industry_stocks, parse_industry_stocks, fetch_liquid_movers, parse_liquid_movers,
)

MAX_SUGGESTIONS = 10


@dataclass
class SectorSuggestion:
    symbol: str
    market: str
    sector_name: str
    gics_sector_id: str
    discovered_at: str
    reason: str


def build_suggestions(
    gics_sector_id: str, sector_name: str, market: str,
    sector_member_symbols: List[str], liquid_mover_symbols: List[str],
    excluded_symbols: Set[str], as_of: Optional[str] = None, limit: int = MAX_SUGGESTIONS,
) -> List[SectorSuggestion]:
    """Pure -- no network. Intersects sector membership with the
    liquidity-filtered mover list, drops anything already in
    excluded_symbols (e.g. the profile's own effective universe, so a
    symbol you already trade is never "suggested"), and caps the result.
    Order follows sector_member_symbols' own order (Tiger's own ranking
    from get_industry_stocks), not re-sorted here."""
    as_of = as_of or date.today().isoformat()
    liquid_set = set(liquid_mover_symbols)
    candidates = [s for s in sector_member_symbols if s in liquid_set and s not in excluded_symbols]

    return [
        SectorSuggestion(
            symbol=symbol, market=market, sector_name=sector_name, gics_sector_id=gics_sector_id,
            discovered_at=as_of,
            reason=(
                f"{sector_name} is showing the strongest relative momentum right now; "
                f"{symbol} is a liquid name in it you don't currently track."
            ),
        )
        for symbol in candidates[:limit]
    ]


def fetch_suggestions_for_sector(
    quote_client, gics_sector_id: str, sector_name: str, market, excluded_symbols: Set[str],
    min_volume: float = 1_000_000,
) -> List[SectorSuggestion]:
    """Orchestrates one sector's suggestion refresh -- fetches both
    Tiger calls and builds the list. `market` is a tigeropen Market enum
    member; the returned SectorSuggestion.market field stores it as a
    plain string for JSON-friendliness."""
    member_raw = fetch_industry_stocks(quote_client, gics_sector_id, market)
    members = parse_industry_stocks(member_raw)
    movers_raw = fetch_liquid_movers(quote_client, market, min_volume=min_volume)
    movers = parse_liquid_movers(movers_raw)
    market_str = market.value if hasattr(market, "value") else str(market)
    return build_suggestions(gics_sector_id, sector_name, market_str, members, movers, excluded_symbols)


def load_suggestions(path: str) -> List[SectorSuggestion]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [SectorSuggestion(**entry) for entry in data]


def save_suggestions(path: str, suggestions: List[SectorSuggestion]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in suggestions], f, indent=2)
