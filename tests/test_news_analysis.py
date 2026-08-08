"""
Run with:
    pytest tests/test_news_analysis.py -v
"""
import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from news_analysis import build_daily_news_summary, format_news_summary_for_telegram, NOTABLE_TILT_THRESHOLD
from news_scanner import SymbolNewsSignal


def signal(symbol, tilt, headlines=None):
    return SymbolNewsSignal(symbol=symbol, tilt=tilt, as_of="2026-08-08", headlines_considered=headlines or [])


def regime(positioning_tilt=1.0, breadth_trend="flat", breadth_at_edge=False):
    return SimpleNamespace(positioning_tilt=positioning_tilt, breadth_trend=breadth_trend, breadth_at_edge=breadth_at_edge)


def test_filters_out_non_notable_tilts():
    signals = {"NVDA": signal("NVDA", 0.1)}  # below threshold
    summary = build_daily_news_summary(signals, held_symbols=set(), as_of="2026-08-08", regime=regime())
    assert summary.implications == []


def test_includes_tilts_at_or_above_threshold():
    signals = {"NVDA": signal("NVDA", NOTABLE_TILT_THRESHOLD)}
    summary = build_daily_news_summary(signals, held_symbols=set(), as_of="2026-08-08", regime=regime())
    assert len(summary.implications) == 1
    assert summary.implications[0].symbol == "NVDA"


def test_sorted_by_absolute_tilt_descending():
    signals = {
        "A": signal("A", 0.35),
        "B": signal("B", -0.9),
        "C": signal("C", 0.5),
    }
    summary = build_daily_news_summary(signals, held_symbols=set(), as_of="2026-08-08", regime=regime())
    assert [i.symbol for i in summary.implications] == ["B", "C", "A"]


def test_held_positive_tailwind_note():
    signals = {"NVDA": signal("NVDA", 0.5)}
    summary = build_daily_news_summary(signals, held_symbols={"NVDA"}, as_of="2026-08-08", regime=regime())
    assert "tailwind" in summary.implications[0].note
    assert summary.implications[0].held is True


def test_held_negative_headwind_note():
    signals = {"NVDA": signal("NVDA", -0.5)}
    summary = build_daily_news_summary(signals, held_symbols={"NVDA"}, as_of="2026-08-08", regime=regime())
    assert "headwind" in summary.implications[0].note
    assert "stop-loss" in summary.implications[0].note


def test_not_held_positive_watch_note():
    signals = {"AVGO": signal("AVGO", 0.6)}
    summary = build_daily_news_summary(signals, held_symbols=set(), as_of="2026-08-08", regime=regime())
    assert "candidate on the next scan" in summary.implications[0].note
    assert "not a buy signal by itself" in summary.implications[0].note
    assert summary.implications[0].held is False


def test_note_includes_sentiment_label_and_value():
    signals = {"NVDA": signal("NVDA", 0.6)}
    summary = build_daily_news_summary(signals, held_symbols={"NVDA"}, as_of="2026-08-08", regime=regime())
    assert "strongly positive" in summary.implications[0].note
    assert "+0.60" in summary.implications[0].note


def test_not_held_negative_mentions_short_gate_when_open():
    # crowded long COT positioning -> short gate open
    signals = {"AMD": signal("AMD", -0.6)}
    summary = build_daily_news_summary(signals, held_symbols=set(), as_of="2026-08-08",
                                        regime=regime(positioning_tilt=0.85))
    assert "short candidate" in summary.implications[0].note
    assert "gate below is currently open" in summary.implications[0].note


def test_not_held_negative_plain_note_when_short_gate_closed():
    signals = {"AMD": signal("AMD", -0.6)}
    summary = build_daily_news_summary(signals, held_symbols=set(), as_of="2026-08-08",
                                        regime=regime(positioning_tilt=1.0))
    assert "gate below is currently open" not in summary.implications[0].note
    assert "short-selling gate is closed right now" in summary.implications[0].note


def test_macro_note_explains_crowded_long_positioning():
    summary = build_daily_news_summary({}, held_symbols=set(), as_of="2026-08-08",
                                        regime=regime(positioning_tilt=0.9, breadth_trend="narrowing", breadth_at_edge=True))
    assert "crowded LONG" in summary.macro_note
    assert "forced-selling pullback" in summary.macro_note
    assert "tilt=+0.900" in summary.macro_note


def test_macro_note_explains_crowded_short_positioning():
    summary = build_daily_news_summary({}, held_symbols=set(), as_of="2026-08-08", regime=regime(positioning_tilt=1.09))
    assert "crowded SHORT" in summary.macro_note
    assert "short squeeze" in summary.macro_note


def test_macro_note_explains_neutral_positioning():
    summary = build_daily_news_summary({}, held_symbols=set(), as_of="2026-08-08", regime=regime(positioning_tilt=1.004))
    assert "close to neutral" in summary.macro_note


def test_macro_note_explains_breadth_and_edge():
    summary = build_daily_news_summary({}, held_symbols=set(), as_of="2026-08-08",
                                        regime=regime(breadth_trend="narrowing", breadth_at_edge=True))
    assert "narrower, more fragile leadership" in summary.macro_note
    assert "stretched relative to its own recent history" in summary.macro_note


def test_macro_note_explains_short_gate_open_and_closed():
    open_summary = build_daily_news_summary({}, held_symbols=set(), as_of="2026-08-08", regime=regime(positioning_tilt=0.85))
    assert "Short-selling gate: OPEN" in open_summary.macro_note
    closed_summary = build_daily_news_summary({}, held_symbols=set(), as_of="2026-08-08", regime=regime(positioning_tilt=1.0))
    assert "Short-selling gate: CLOSED" in closed_summary.macro_note
    assert "if the opportunity arises" in closed_summary.macro_note


def test_macro_note_handles_missing_regime():
    summary = build_daily_news_summary({}, held_symbols=set(), as_of="2026-08-08", regime=None)
    assert "No macro regime data" in summary.macro_note


def test_format_for_telegram_includes_macro_note_and_no_notable_news_message():
    from news_analysis import DailyNewsSummary
    text = format_news_summary_for_telegram(
        DailyNewsSummary(as_of="2026-08-08", implications=[], macro_note="Short-selling gate: CLOSED.")
    )
    assert "Short-selling gate: CLOSED." in text
    assert "No notable per-symbol news today" in text


def test_format_for_telegram_lists_top_items_and_overflow_count():
    signals = {
        "A": signal("A", 0.9), "B": signal("B", -0.8), "C": signal("C", 0.6), "D": signal("D", 0.4),
    }
    summary = build_daily_news_summary(signals, held_symbols=set(), as_of="2026-08-08", regime=regime())
    text = format_news_summary_for_telegram(summary, max_items=3)
    assert summary.macro_note in text
    assert "A (" in text and "B (" in text and "C (" in text
    assert "D (" not in text
    assert "1 more" in text
