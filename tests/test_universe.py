"""
Run with:
    pytest tests/test_universe.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from universe import (
    DEFAULT_UNIVERSE, DIVIDEND_UNIVERSE, UniverseEntry, SYMBOL_NAMES,
    entries_for_sleeve, entries_for_market, display_name,
)


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


def test_display_name_returns_known_name():
    assert display_name("VOO") == "Vanguard S&P 500 ETF"


def test_display_name_falls_back_to_symbol_when_unknown():
    assert display_name("ZZZZ") == "ZZZZ"


def test_every_growth_universe_symbol_has_a_display_name():
    missing = [e.symbol for e in DEFAULT_UNIVERSE if e.symbol not in SYMBOL_NAMES]
    assert missing == [], f"missing SYMBOL_NAMES entries: {missing}"


def test_every_dividend_universe_symbol_has_a_display_name():
    missing = [e.symbol for e in DIVIDEND_UNIVERSE if e.symbol not in SYMBOL_NAMES]
    assert missing == [], f"missing SYMBOL_NAMES entries: {missing}"
