"""
Deterministic synthesis of "what does today's news mean for this
portfolio" -- connects the free Alpha Vantage sentiment signal
(news_scanner.SymbolNewsSignal, already persisted to config/news_signal.json)
to currently-held positions and the macro short-gate. Entirely rule-based,
no LLM call: consistent with every other signal in this codebase (COT
z-scores, market breadth, momentum -- all pure math, not narration), and
the user's own stated preference against paying for an automated
analysis pass. Pure logic -- reads already-persisted state, never touches
the network itself, so this can render fast on the dashboard/Telegram
without a live Tiger call.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from news_scanner import SymbolNewsSignal

NOTABLE_TILT_THRESHOLD = 0.3  # |tilt| below this isn't worth surfacing as "notable"


@dataclass
class NewsImplication:
    symbol: str
    tilt: float
    headlines: List[str]
    held: bool
    note: str


@dataclass
class DailyNewsSummary:
    as_of: str
    implications: List[NewsImplication] = field(default_factory=list)
    macro_note: str = ""


def _implication_note(tilt: float, held: bool, short_gate_open: bool) -> str:
    if held and tilt > 0:
        return "Positive coverage is a tailwind for your existing position."
    if held and tilt < 0:
        return "Negative coverage is a headwind on your existing position -- watch for the stop-loss."
    if not held and tilt > 0:
        return "Notable positive coverage on a name you don't currently hold -- worth watching for the next scan."
    # not held and tilt < 0
    if short_gate_open:
        return ("Notable negative coverage, and the macro short-gate is currently open -- "
                "worth checking this period's short candidates.")
    return "Notable negative coverage on a name you don't currently hold."


def _macro_note(regime, short_gate_open: bool) -> str:
    if regime is None:
        return "No macro regime data available yet."
    parts = []
    if regime.positioning_tilt is not None:
        parts.append(f"COT positioning tilt {regime.positioning_tilt:+.3f}")
    if regime.breadth_trend is not None:
        edge = " (at an edge)" if regime.breadth_at_edge else ""
        parts.append(f"market breadth {regime.breadth_trend}{edge}")
    parts.append(f"short gate {'OPEN' if short_gate_open else 'closed'}")
    return "; ".join(parts) if parts else "No macro regime data available yet."


def build_daily_news_summary(
    news_signals: Dict[str, SymbolNewsSignal],
    held_symbols: Set[str],
    as_of: str,
    regime=None,
    notable_threshold: float = NOTABLE_TILT_THRESHOLD,
) -> DailyNewsSummary:
    """
    news_signals: from news_scanner.load_news_signal(NEWS_PATH).
    held_symbols: symbols with a currently nonzero position (long or
        short) -- "is this news relevant to something you own."
    regime: a macro_regime.RegimeSignal (or None if regime.json doesn't
        exist yet) -- used only to compute the short-gate status via
        short_signal.market_favors_shorting, and to describe positioning/
        breadth briefly.

    Only symbols with |tilt| >= notable_threshold are included -- most
    symbols on most days have near-neutral coverage, and surfacing every
    one would bury the signal in noise. Sorted by |tilt| descending, so
    the most notable story leads.
    """
    from short_signal import market_favors_shorting
    short_gate_open = market_favors_shorting(regime)

    implications = []
    for symbol, signal in news_signals.items():
        if abs(signal.tilt) < notable_threshold:
            continue
        held = symbol in held_symbols
        implications.append(NewsImplication(
            symbol=symbol,
            tilt=signal.tilt,
            headlines=signal.headlines_considered,
            held=held,
            note=_implication_note(signal.tilt, held, short_gate_open),
        ))

    implications.sort(key=lambda i: abs(i.tilt), reverse=True)

    return DailyNewsSummary(
        as_of=as_of,
        implications=implications,
        macro_note=_macro_note(regime, short_gate_open),
    )


def format_news_summary_for_telegram(summary: DailyNewsSummary, max_items: int = 3) -> str:
    """A short digest for the daily Telegram update -- top few notable
    stories only, not the full breakdown (that's what the dashboard/
    /news page are for)."""
    if not summary.implications:
        return "No notable news today (nothing crossed the sentiment threshold)."
    lines = ["Notable news today:"]
    for imp in summary.implications[:max_items]:
        direction = "+" if imp.tilt > 0 else ""
        lines.append(f"  {imp.symbol} ({direction}{imp.tilt:.2f}): {imp.note}")
    if len(summary.implications) > max_items:
        lines.append(f"  ...and {len(summary.implications) - max_items} more on the dashboard.")
    return "\n".join(lines)
