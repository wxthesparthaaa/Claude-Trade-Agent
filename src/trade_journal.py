"""
This app's own durable record of every real trade it has placed --
distinct from decision_log.json (rationale for every candidate every
scan, no price/quantity/P&L) and from Tiger's own position data (current
state only, no history or "why"). Ported from the sibling Forex Agent
project's trade_journal.py, adapted to this project's single
current-position-per-symbol model (positions/closes/reduces are already
handled as one aggregate per symbol everywhere else here, e.g.
position_close_confirm -- no multi-lot accounting).

One OPEN entry per symbol at a time. Which side a fill opens/closes is
derived purely from the journal's own current state, not from caller-
supplied intent: a BUY with no open entry opens a long; a SELL with no
open entry opens a short (mirroring how this project already treats
"selling a symbol you don't hold" as what opens a short everywhere
else -- see scan_workflow.py's module docstring). This means the
caller (order_execution.execute_instructions) only needs to hand over
plain fill facts, no extra "is this a short?" flag.

Persisted through the same STATE_FILES/github_state_sync pattern as
every other state file here (see state_paths.JOURNAL_PATH); pushing is
the caller's job, same convention strategy_ledger.py already uses.
"""
import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


@dataclass
class JournalEntry:
    symbol: str
    sleeve: str
    position_type: str        # "long" | "short"
    quantity: int              # current open quantity on this entry
    entry_price: float
    confidence_pct: Optional[float]
    reason: str
    opened_at: str
    status: str = "OPEN"       # "OPEN" | "CLOSED"
    closed_at: Optional[str] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None


def load_journal(path: str) -> List[JournalEntry]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [JournalEntry(**entry) for entry in data]


def save_journal(path: str, entries: List[JournalEntry]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in entries], f, indent=2)


def open_entries(entries: List[JournalEntry]) -> List[JournalEntry]:
    return [e for e in entries if e.status == "OPEN"]


def apply_fill(
    entries: List[JournalEntry], symbol: str, sleeve: str, action: str,
    quantity: int, fill_price: float, opened_at: str,
    confidence_pct: Optional[float] = None, reason: str = "",
) -> List[JournalEntry]:
    """Applies one real fill (action: "BUY" | "SELL") to the journal's
    single-open-entry-per-symbol model. Pure logic -- entries is not
    mutated in place, a new list is returned."""
    untouched = [e for e in entries if not (e.symbol == symbol and e.status == "OPEN")]
    open_entry = next((e for e in entries if e.symbol == symbol and e.status == "OPEN"), None)

    if open_entry is None:
        new_entry = JournalEntry(
            symbol=symbol, sleeve=sleeve, position_type=("long" if action == "BUY" else "short"),
            quantity=quantity, entry_price=fill_price, confidence_pct=confidence_pct,
            reason=reason, opened_at=opened_at,
        )
        return untouched + [new_entry]

    adding = (action == "BUY" and open_entry.position_type == "long") or \
             (action == "SELL" and open_entry.position_type == "short")

    if adding:
        total_quantity = open_entry.quantity + quantity
        averaged_price = ((open_entry.entry_price * open_entry.quantity) + (fill_price * quantity)) / total_quantity
        updated = JournalEntry(**{**asdict(open_entry), "quantity": total_quantity, "entry_price": averaged_price})
        return untouched + [updated]

    # Opposite direction -- reduces or closes the existing position.
    direction_sign = 1 if open_entry.position_type == "long" else -1
    reduced_quantity = min(quantity, open_entry.quantity)
    realized = direction_sign * (fill_price - open_entry.entry_price) * reduced_quantity
    running_pnl = (open_entry.realized_pnl or 0.0) + realized

    result = list(untouched)
    if quantity >= open_entry.quantity:
        closed = JournalEntry(**{
            **asdict(open_entry), "quantity": open_entry.quantity, "status": "CLOSED",
            "closed_at": opened_at, "exit_price": fill_price, "realized_pnl": running_pnl,
        })
        result.append(closed)
        remainder = quantity - open_entry.quantity
        if remainder > 0:
            # Overshoot -- covering/selling more than was open flips into
            # a new position on the other side. Rare, handled rather
            # than silently dropped.
            result.append(JournalEntry(
                symbol=symbol, sleeve=sleeve, position_type=("long" if action == "BUY" else "short"),
                quantity=remainder, entry_price=fill_price, confidence_pct=confidence_pct,
                reason=reason, opened_at=opened_at,
            ))
    else:
        reduced = JournalEntry(**{
            **asdict(open_entry), "quantity": open_entry.quantity - quantity, "realized_pnl": running_pnl,
        })
        result.append(reduced)

    return result


def record_fills(path: str, fills: List[Dict], opened_at: str) -> List[JournalEntry]:
    """fills: [{"symbol", "sleeve", "action", "quantity", "fill_price",
    "confidence_pct" (optional), "reason" (optional)}, ...]. Loads,
    applies each fill in order, saves, and returns the updated journal."""
    entries = load_journal(path)
    for fill in fills:
        entries = apply_fill(entries, opened_at=opened_at, **fill)
    save_journal(path, entries)
    return entries
