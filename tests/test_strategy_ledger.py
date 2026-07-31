"""
Run with:
    pytest tests/test_strategy_ledger.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from strategy_ledger import load_or_init_ledger, record_snapshot, latest_capital, capital_n_entries_ago


def test_load_or_init_ledger_creates_seed_entry(tmp_path):
    path = str(tmp_path / "ledger.json")
    ledger = load_or_init_ledger(path, initial_capital=1000.0)
    assert latest_capital(ledger) == 1000.0
    assert os.path.exists(path)


def test_load_or_init_ledger_returns_existing_without_overwriting(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    record_snapshot(path, capital=1050.0, as_of="2026-08-01")
    ledger = load_or_init_ledger(path, initial_capital=999.0)  # should be ignored, file already exists
    assert latest_capital(ledger) == 1050.0


def test_record_snapshot_appends():
    pass  # covered by the round-trip test below


def test_record_snapshot_round_trip(tmp_path):
    path = str(tmp_path / "ledger.json")
    record_snapshot(path, capital=1000.0, as_of="2026-07-31")
    record_snapshot(path, capital=1010.0, as_of="2026-08-01")
    ledger = record_snapshot(path, capital=1005.0, as_of="2026-08-02")
    assert [h["capital"] for h in ledger["history"]] == [1000.0, 1010.0, 1005.0]
    assert latest_capital(ledger) == 1005.0


def test_capital_n_entries_ago(tmp_path):
    path = str(tmp_path / "ledger.json")
    record_snapshot(path, capital=1000.0, as_of="2026-07-25")
    record_snapshot(path, capital=1010.0, as_of="2026-07-26")
    ledger = record_snapshot(path, capital=1005.0, as_of="2026-07-27")
    assert capital_n_entries_ago(ledger, 1) == 1010.0
    assert capital_n_entries_ago(ledger, 2) == 1000.0
    assert capital_n_entries_ago(ledger, 99) == 1000.0  # clamps to oldest


def test_latest_capital_raises_on_empty_history():
    with pytest.raises(ValueError):
        latest_capital({"history": []})
