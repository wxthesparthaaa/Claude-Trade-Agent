"""
Run with:
    pytest tests/test_self_improvement.py -v

Mirrors the sibling Forex Agent project's own pause/resume tests --
same mechanical shape, adapted to this project's JournalEntry-based P&L.
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from self_improvement import (
    SelfImprovementState, load_self_improvement_state, save_self_improvement_state,
    week_pnl_by_symbol, apply_self_improvement, resumes_on,
    PAUSE_AFTER_NEGATIVE_WEEKS, PNL_HISTORY_WEEKS, PAUSE_DURATION_WEEKS,
)
from trade_journal import JournalEntry


def _closed_entry(symbol, closed_at, realized_pnl):
    return JournalEntry(
        symbol=symbol, sleeve="core", position_type="long", quantity=1, entry_price=100.0,
        confidence_pct=None, reason="test", opened_at="2026-01-01", status="CLOSED",
        closed_at=closed_at, exit_price=100.0, realized_pnl=realized_pnl,
    )


def _open_entry(symbol):
    return JournalEntry(
        symbol=symbol, sleeve="core", position_type="long", quantity=1, entry_price=100.0,
        confidence_pct=None, reason="test", opened_at="2026-01-01",
    )


# ---- week_pnl_by_symbol -------------------------------------------------------

def test_week_pnl_by_symbol_sums_closed_trades_in_window():
    entries = [
        _closed_entry("AAA", "2026-08-11", 10.0),
        _closed_entry("AAA", "2026-08-12", -3.0),
        _closed_entry("BBB", "2026-08-13", 5.0),
    ]
    result = week_pnl_by_symbol(entries, since_iso="2026-08-10")
    assert result == {"AAA": 7.0, "BBB": 5.0}


def test_week_pnl_by_symbol_excludes_trades_before_the_window():
    entries = [_closed_entry("AAA", "2026-08-01", 100.0)]
    assert week_pnl_by_symbol(entries, since_iso="2026-08-10") == {}


def test_week_pnl_by_symbol_ignores_open_entries():
    entries = [_open_entry("AAA")]
    assert week_pnl_by_symbol(entries, since_iso="2026-08-10") == {}


def test_week_pnl_by_symbol_empty_when_no_entries():
    assert week_pnl_by_symbol([], since_iso="2026-08-10") == {}


# ---- apply_self_improvement ---------------------------------------------------

def test_a_single_losing_week_does_not_pause():
    state = SelfImprovementState()
    changes = apply_self_improvement(state, {"AAA": -10.0}, today=date(2026, 8, 14))
    assert state.paused_symbols == {}
    assert changes == []
    assert state.weekly_pnl_by_symbol["AAA"] == [-10.0]


def test_pauses_after_n_consecutive_losing_weeks():
    state = SelfImprovementState(weekly_pnl_by_symbol={"AAA": [-1.0, -2.0]})  # 2 prior losing weeks
    assert PAUSE_AFTER_NEGATIVE_WEEKS == 3
    changes = apply_self_improvement(state, {"AAA": -3.0}, today=date(2026, 8, 14))
    assert "AAA" in state.paused_symbols
    assert state.paused_symbols["AAA"] == "2026-08-14"
    assert any("Auto-paused AAA" in c for c in changes)


def test_does_not_pause_if_one_of_the_trailing_weeks_was_positive():
    state = SelfImprovementState(weekly_pnl_by_symbol={"AAA": [-1.0, 5.0]})  # a winning week breaks the streak
    changes = apply_self_improvement(state, {"AAA": -3.0}, today=date(2026, 8, 14))
    assert state.paused_symbols == {}
    assert changes == []


def test_trailing_history_is_capped_at_pnl_history_weeks():
    assert PNL_HISTORY_WEEKS == 4
    state = SelfImprovementState(weekly_pnl_by_symbol={"AAA": [100.0, -1.0, -2.0, -3.0]})
    apply_self_improvement(state, {"AAA": -4.0}, today=date(2026, 8, 14))
    assert len(state.weekly_pnl_by_symbol["AAA"]) == PNL_HISTORY_WEEKS
    assert state.weekly_pnl_by_symbol["AAA"] == [-1.0, -2.0, -3.0, -4.0]


def test_already_paused_symbol_is_not_re_evaluated():
    state = SelfImprovementState(paused_symbols={"AAA": "2026-08-01"})
    changes = apply_self_improvement(state, {"AAA": -999.0}, today=date(2026, 8, 3))
    assert state.weekly_pnl_by_symbol.get("AAA", []) == []  # no history appended while paused
    assert changes == []


def test_resumes_after_pause_duration_and_resets_history():
    assert PAUSE_DURATION_WEEKS == 2
    state = SelfImprovementState(
        paused_symbols={"AAA": "2026-08-01"},
        weekly_pnl_by_symbol={"AAA": [-1.0, -2.0, -3.0]},
    )
    changes = apply_self_improvement(state, {}, today=date(2026, 8, 15))  # exactly 2 weeks later
    assert "AAA" not in state.paused_symbols
    assert state.weekly_pnl_by_symbol["AAA"] == []
    assert any("Resumed AAA" in c for c in changes)


def test_does_not_resume_before_pause_duration_elapses():
    state = SelfImprovementState(paused_symbols={"AAA": "2026-08-01"})
    changes = apply_self_improvement(state, {}, today=date(2026, 8, 10))  # only 9 days later
    assert "AAA" in state.paused_symbols
    assert changes == []


def test_unrelated_symbols_are_independent():
    state = SelfImprovementState(weekly_pnl_by_symbol={"AAA": [-1.0, -2.0]})
    changes = apply_self_improvement(state, {"AAA": -3.0, "BBB": 50.0}, today=date(2026, 8, 14))
    assert "AAA" in state.paused_symbols
    assert "BBB" not in state.paused_symbols
    assert state.weekly_pnl_by_symbol["BBB"] == [50.0]


# ---- resumes_on -----------------------------------------------------------------

def test_resumes_on_adds_pause_duration_weeks():
    assert resumes_on("2026-08-01") == "2026-08-15"


# ---- load/save round trip --------------------------------------------------------

def test_load_returns_empty_state_when_file_missing(tmp_path):
    state = load_self_improvement_state(str(tmp_path / "does_not_exist.json"))
    assert state == SelfImprovementState()


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "paused_symbols.json")
    original = SelfImprovementState(
        paused_symbols={"AAA": "2026-08-01"},
        weekly_pnl_by_symbol={"AAA": [], "BBB": [-1.0, 2.0]},
        week_start="2026-08-08",
    )
    save_self_improvement_state(path, original)
    loaded = load_self_improvement_state(path)
    assert loaded == original
