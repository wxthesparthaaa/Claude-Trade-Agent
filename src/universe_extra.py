"""
User-approved additions to a profile's tradeable universe, layered on top
of the code-defined DEFAULT_UNIVERSE/DIVIDEND_UNIVERSE (see universe.py)
without ever mutating those lists -- see portfolio_profiles.
effective_universe for how the two are combined. Same load/save-with-
default pattern as shortlist.py: a plain JSON file, full overwrite on
save.

A symbol lands here either through app.py's POST /universe/add route
(a human approves a screener-sourced suggestion -- see
sector_suggestions.py) or, for the growth profile only, automatically
via scheduled_sector_rotation_update when a sector/mover match is
found (see app.py's _auto_add_candidates -- bounded by a per-run cap
and a total-size ceiling, still going through the same
validate_new_universe_entry disjointness check either way) -- this
module itself never decides which symbols to add, it only persists the
decision. auto_added distinguishes the two for the dashboard's
"Approved additions" panel.
"""
import json
import os
from dataclasses import asdict, dataclass
from typing import List


@dataclass
class ExtraUniverseEntry:
    symbol: str
    market: str
    currency: str
    exchange: str
    sleeve: str
    added_at: str
    source_sector: str = ""  # human-readable note, e.g. "Technology" -- purely informational
    auto_added: bool = False  # True if added by scheduled_sector_rotation_update, not a human click


def load_extra_universe(path: str) -> List[ExtraUniverseEntry]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [ExtraUniverseEntry(**entry) for entry in data]


def save_extra_universe(path: str, entries: List[ExtraUniverseEntry]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in entries], f, indent=2)


def add_entry(path: str, entry: ExtraUniverseEntry) -> List[ExtraUniverseEntry]:
    """Loads, appends (replacing any existing entry for the same symbol
    rather than duplicating it), saves, and returns the updated list."""
    entries = [e for e in load_extra_universe(path) if e.symbol != entry.symbol]
    entries.append(entry)
    save_extra_universe(path, entries)
    return entries


def remove_entry(path: str, symbol: str) -> List[ExtraUniverseEntry]:
    """Loads, drops the entry for `symbol` if present, saves, and
    returns the updated list."""
    entries = [e for e in load_extra_universe(path) if e.symbol != symbol]
    save_extra_universe(path, entries)
    return entries
