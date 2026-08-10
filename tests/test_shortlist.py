"""
Run with:
    pytest tests/test_shortlist.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shortlist import (
    ShortlistEntry, load_shortlist, save_shortlist, prune_expired_shortlist, update_shortlist,
)


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "shortlist.json")
    entries = [
        ShortlistEntry(symbol="NVDA", sleeve="satellite", first_seen="2026-08-01", last_updated="2026-08-01",
                        confidence_pct=60.0, previous_confidence_pct=None, score=0.02, price=200.0, reason="test"),
    ]
    save_shortlist(path, entries)
    assert load_shortlist(path) == entries


def test_load_returns_empty_list_when_file_missing(tmp_path):
    assert load_shortlist(str(tmp_path / "missing.json")) == []


def test_prune_expired_shortlist_drops_entries_older_than_max_age():
    entries = [
        ShortlistEntry(symbol="OLD", sleeve="satellite", first_seen="2026-07-01", last_updated="2026-07-01",
                        confidence_pct=55.0, previous_confidence_pct=None, score=0.0, price=1.0, reason=""),
        ShortlistEntry(symbol="NEW", sleeve="satellite", first_seen="2026-08-01", last_updated="2026-08-01",
                        confidence_pct=55.0, previous_confidence_pct=None, score=0.0, price=1.0, reason=""),
    ]
    kept = prune_expired_shortlist(entries, as_of="2026-08-05", max_age_days=30)
    assert [e.symbol for e in kept] == ["NEW"]  # OLD is 35 days old, past the 30-day window


def test_prune_expired_shortlist_keeps_entry_exactly_at_boundary():
    entries = [
        ShortlistEntry(symbol="EDGE", sleeve="satellite", first_seen="2026-07-06", last_updated="2026-07-06",
                        confidence_pct=55.0, previous_confidence_pct=None, score=0.0, price=1.0, reason=""),
    ]
    kept = prune_expired_shortlist(entries, as_of="2026-08-05", max_age_days=30)
    assert len(kept) == 1


def test_update_shortlist_adds_new_entry_in_middle_band():
    updated = update_shortlist(
        existing=[], confidence_by_symbol={"NVDA": 60.0}, score_by_symbol={"NVDA": 0.02},
        price_by_symbol={"NVDA": 200.0}, sleeve_by_symbol={"NVDA": "satellite"},
        execute_threshold_pct=70.0, shortlist_threshold_pct=50.0, as_of="2026-08-01",
    )
    assert len(updated) == 1
    assert updated[0].symbol == "NVDA"
    assert updated[0].confidence_pct == 60.0
    assert updated[0].previous_confidence_pct is None
    assert updated[0].first_seen == "2026-08-01"


def test_update_shortlist_rolls_previous_confidence_on_existing_entry():
    existing = [
        ShortlistEntry(symbol="NVDA", sleeve="satellite", first_seen="2026-08-01", last_updated="2026-08-01",
                        confidence_pct=55.0, previous_confidence_pct=None, score=0.01, price=195.0, reason="old"),
    ]
    updated = update_shortlist(
        existing=existing, confidence_by_symbol={"NVDA": 62.0}, score_by_symbol={"NVDA": 0.025},
        price_by_symbol={"NVDA": 205.0}, sleeve_by_symbol={"NVDA": "satellite"},
        execute_threshold_pct=70.0, shortlist_threshold_pct=50.0, as_of="2026-08-02",
    )
    assert updated[0].confidence_pct == 62.0
    assert updated[0].previous_confidence_pct == 55.0  # the delta the dashboard badge needs
    assert updated[0].first_seen == "2026-08-01"  # unchanged
    assert updated[0].last_updated == "2026-08-02"


def test_update_shortlist_removes_graduated_candidate():
    existing = [
        ShortlistEntry(symbol="NVDA", sleeve="satellite", first_seen="2026-08-01", last_updated="2026-08-01",
                        confidence_pct=65.0, previous_confidence_pct=None, score=0.03, price=200.0, reason="old"),
    ]
    updated = update_shortlist(
        existing=existing, confidence_by_symbol={"NVDA": 75.0}, score_by_symbol={"NVDA": 0.04},
        price_by_symbol={"NVDA": 210.0}, sleeve_by_symbol={"NVDA": "satellite"},
        execute_threshold_pct=70.0, shortlist_threshold_pct=50.0, as_of="2026-08-02",
    )
    assert updated == []  # graduated -- now a normal pending approval, not shortlisted


def test_update_shortlist_removes_dropped_candidate():
    existing = [
        ShortlistEntry(symbol="NVDA", sleeve="satellite", first_seen="2026-08-01", last_updated="2026-08-01",
                        confidence_pct=55.0, previous_confidence_pct=None, score=0.01, price=200.0, reason="old"),
    ]
    updated = update_shortlist(
        existing=existing, confidence_by_symbol={"NVDA": 40.0}, score_by_symbol={"NVDA": -0.02},
        price_by_symbol={"NVDA": 190.0}, sleeve_by_symbol={"NVDA": "satellite"},
        execute_threshold_pct=70.0, shortlist_threshold_pct=50.0, as_of="2026-08-02",
    )
    assert updated == []


def test_update_shortlist_leaves_unscored_symbol_untouched():
    existing = [
        ShortlistEntry(symbol="AMD", sleeve="satellite", first_seen="2026-08-01", last_updated="2026-08-01",
                        confidence_pct=58.0, previous_confidence_pct=None, score=0.015, price=150.0, reason="old"),
    ]
    # AMD wasn't scored this run (e.g. missing price history today)
    updated = update_shortlist(
        existing=existing, confidence_by_symbol={}, score_by_symbol={},
        price_by_symbol={}, sleeve_by_symbol={},
        execute_threshold_pct=70.0, shortlist_threshold_pct=50.0, as_of="2026-08-02",
    )
    assert len(updated) == 1
    assert updated[0].confidence_pct == 58.0  # untouched, not reset


def test_update_shortlist_sorts_by_confidence_descending():
    updated = update_shortlist(
        existing=[], confidence_by_symbol={"LOW": 51.0, "HIGH": 68.0},
        score_by_symbol={"LOW": 0.0, "HIGH": 0.03}, price_by_symbol={"LOW": 10.0, "HIGH": 20.0},
        sleeve_by_symbol={"LOW": "satellite", "HIGH": "satellite"},
        execute_threshold_pct=70.0, shortlist_threshold_pct=50.0, as_of="2026-08-01",
    )
    assert [e.symbol for e in updated] == ["HIGH", "LOW"]
