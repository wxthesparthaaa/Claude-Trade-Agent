"""
R-multiple expectancy from the trade journal -- the "honest odds" framing: is
the strategy's edge real, judged per unit of risk taken rather than in dollars?

R for a closed trade = realized P&L / the $ risk it started with, where the
risk is what the stop-loss would have cost: entry_price x quantity x
stop_loss_pct. A trade that loses exactly its stop is -1R; a winner that
makes twice its stop distance is +2R.

Break-even hit rate = 1 / (1 + payoff), payoff = average win R / average loss
R. A strategy that wins less often than that is losing money however good the
wins feel (e.g. 58% wins with a 0.4 payoff needs ~71% to break even).

Approximation, stated up front: trade_journal keeps ONE aggregated entry per
symbol (current quantity, averaged entry price), so for a position that was
trimmed in stages realized_pnl is the whole round trip but quantity is only
the final lot -- R is then somewhat overstated. Fine as an at-a-glance
health check (and it matters less now that the rebalance band means far
fewer partial trims); not an audit-grade figure.
"""
from dataclasses import dataclass
from typing import List, Optional

from trade_journal import JournalEntry

SMALL_SAMPLE = 10  # below this many closed trades, flag the figure as indicative only


@dataclass
class Expectancy:
    n: int
    avg_r: float
    hit_rate: float                          # 0..1
    break_even_hit_rate: Optional[float]     # None unless there is at least one win AND one loss


def r_multiple(entry: JournalEntry, stop_loss_pct: float) -> Optional[float]:
    """None if this entry can't be expressed in R (not closed, no P&L, or
    nonsensical price/quantity/stop)."""
    if entry.status != "CLOSED" or entry.realized_pnl is None:
        return None
    risk = entry.entry_price * entry.quantity * stop_loss_pct
    if risk <= 0:
        return None
    return entry.realized_pnl / risk


def compute_expectancy(
    entries: List[JournalEntry], stop_loss_pct: float, since_iso: Optional[str] = None,
) -> Optional[Expectancy]:
    """Expectancy over CLOSED entries (closed on/after since_iso if given).
    None when there are no usable closed trades."""
    rs = []
    for e in entries:
        if since_iso is not None and (e.closed_at is None or e.closed_at < since_iso):
            continue
        r = r_multiple(e, stop_loss_pct)
        if r is not None:
            rs.append(r)
    if not rs:
        return None

    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r < 0]
    break_even = None
    if wins and losses:
        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)
        break_even = avg_loss / (avg_win + avg_loss)
    return Expectancy(n=len(rs), avg_r=sum(rs) / len(rs), hit_rate=len(wins) / len(rs), break_even_hit_rate=break_even)


def format_expectancy(label: str, e: Expectancy) -> str:
    text = f"{label}: {e.avg_r:+.2f}R average over {e.n} closed trade{'s' if e.n != 1 else ''}, hit rate {e.hit_rate:.0%}"
    if e.break_even_hit_rate is not None:
        text += f" (needs {e.break_even_hit_rate:.0%} to break even)"
    if e.n < SMALL_SAMPLE:
        text += " -- small sample"
    return text
