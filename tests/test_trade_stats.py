"""
Run with:
    pytest tests/test_trade_stats.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from trade_journal import JournalEntry
from trade_stats import r_multiple, compute_expectancy, format_expectancy, Expectancy


def closed(symbol, entry_price, quantity, pnl, closed_at="2026-10-28T00:00:00"):
    return JournalEntry(
        symbol=symbol, sleeve="satellite", position_type="long", quantity=quantity, entry_price=entry_price,
        confidence_pct=None, reason="", opened_at="2026-10-01T00:00:00", status="CLOSED",
        closed_at=closed_at, exit_price=None, realized_pnl=pnl,
    )


def test_r_multiple_is_pnl_over_the_stop_risk():
    # risk = 100 x 10 x 20% = $200; making $400 is +2R, losing its whole stop is -1R
    assert r_multiple(closed("A", 100.0, 10, 400.0), 0.20) == pytest.approx(2.0)
    assert r_multiple(closed("A", 100.0, 10, -200.0), 0.20) == pytest.approx(-1.0)


def test_r_multiple_none_when_not_expressible():
    open_entry = closed("A", 100.0, 10, 5.0)
    open_entry.status = "OPEN"
    assert r_multiple(open_entry, 0.20) is None
    assert r_multiple(closed("A", 100.0, 10, None), 0.20) is None
    assert r_multiple(closed("A", 100.0, 0, 5.0), 0.20) is None
    assert r_multiple(closed("A", 100.0, 10, 5.0), 0.0) is None


def test_expectancy_hit_rate_and_break_even():
    entries = [
        closed("W1", 100.0, 10, 200.0),    # +1R
        closed("W2", 100.0, 10, 200.0),    # +1R
        closed("L1", 100.0, 10, -400.0),   # -2R
    ]
    e = compute_expectancy(entries, 0.20)
    assert e.n == 3
    assert e.avg_r == pytest.approx(0.0)
    assert e.hit_rate == pytest.approx(2 / 3)
    # avg win 1R, avg loss 2R -> must win 2/(1+2) = 66.7% just to break even
    assert e.break_even_hit_rate == pytest.approx(2 / 3)


def test_expectancy_reproduces_the_real_baseline_shape():
    """58% wins with winners 0.4x the size of losers needs ~71% to break even."""
    entries = [closed(f"W{i}", 100.0, 10, 80.0) for i in range(7)] + [closed(f"L{i}", 100.0, 10, -200.0) for i in range(5)]
    e = compute_expectancy(entries, 0.20)
    assert e.hit_rate == pytest.approx(7 / 12)
    assert e.break_even_hit_rate == pytest.approx(1 / (1 + 0.4))
    assert e.avg_r < 0


def test_expectancy_window_only_counts_trades_closed_since():
    entries = [
        closed("OLD", 100.0, 10, -200.0, closed_at="2026-09-01T00:00:00"),
        closed("NEW", 100.0, 10, 200.0, closed_at="2026-10-28T00:00:00"),
    ]
    e = compute_expectancy(entries, 0.20, since_iso="2026-10-26")
    assert e.n == 1 and e.avg_r == pytest.approx(1.0)


def test_expectancy_none_without_closed_trades():
    assert compute_expectancy([], 0.20) is None


def test_break_even_none_when_all_wins_or_all_losses():
    assert compute_expectancy([closed("W", 100.0, 10, 200.0)], 0.20).break_even_hit_rate is None
    assert compute_expectancy([closed("L", 100.0, 10, -200.0)], 0.20).break_even_hit_rate is None


def test_format_expectancy_flags_small_samples_and_shows_break_even():
    small = format_expectancy("Since inception", Expectancy(n=3, avg_r=-0.21, hit_rate=0.5, break_even_hit_rate=0.62))
    assert small == "Since inception: -0.21R average over 3 closed trades, hit rate 50% (needs 62% to break even) -- small sample"
    big = format_expectancy("This week", Expectancy(n=12, avg_r=0.35, hit_rate=0.75, break_even_hit_rate=None))
    assert big == "This week: +0.35R average over 12 closed trades, hit rate 75%"
