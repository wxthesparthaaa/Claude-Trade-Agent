"""
Run with:
    pytest tests/test_trade_journal.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from trade_journal import JournalEntry, load_journal, save_journal, open_entries, apply_fill, record_fills


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "journal.json")
    entries = [JournalEntry(symbol="NVDA", sleeve="satellite", position_type="long", quantity=5,
                             entry_price=200.0, confidence_pct=81.4, reason="test", opened_at="2026-08-01T00:00:00")]
    save_journal(path, entries)
    assert load_journal(path) == entries


def test_load_returns_empty_list_when_file_missing(tmp_path):
    assert load_journal(str(tmp_path / "missing.json")) == []


def test_apply_fill_buy_with_no_open_entry_opens_a_long():
    entries = apply_fill([], symbol="NVDA", sleeve="satellite", action="BUY", quantity=5,
                          fill_price=200.0, opened_at="2026-08-01T00:00:00", confidence_pct=81.4, reason="entry")
    assert len(entries) == 1
    assert entries[0].position_type == "long"
    assert entries[0].quantity == 5
    assert entries[0].entry_price == 200.0
    assert entries[0].status == "OPEN"


def test_apply_fill_sell_with_no_open_entry_opens_a_short():
    entries = apply_fill([], symbol="AMD", sleeve="satellite", action="SELL", quantity=3,
                          fill_price=150.0, opened_at="2026-08-01T00:00:00")
    assert len(entries) == 1
    assert entries[0].position_type == "short"
    assert entries[0].quantity == 3


def test_apply_fill_adding_to_long_averages_entry_price():
    entries = apply_fill([], symbol="NVDA", sleeve="satellite", action="BUY", quantity=5,
                          fill_price=200.0, opened_at="2026-08-01T00:00:00")
    entries = apply_fill(entries, symbol="NVDA", sleeve="satellite", action="BUY", quantity=5,
                          fill_price=220.0, opened_at="2026-08-02T00:00:00")
    assert len(open_entries(entries)) == 1
    entry = open_entries(entries)[0]
    assert entry.quantity == 10
    assert entry.entry_price == pytest.approx(210.0)


def test_apply_fill_full_close_of_long_computes_realized_pnl():
    entries = apply_fill([], symbol="NVDA", sleeve="satellite", action="BUY", quantity=5,
                          fill_price=200.0, opened_at="2026-08-01T00:00:00")
    entries = apply_fill(entries, symbol="NVDA", sleeve="satellite", action="SELL", quantity=5,
                          fill_price=220.0, opened_at="2026-08-05T00:00:00")
    assert len(entries) == 1
    closed = entries[0]
    assert closed.status == "CLOSED"
    assert closed.exit_price == 220.0
    assert closed.realized_pnl == pytest.approx((220.0 - 200.0) * 5)
    assert closed.closed_at == "2026-08-05T00:00:00"


def test_apply_fill_full_cover_of_short_computes_realized_pnl_with_correct_sign():
    entries = apply_fill([], symbol="AMD", sleeve="satellite", action="SELL", quantity=3,
                          fill_price=150.0, opened_at="2026-08-01T00:00:00")
    entries = apply_fill(entries, symbol="AMD", sleeve="satellite", action="BUY", quantity=3,
                          fill_price=130.0, opened_at="2026-08-05T00:00:00")
    closed = entries[0]
    assert closed.status == "CLOSED"
    # Short profits when price falls: entered at 150, covered at 130 -> +20/share
    assert closed.realized_pnl == pytest.approx((150.0 - 130.0) * 3)


def test_apply_fill_partial_reduce_stays_open_and_accumulates_pnl():
    entries = apply_fill([], symbol="NVDA", sleeve="satellite", action="BUY", quantity=10,
                          fill_price=200.0, opened_at="2026-08-01T00:00:00")
    entries = apply_fill(entries, symbol="NVDA", sleeve="satellite", action="SELL", quantity=4,
                          fill_price=230.0, opened_at="2026-08-05T00:00:00")
    assert len(open_entries(entries)) == 1
    entry = open_entries(entries)[0]
    assert entry.status == "OPEN"
    assert entry.quantity == 6
    assert entry.realized_pnl == pytest.approx((230.0 - 200.0) * 4)

    entries = apply_fill(entries, symbol="NVDA", sleeve="satellite", action="SELL", quantity=6,
                          fill_price=240.0, opened_at="2026-08-10T00:00:00")
    closed = next(e for e in entries if e.symbol == "NVDA")
    assert closed.status == "CLOSED"
    # Running total: first partial (+120) plus the final close (+240) = +360
    assert closed.realized_pnl == pytest.approx((230.0 - 200.0) * 4 + (240.0 - 200.0) * 6)


def test_apply_fill_overshoot_flips_to_opposite_side():
    entries = apply_fill([], symbol="NVDA", sleeve="satellite", action="BUY", quantity=5,
                          fill_price=200.0, opened_at="2026-08-01T00:00:00")
    # Selling more than held -- closes the long and opens a short with the remainder.
    entries = apply_fill(entries, symbol="NVDA", sleeve="satellite", action="SELL", quantity=8,
                          fill_price=210.0, opened_at="2026-08-05T00:00:00")
    closed = next(e for e in entries if e.status == "CLOSED")
    flipped = next(e for e in entries if e.status == "OPEN")
    assert closed.quantity == 5
    assert flipped.position_type == "short"
    assert flipped.quantity == 3


def test_apply_fill_preserves_unrelated_symbols():
    entries = apply_fill([], symbol="NVDA", sleeve="satellite", action="BUY", quantity=5,
                          fill_price=200.0, opened_at="2026-08-01T00:00:00")
    entries = apply_fill(entries, symbol="AMD", sleeve="satellite", action="BUY", quantity=3,
                          fill_price=100.0, opened_at="2026-08-02T00:00:00")
    assert {e.symbol for e in entries} == {"NVDA", "AMD"}


def test_record_fills_applies_multiple_fills_and_persists(tmp_path):
    path = str(tmp_path / "journal.json")
    fills = [
        {"symbol": "NVDA", "sleeve": "satellite", "action": "BUY", "quantity": 5,
         "fill_price": 200.0, "confidence_pct": 81.4, "reason": "top pick"},
        {"symbol": "AMD", "sleeve": "satellite", "action": "SELL", "quantity": 2,
         "fill_price": 150.0},
    ]
    entries = record_fills(path, fills, opened_at="2026-08-01T00:00:00")
    assert len(entries) == 2
    reloaded = load_journal(path)
    assert reloaded == entries


def test_record_fills_confidence_pct_defaults_to_none_when_omitted(tmp_path):
    path = str(tmp_path / "journal.json")
    entries = record_fills(path, [{"symbol": "NVDA", "sleeve": "satellite", "action": "BUY",
                                    "quantity": 5, "fill_price": 200.0}], opened_at="2026-08-01T00:00:00")
    assert entries[0].confidence_pct is None
