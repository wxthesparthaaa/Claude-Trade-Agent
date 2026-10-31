"""
Run with:
    pytest tests/test_strategy_ledger.py -v
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from datetime import date, timedelta

from strategy_ledger import (
    load_or_init_ledger, record_snapshot, latest_capital, capital_n_entries_ago, capital_as_of,
    get_cash_reserve, apply_trade_and_snapshot, mark_to_market_snapshot, reanchor_capital,
    most_recent_reset_date, gain_baseline_date, drawdown_curve, advance_halt_restart,
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


def test_reanchor_capital_preserves_prior_history(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    apply_trade_and_snapshot(path, cash_delta=-100.0, positions_value_now=120.0, as_of="2026-08-01")

    ledger = reanchor_capital(path, target_capital=2000.0, positions_value_now=120.0, as_of="2026-08-10")

    assert len(ledger["history"]) == 3  # seed + trade snapshot + reset, nothing discarded
    assert ledger["history"][0]["capital"] == 1000.0
    assert ledger["history"][-1] == {"date": "2026-08-10", "capital": 2000.0, "type": "reset"}


def test_reanchor_capital_sets_cash_reserve_so_total_matches_target(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    ledger = reanchor_capital(path, target_capital=2000.0, positions_value_now=300.0, as_of="2026-08-10")
    assert get_cash_reserve(ledger) == pytest.approx(1700.0)
    assert latest_capital(ledger) == 2000.0


def test_reanchor_capital_refuses_when_positions_exceed_target(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    with pytest.raises(ValueError, match="worth more than"):
        reanchor_capital(path, target_capital=500.0, positions_value_now=600.0, as_of="2026-08-10")


def test_capital_as_of_finds_most_recent_entry_on_or_before_date():
    ledger = {"history": [
        {"date": "2026-07-01", "capital": 1000.0},
        {"date": "2026-07-15", "capital": 1050.0},
        {"date": "2026-08-01", "capital": 1100.0},
    ]}
    assert capital_as_of(ledger, "2026-07-20") == 1050.0  # closest entry at or before this date


def test_capital_as_of_exact_date_match():
    ledger = {"history": [
        {"date": "2026-07-01", "capital": 1000.0},
        {"date": "2026-08-01", "capital": 1100.0},
    ]}
    assert capital_as_of(ledger, "2026-08-01") == 1100.0


def test_capital_as_of_multiple_entries_same_day_picks_latest():
    ledger = {"history": [
        {"date": "2026-08-01", "capital": 1000.0},
        {"date": "2026-08-01", "capital": 1020.0},
        {"date": "2026-08-01", "capital": 1015.0},
    ]}
    assert capital_as_of(ledger, "2026-08-01") == 1015.0  # last entry that day, not the first


def test_capital_as_of_falls_back_to_earliest_when_date_predates_history():
    ledger = {"history": [
        {"date": "2026-08-01", "capital": 1000.0},
        {"date": "2026-08-05", "capital": 1050.0},
    ]}
    assert capital_as_of(ledger, "2026-07-01") == 1000.0  # doesn't go back that far -- earliest available


def test_capital_as_of_raises_on_empty_history():
    with pytest.raises(ValueError, match="no history"):
        capital_as_of({"history": []}, "2026-08-01")


def test_reanchor_capital_tags_the_new_entry_as_a_reset(tmp_path):
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    ledger = reanchor_capital(path, target_capital=5000.0, positions_value_now=0.0, as_of="2026-08-13")
    assert ledger["history"][-1]["type"] == "reset"


def test_most_recent_reset_date_none_when_never_reset():
    ledger = {"history": [{"date": "2026-08-01", "capital": 1000.0}]}
    assert most_recent_reset_date(ledger) is None


def test_most_recent_reset_date_finds_latest_reset():
    ledger = {"history": [
        {"date": "2026-07-01", "capital": 1000.0, "type": "reset"},
        {"date": "2026-08-01", "capital": 1050.0},
        {"date": "2026-08-10", "capital": 5000.0, "type": "reset"},
    ]}
    assert most_recent_reset_date(ledger) == "2026-08-10"


def test_gain_baseline_date_uses_lookback_when_no_reset():
    ledger = {"history": [{"date": "2026-07-01", "capital": 1000.0}]}
    baseline = gain_baseline_date(ledger, lookback_days=30, today=date(2026, 8, 13))
    assert baseline == "2026-07-14"  # 30 days before 2026-08-13


def test_gain_baseline_date_stops_at_a_recent_reset():
    """Regression test for the real bug this was built to fix: a $1,000
    -> $5,000 capital reset showing up as a 400%+ 'monthly gain' because
    the trailing-30-day baseline reached back to before the reset."""
    ledger = {"history": [
        {"date": "2026-07-01", "capital": 1000.0},
        {"date": "2026-08-10", "capital": 5000.0, "type": "reset"},
    ]}
    baseline = gain_baseline_date(ledger, lookback_days=30, today=date(2026, 8, 13))
    assert baseline == "2026-08-10"  # the reset date, not 30 days back


def test_gain_baseline_date_ignores_an_old_reset_outside_the_window():
    ledger = {"history": [
        {"date": "2026-01-01", "capital": 1000.0, "type": "reset"},
        {"date": "2026-08-01", "capital": 1100.0},
    ]}
    baseline = gain_baseline_date(ledger, lookback_days=30, today=date(2026, 8, 13))
    assert baseline == "2026-07-14"  # the old reset is outside the 30-day window, ignored


def test_monthly_gain_after_reset_reflects_only_post_reset_performance(tmp_path):
    """End-to-end: reset to $5,000, then a real trading gain -- the
    reported gain should be relative to the reset, not the original
    $1,000 baseline."""
    path = str(tmp_path / "ledger.json")
    load_or_init_ledger(path, initial_capital=1000.0)
    record_snapshot(path, capital=1020.0, as_of="2026-08-05")
    reanchor_capital(path, target_capital=5000.0, positions_value_now=0.0, as_of="2026-08-10")
    ledger = record_snapshot(path, capital=5100.0, as_of="2026-08-13")  # real +2% since the reset

    baseline_date = gain_baseline_date(ledger, lookback_days=30, today=date(2026, 8, 13))
    baseline_capital = capital_as_of(ledger, baseline_date)
    gain_pct = (latest_capital(ledger) - baseline_capital) / baseline_capital

    assert baseline_capital == 5000.0
    assert gain_pct == pytest.approx(0.02)  # not the ~400% a naive 30-day lookback would report


# 2026-11-02 is a Monday.
MONDAY = date(2026, 11, 2)


def _halt_ledger(tmp_path, **extra):
    path = str(tmp_path / "ledger.json")
    ledger = {"cash_reserve": 100.0, "history": [{"date": "2026-08-01", "capital": 5000.0},
                                                 {"date": "2026-09-01", "capital": 3000.0}], **extra}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f)
    return path


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_drawdown_curve_is_the_plain_history_when_never_restarted():
    ledger = {"history": [{"date": "a", "capital": 5000.0}, {"date": "b", "capital": 3000.0, "type": "reset"}]}
    assert drawdown_curve(ledger) == [5000.0, 3000.0]


def test_drawdown_curve_after_a_restart_drops_the_old_peak_but_keeps_later_highs():
    ledger = {"history": [{"date": "a", "capital": 5000.0}, {"date": "b", "capital": 3000.0},
                          {"date": "c", "capital": 3500.0}],
              "halt_restart": {"date": "b", "equity": 3100.0, "history_index": 2}}
    assert drawdown_curve(ledger) == [3100.0, 3500.0]


def test_halt_count_starts_and_only_counts_a_date_once(tmp_path):
    path = _halt_ledger(tmp_path)
    first = advance_halt_restart(path, True, 3000.0, 60, MONDAY)
    repeat = advance_halt_restart(path, True, 3000.0, 60, MONDAY)
    assert first == (True, False, 1)
    assert repeat == (False, False, 1)
    assert _read(path)["halt_tracking"] == {"since": "2026-11-02", "last_date": "2026-11-02", "days": 1}


def test_halt_count_skips_weekends_and_scanless_days(tmp_path):
    path = _halt_ledger(tmp_path)
    assert advance_halt_restart(path, True, 3000.0, 60, MONDAY - timedelta(days=2)) == (False, False, 0)  # Saturday
    assert "halt_tracking" not in _read(path)
    advance_halt_restart(path, True, 3000.0, 60, MONDAY)
    # A week with no scans at all adds one day, not six.
    assert advance_halt_restart(path, True, 3000.0, 60, MONDAY + timedelta(days=7)).days == 2


def test_recovery_clears_the_count(tmp_path):
    path = _halt_ledger(tmp_path, halt_tracking={"since": "2026-10-01", "last_date": "2026-10-30", "days": 40})
    assert advance_halt_restart(path, False, 4000.0, 60, MONDAY) == (True, False, 0)
    assert "halt_tracking" not in _read(path)
    # Nothing to clear means nothing to rewrite or push.
    assert advance_halt_restart(path, False, 4000.0, 60, MONDAY).changed is False


def test_restart_day_rebases_the_peak_and_releases_the_halt(tmp_path):
    path = _halt_ledger(tmp_path, halt_tracking={"since": "2026-08-10", "last_date": "2026-10-30", "days": 59})
    assert advance_halt_restart(path, True, 3050.0, 60, MONDAY) == (True, True, 60)
    ledger = _read(path)
    assert "halt_tracking" not in ledger
    assert ledger["halt_restart"] == {"date": "2026-11-02", "equity": 3050.0, "history_index": 2}
    assert drawdown_curve(ledger) == [3050.0]


def test_halt_state_survives_the_ledgers_other_writers(tmp_path):
    path = _halt_ledger(tmp_path, halt_tracking={"since": "2026-10-01", "last_date": "2026-10-30", "days": 40},
                        halt_restart={"date": "2026-01-01", "equity": 1.0, "history_index": 1})
    record_snapshot(path, 3000.0, as_of="2026-11-02")
    apply_trade_and_snapshot(path, -10.0, 2900.0, as_of="2026-11-02")
    mark_to_market_snapshot(path, 2950.0, as_of="2026-11-02")
    ledger = _read(path)
    assert ledger["halt_tracking"]["days"] == 40
    assert ledger["halt_restart"]["history_index"] == 1
