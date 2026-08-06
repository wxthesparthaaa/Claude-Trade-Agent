"""
Run with:
    pytest tests/test_strategy_ledger.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from strategy_ledger import (
    load_or_init_ledger, record_snapshot, latest_capital, capital_n_entries_ago,
    get_cash_reserve, apply_trade_and_snapshot, mark_to_market_snapshot,
)


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


def test_load_or_init_ledger_seeds_cash_reserve(tmp_path):
    path = str(tmp_path / "ledger.json")
    ledger = load_or_init_ledger(path, initial_capital=1000.0)
    assert get_cash_reserve(ledger) == 1000.0


def test_get_cash_reserve_falls_back_to_latest_capital_for_legacy_ledgers():
    # Ledgers written before cash_reserve existed have no such key.
    legacy_ledger = {"history": [{"date": "2026-07-31", "capital": 1000.0}]}
    assert get_cash_reserve(legacy_ledger) == 1000.0


def test_apply_trade_and_snapshot_buy_converts_cash_to_position_value(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)

    # Spend $525.38 (incl. commission) on a batch of buys; positions are now
    # worth $525.18 at current market prices (tiny price dip since fill).
    ledger = apply_trade_and_snapshot(path, cash_delta=-525.38, positions_value_now=525.18, as_of="2026-08-01")

    assert get_cash_reserve(ledger) == pytest.approx(1000.0 - 525.38)
    assert latest_capital(ledger) == pytest.approx((1000.0 - 525.38) + 525.18)


def test_apply_trade_and_snapshot_sell_returns_cash(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    apply_trade_and_snapshot(path, cash_delta=-500.0, positions_value_now=500.0, as_of="2026-08-01")

    # Sell everything back: cash goes up, positions value goes to zero.
    ledger = apply_trade_and_snapshot(path, cash_delta=497.0, positions_value_now=0.0, as_of="2026-08-02")

    assert get_cash_reserve(ledger) == pytest.approx(500.0 + 497.0)
    assert latest_capital(ledger) == pytest.approx(997.0)  # $3 lost to commission, correctly reflected


def test_apply_trade_and_snapshot_appends_not_overwrites(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    apply_trade_and_snapshot(path, cash_delta=-100.0, positions_value_now=100.0, as_of="2026-08-01")
    ledger = apply_trade_and_snapshot(path, cash_delta=-50.0, positions_value_now=155.0, as_of="2026-08-02")
    assert len(ledger["history"]) == 3  # seed entry + two trade snapshots
    assert [h["capital"] for h in ledger["history"]] == [1000.0, 1000.0, 1005.0]


def test_mark_to_market_snapshot_leaves_cash_reserve_untouched(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    apply_trade_and_snapshot(path, cash_delta=-525.38, positions_value_now=525.18, as_of="2026-08-01")

    # Next day, no trade -- positions are now worth more (price went up).
    ledger = mark_to_market_snapshot(path, positions_value_now=540.00, as_of="2026-08-02")

    assert get_cash_reserve(ledger) == pytest.approx(1000.0 - 525.38)  # unchanged
    assert latest_capital(ledger) == pytest.approx((1000.0 - 525.38) + 540.00)


def test_mark_to_market_snapshot_appends_new_entry(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    ledger = mark_to_market_snapshot(path, positions_value_now=0.0, as_of="2026-08-02")
    assert len(ledger["history"]) == 2
    assert ledger["history"][-1]["date"] == "2026-08-02"
