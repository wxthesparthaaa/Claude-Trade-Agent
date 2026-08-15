"""
Mechanical, explainable, downside-only self-improvement: a symbol that
closes net-negative for PAUSE_AFTER_NEGATIVE_WEEKS traded weeks running
gets paused from NEW entries for PAUSE_DURATION_WEEKS, then automatically
resumes with a fresh trailing history. Mirrors the sibling Forex Agent
project's per-instrument pause mechanism 1:1 (see its
scheduled_jobs.py::_apply_self_improvement -- same constants, same
mechanical downside-only shape), adapted here to this project's
trade_journal (realized_pnl on CLOSED JournalEntry rows) instead of
Forex's closed-trade list, and to per-profile persistence (growth and
dividend each pause independently -- see portfolio_profiles.py's
paused_symbols_path).

Deliberately never increases size or focus on a hot symbol -- a handful
of trades a week is too small a sample to safely lean into, same
reasoning the Forex Agent module documents.

A paused symbol is excluded from NEW entries only (see scan_workflow.py)
-- it never blocks exiting/stop-lossing a position already held, mirroring
that module's existing confidence-gate's own "never force-liquidate
something already held" rule.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from trade_journal import JournalEntry

# How many of a symbol's last TRADED weeks (not calendar weeks -- a week
# with zero closed trades leaves no data point either way) must all be
# net-negative before it gets auto-paused.
PAUSE_AFTER_NEGATIVE_WEEKS = 3
# How many of those trailing traded weeks are kept per symbol.
PNL_HISTORY_WEEKS = 4
# Fixed cooldown before a pause auto-expires. Deliberately a fixed
# duration rather than a performance gate ("resume once it's no longer
# net-negative") -- a paused symbol isn't generating new entries, so it
# can never generate the data that would prove recovery; re-evaluating
# from scratch after a fixed break avoids that deadlock.
PAUSE_DURATION_WEEKS = 2


@dataclass
class SelfImprovementState:
    paused_symbols: Dict[str, str] = field(default_factory=dict)              # {symbol: iso date paused}
    weekly_pnl_by_symbol: Dict[str, List[float]] = field(default_factory=dict)  # {symbol: [pnl, oldest first]}
    week_start: Optional[str] = None  # ISO date -- start of the current trailing-P&L window


def load_self_improvement_state(path: str) -> SelfImprovementState:
    if not os.path.exists(path):
        return SelfImprovementState()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return SelfImprovementState(
        paused_symbols=data.get("paused_symbols", {}),
        weekly_pnl_by_symbol=data.get("weekly_pnl_by_symbol", {}),
        week_start=data.get("week_start"),
    )


def save_self_improvement_state(path: str, state: SelfImprovementState) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)


def week_pnl_by_symbol(entries: List[JournalEntry], since_iso: str) -> Dict[str, float]:
    """Sums realized_pnl across CLOSED journal entries closed on/after
    since_iso, grouped by symbol -- only symbols with at least one closed
    trade in the window get an entry, same as Forex Agent's own
    week_by_instrument (a quiet week leaves no data point either way)."""
    totals: Dict[str, float] = {}
    for e in entries:
        if e.status != "CLOSED" or e.closed_at is None or e.realized_pnl is None:
            continue
        if e.closed_at < since_iso:
            continue
        totals[e.symbol] = totals.get(e.symbol, 0.0) + e.realized_pnl
    return totals


def apply_self_improvement(state: SelfImprovementState, pnl_by_symbol: Dict[str, float], today: date) -> List[str]:
    """Mutates state in place (resume expirations, append this week's P&L,
    pause on a qualifying losing streak). Returns human-readable change
    lines for the weekly review digest -- empty if nothing changed."""
    changes: List[str] = []

    expired = [
        symbol for symbol, paused_iso in state.paused_symbols.items()
        if today - date.fromisoformat(paused_iso) >= timedelta(weeks=PAUSE_DURATION_WEEKS)
    ]
    for symbol in expired:
        del state.paused_symbols[symbol]
        state.weekly_pnl_by_symbol[symbol] = []
        changes.append(f"Resumed {symbol} after a {PAUSE_DURATION_WEEKS}-week pause -- re-evaluating fresh")

    for symbol, pnl in pnl_by_symbol.items():
        if symbol in state.paused_symbols:
            continue
        history = state.weekly_pnl_by_symbol.setdefault(symbol, [])
        history.append(pnl)
        del history[:-PNL_HISTORY_WEEKS]
        if len(history) >= PAUSE_AFTER_NEGATIVE_WEEKS and all(p < 0 for p in history[-PAUSE_AFTER_NEGATIVE_WEEKS:]):
            state.paused_symbols[symbol] = today.isoformat()
            changes.append(f"Auto-paused {symbol} for {PAUSE_DURATION_WEEKS} weeks: "
                            f"net-negative {PAUSE_AFTER_NEGATIVE_WEEKS} weeks running")

    return changes


def resumes_on(paused_iso: str) -> str:
    """The date a pause auto-expires -- used by the dashboard to show
    'resumes on <date>' next to each paused symbol."""
    return (date.fromisoformat(paused_iso) + timedelta(weeks=PAUSE_DURATION_WEEKS)).isoformat()
