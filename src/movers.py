"""
Today's most-active/moving stocks per market, straight from Tiger's own
ranking (QuoteClient.get_trade_rank) -- confirmed live this is a real,
Tiger-curated "what's moving right now" list (semiconductor names
dominated the top of the US list the day this was built, consistent
with sector_rotation.py's own independent finding that Technology was
the hottest US sector that same day). Very likely the same data behind
whatever "movers"/"hot stocks" screen shows in the Tiger app itself --
there's no separate news endpoint exposed in this SDK to pull from
directly.

US and HK only -- confirmed live that Tiger's SG endpoint rejects this
call outright (ApiException 1010, "biz param error(market)"), the same
SG gap already established for GICS classification.

Deliberately a standalone module, not sector_rotation.py -- this is
about immediate activity ("what's trading heavily right now"), not
relative-strength ranking. sector_suggestions.py's build_suggestions
is reused as-is to intersect a mover list with a hot sector's
membership (see app.py's scheduled_sector_rotation_update), rather than
duplicating that intersection logic here.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, List

from tigeropen.common.consts import Market

_MARKET_ENUM = {"US": Market.US, "HK": Market.HK}


@dataclass
class MoverEntry:
    symbol: str
    name: str
    change_rate: float
    rank: int  # 1 = most active by Tiger's own ranking, not re-sorted here


@dataclass
class MoversSignal:
    as_of: str
    region: str  # "US" | "HK" | "SG"
    entries: List[MoverEntry] = field(default_factory=list)
    note: str = ""


def fetch_trade_rank(quote_client, market):
    """The only function here that calls get_trade_rank. `market` is a
    tigeropen Market enum member. Returns a pandas DataFrame (Tiger's
    own return type) with at least symbol/name/change_rate columns."""
    return quote_client.get_trade_rank(market)


def parse_trade_rank(df) -> List[MoverEntry]:
    """Pure -- df is fetch_trade_rank's return. Rank follows Tiger's own
    row order (its own activity ranking), not re-sorted here. Empty list
    for a missing/empty DataFrame rather than raising."""
    if df is None or len(df) == 0:
        return []
    return [
        MoverEntry(
            symbol=row["symbol"],
            name=row.get("name", row["symbol"]),
            change_rate=float(row["change_rate"]),
            rank=i + 1,
        )
        for i, (_, row) in enumerate(df.iterrows())
    ]


def rank_movers(quote_client, region: str) -> MoversSignal:
    """Fetch + parse for one region. US/HK only -- SG returns the
    explicit "unavailable" signal without even attempting the call,
    same convention as sector_rotation.sg_unavailable_signal."""
    if region not in _MARKET_ENUM:
        return MoversSignal(
            as_of=date.today().isoformat(), region=region, entries=[],
            note="Tiger's movers ranking isn't available for SG (confirmed unsupported).",
        )
    try:
        df = fetch_trade_rank(quote_client, _MARKET_ENUM[region])
        entries = parse_trade_rank(df)
    except Exception as e:
        print(f"Movers fetch failed for {region}: {type(e).__name__}: {e}")
        entries = []
    return MoversSignal(
        as_of=date.today().isoformat(), region=region, entries=entries,
        note="" if entries else "No movers data yet -- refreshes daily on weekday mornings.",
    )


def refresh_movers(quote_client) -> Dict[str, MoversSignal]:
    """Orchestrates a full refresh across all three regions -- what the
    daily scheduled job calls."""
    return {region: rank_movers(quote_client, region) for region in ("US", "HK", "SG")}


def load_movers(path: str) -> Dict[str, MoversSignal]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        region: MoversSignal(
            as_of=entry["as_of"], region=entry["region"],
            entries=[MoverEntry(**e) for e in entry.get("entries", [])],
            note=entry.get("note", ""),
        )
        for region, entry in data.items()
    }


def save_movers(path: str, signals: Dict[str, MoversSignal]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({region: asdict(sig) for region, sig in signals.items()}, f, indent=2)
