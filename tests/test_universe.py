"""
Run with:
    pytest tests/test_universe.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from universe import DEFAULT_UNIVERSE, UniverseEntry, entries_for_sleeve, entries_for_market


def test_default_universe_is_nonempty():
    assert len(DEFAULT_UNIVERSE) > 0


def test_default_universe_covers_all_three_markets():
    markets = {e.market for e in DEFAULT_UNIVERSE}
    assert markets == {"US", "HK", "SG"}


def test_default_universe_has_both_sleeves():
    sleeves = {e.sleeve for e in DEFAULT_UNIVERSE}
    assert sleeves == {"core", "satellite"}


def test_entries_for_sleeve_filters_correctly():
    universe = [
        UniverseEntry("A", "US", "USD", "", "core"),
        UniverseEntry("B", "US", "USD", "", "satellite"),
    ]
    result = entries_for_sleeve("core", universe)
    assert [e.symbol for e in result] == ["A"]


def test_entries_for_market_filters_correctly():
    universe = [
        UniverseEntry("A", "US", "USD", "", "core"),
        UniverseEntry("B", "HK", "HKD", "SEHK", "satellite"),
    ]
    result = entries_for_market("HK", universe)
    assert [e.symbol for e in result] == ["B"]


def test_non_us_entries_have_exchange_metadata():
    for entry in DEFAULT_UNIVERSE:
        if entry.market != "US":
            assert entry.exchange, f"{entry.symbol} ({entry.market}) is missing an exchange"
            assert entry.currency != "USD", f"{entry.symbol} ({entry.market}) should not be USD"
