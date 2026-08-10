"""
Run with:
    pytest tests/test_journal_export.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dataclasses import asdict
from journal_export import build_journal_workbook, COLUMNS
from trade_journal import JournalEntry


def test_build_journal_workbook_writes_header_row():
    wb = build_journal_workbook([])
    ws = wb.active
    header = [cell.value for cell in ws[1]]
    assert header == COLUMNS


def test_build_journal_workbook_writes_one_row_per_entry():
    entries = [
        asdict(JournalEntry(symbol="NVDA", sleeve="satellite", position_type="long", quantity=5,
                             entry_price=200.0, confidence_pct=81.4, reason="top pick",
                             opened_at="2026-08-01T00:00:00")),
        asdict(JournalEntry(symbol="AMD", sleeve="satellite", position_type="short", quantity=3,
                             entry_price=150.0, confidence_pct=None, reason="backfilled",
                             opened_at="2026-08-02T00:00:00", status="CLOSED", closed_at="2026-08-05T00:00:00",
                             exit_price=130.0, realized_pnl=60.0)),
    ]
    wb = build_journal_workbook(entries)
    ws = wb.active
    assert ws.max_row == 3  # header + 2 entries
    row2 = [cell.value for cell in ws[2]]
    assert row2[0] == "NVDA"
    assert row2[2] == "long"
    assert row2[5] == 81.4
    row3 = [cell.value for cell in ws[3]]
    assert row3[0] == "AMD"
    assert row3[6] == "CLOSED"
    assert row3[10] == 60.0
