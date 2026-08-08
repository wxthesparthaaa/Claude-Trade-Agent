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
from short_signal import DEFAULT_CROWDED_LONG_TILT_THRESHOLD, market_favors_shorting

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


def _sentiment_label(tilt: float) -> str:
    """Plain-language read of a [-1, 1] sentiment tilt, so a bare number
    like '+0.60' doesn't have to be interpreted by the reader."""
    magnitude = abs(tilt)
    strength = "strongly" if magnitude >= 0.6 else "notably"
    direction = "positive" if tilt > 0 else "negative"
    return f"{strength} {direction}"


def _implication_note(tilt: float, held: bool, short_gate_open: bool) -> str:
    label = _sentiment_label(tilt)
    if held and tilt > 0:
        return f"News sentiment is {label} ({tilt:+.2f}) -- a tailwind for the position you're already holding."
    if held and tilt < 0:
        return (f"News sentiment is {label} ({tilt:+.2f}) -- a headwind on the position you're already "
                f"holding. Nothing automatic happens from this alone; the stop-loss rule (a hard price "
                f"level, not a sentiment score) is what would actually trigger an exit.")
    if not held and tilt > 0:
        return (f"News sentiment is {label} ({tilt:+.2f}) on a name you don't currently hold -- "
                f"not a buy signal by itself, but worth checking if it shows up as a candidate on the next scan.")
    # not held and tilt < 0
    if short_gate_open:
        return (f"News sentiment is {label} ({tilt:+.2f}), and the short-selling gate below is currently "
                f"open -- worth checking whether this shows up as a short candidate on the next scan.")
    return (f"News sentiment is {label} ({tilt:+.2f}) on a name you don't currently hold. The short-selling "
            f"gate is closed right now, so this wouldn't trigger a short candidate even if the price is falling.")


def _positioning_explanation(tilt: float, crowded_threshold: float) -> str:
    """
    tilt comes from cot_adapter.positioning_to_tilt: a bounded ~0.9-1.1
    multiplier derived from CFTC Commitment of Traders data (how
    speculators are positioned in S&P 500 / Nasdaq-100 futures). 1.000 is
    neutral; further from 1.0 means positioning is more stretched.
    """
    if tilt <= crowded_threshold:
        read = (f"crowded LONG -- speculative futures traders are heavily positioned long right now. "
                f"That raises the risk of a forced-selling pullback if sentiment turns (a lot of people "
                f"would be selling into the same downturn at once)")
    elif tilt >= (2.0 - crowded_threshold):  # symmetric on the other side of 1.0
        read = (f"crowded SHORT -- speculative futures traders are heavily positioned short right now. "
                f"That raises the risk of a short squeeze (a sharp rally as short-sellers are forced to "
                f"buy back in)")
    else:
        read = "close to neutral -- not stretched long or short in either direction"
    return (
        f"Futures positioning (CFTC Commitment of Traders data): {read}. "
        f"(tilt={tilt:+.3f} -- 1.000 is neutral; this only reflects crowding in S&P 500/Nasdaq-100 "
        f"index futures, not any specific stock.)"
    )


def _breadth_explanation(trend: str, at_edge: bool) -> str:
    """
    trend/at_edge come from market_breadth.py: the ratio of the
    equal-weight S&P 500 (RSP) to the cap-weight S&P 500 (SPY).
    """
    if trend == "broadening":
        read = "the average stock has been outperforming the mega-caps recently -- a healthier, more broad-based market"
    elif trend == "narrowing":
        read = "a handful of mega-cap stocks have been carrying the market while the average stock lags -- narrower, more fragile leadership"
    else:
        read = "no clear trend either way right now"
    edge_note = (
        " This move looks stretched relative to its own recent history, so a reversal is somewhat "
        "more likely than usual (though not imminent or guaranteed)."
        if at_edge else ""
    )
    return f"Market breadth (equal-weight vs. cap-weight S&P 500): {read}.{edge_note}"


def _macro_note(regime, short_gate_open: bool, crowded_threshold: float = DEFAULT_CROWDED_LONG_TILT_THRESHOLD) -> str:
    if regime is None:
        return "No macro regime data available yet -- the weekly COT and daily market-breadth refresh jobs haven't produced a reading."

    sentences = []
    if regime.positioning_tilt is not None:
        sentences.append(_positioning_explanation(regime.positioning_tilt, crowded_threshold))
    if regime.breadth_trend is not None:
        sentences.append(_breadth_explanation(regime.breadth_trend, regime.breadth_at_edge))

    if short_gate_open:
        gate_desc = (
            "Short-selling gate: OPEN. One of the two conditions above (crowded-long futures positioning, "
            "or a stretched/narrowing breadth trend) is currently met, so the daily scan will consider "
            "tactical short candidates -- individual stocks in a real price breakdown -- alongside the "
            "usual long picks."
        )
    else:
        gate_desc = (
            "Short-selling gate: CLOSED. Neither condition above is currently met, so the daily scan will "
            "NOT consider any short candidates right now, even if a specific stock's price is falling hard. "
            "This is a deliberate, tactical restriction -- shorting only happens \"if the opportunity arises\" "
            "at the macro level, not on any single stock's momentum alone."
        )
    sentences.append(gate_desc)

    return " ".join(sentences) if sentences else "No macro regime data available yet."


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
    """
    Digest for the daily Telegram update: the macro context (positioning/
    breadth/short-gate explanation) plus the top few notable per-symbol
    stories -- the full per-symbol breakdown lives on the dashboard/
    /news page, but the macro context is short enough to always include
    in full rather than truncate.
    """
    lines = []
    if summary.macro_note:
        lines.append(summary.macro_note)

    lines.append("")
    if summary.implications:
        lines.append("Notable news today:")
        for imp in summary.implications[:max_items]:
            direction = "+" if imp.tilt > 0 else ""
            lines.append(f"  {imp.symbol} ({direction}{imp.tilt:.2f}): {imp.note}")
        if len(summary.implications) > max_items:
            lines.append(f"  ...and {len(summary.implications) - max_items} more on the dashboard.")
    else:
        lines.append("No notable per-symbol news today (nothing crossed the sentiment threshold).")

    return "\n".join(lines)
