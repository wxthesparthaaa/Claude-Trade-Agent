"""
Run with:
    pytest tests/test_universe_extra.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from universe_extra import ExtraUniverseEntry, load_extra_universe, save_extra_universe, add_entry, remove_entry


def test_load_extra_universe_empty_when_file_missing(tmp_path):
    assert load_extra_universe(str(tmp_path / "does_not_exist.json")) == []


def test_save_then_load_extra_universe_round_trips(tmp_path):
    path = str(tmp_path / "extra_universe.json")
    original = [
        ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite",
                            added_at="2026-08-16", source_sector="Financials"),
    ]
    save_extra_universe(path, original)
    assert load_extra_universe(path) == original


def test_add_entry_appends_to_an_empty_file(tmp_path):
    path = str(tmp_path / "extra_universe.json")
    entry = ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite", added_at="2026-08-16")
    result = add_entry(path, entry)
    assert result == [entry]
    assert load_extra_universe(path) == [entry]


def test_add_entry_replaces_an_existing_entry_for_the_same_symbol(tmp_path):
    path = str(tmp_path / "extra_universe.json")
    old = ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite",
                              added_at="2026-08-01", source_sector="Financials")
    save_extra_universe(path, [old])

    new = ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="core",
                              added_at="2026-08-16", source_sector="Financials")
    result = add_entry(path, new)

    assert result == [new]  # not duplicated, replaced


def test_add_entry_preserves_other_existing_entries(tmp_path):
    path = str(tmp_path / "extra_universe.json")
    existing = ExtraUniverseEntry(symbol="XOM", market="US", currency="USD", exchange="", sleeve="core", added_at="2026-08-01")
    save_extra_universe(path, [existing])

    new = ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite", added_at="2026-08-16")
    result = add_entry(path, new)

    assert existing in result
    assert new in result
    assert len(result) == 2


def test_remove_entry_drops_the_matching_symbol(tmp_path):
    path = str(tmp_path / "extra_universe.json")
    keep = ExtraUniverseEntry(symbol="XOM", market="US", currency="USD", exchange="", sleeve="core", added_at="2026-08-01")
    drop = ExtraUniverseEntry(symbol="JPM", market="US", currency="USD", exchange="", sleeve="satellite", added_at="2026-08-16")
    save_extra_universe(path, [keep, drop])

    result = remove_entry(path, "JPM")

    assert result == [keep]
    assert load_extra_universe(path) == [keep]


def test_remove_entry_no_op_when_symbol_not_present(tmp_path):
    path = str(tmp_path / "extra_universe.json")
    keep = ExtraUniverseEntry(symbol="XOM", market="US", currency="USD", exchange="", sleeve="core", added_at="2026-08-01")
    save_extra_universe(path, [keep])

    result = remove_entry(path, "NOT_THERE")

    assert result == [keep]
