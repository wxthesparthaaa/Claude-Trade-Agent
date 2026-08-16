"""
Run with:
    pytest tests/test_sector_suggestions.py -v
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sector_suggestions import (
    SectorSuggestion, build_suggestions, fetch_suggestions_for_sector,
    load_suggestions, save_suggestions, MAX_SUGGESTIONS,
)


# ---- build_suggestions -------------------------------------------------

def test_build_suggestions_intersects_membership_and_liquidity():
    result = build_suggestions(
        gics_sector_id="45", sector_name="Technology", market="US",
        sector_member_symbols=["AAPL", "MSFT", "OBSCURESYM"],
        liquid_mover_symbols=["AAPL", "MSFT", "OTHERSYM"],
        excluded_symbols=set(),
    )
    assert [s.symbol for s in result] == ["AAPL", "MSFT"]  # OBSCURESYM not liquid, OTHERSYM not in sector


def test_build_suggestions_excludes_already_covered_symbols():
    result = build_suggestions(
        gics_sector_id="45", sector_name="Technology", market="US",
        sector_member_symbols=["AAPL", "MSFT"], liquid_mover_symbols=["AAPL", "MSFT"],
        excluded_symbols={"AAPL"},
    )
    assert [s.symbol for s in result] == ["MSFT"]


def test_build_suggestions_caps_at_limit():
    symbols = [f"SYM{i}" for i in range(20)]
    result = build_suggestions(
        gics_sector_id="45", sector_name="Technology", market="US",
        sector_member_symbols=symbols, liquid_mover_symbols=symbols, excluded_symbols=set(),
    )
    assert len(result) == MAX_SUGGESTIONS


def test_build_suggestions_carries_sector_metadata_and_reason():
    result = build_suggestions(
        gics_sector_id="45", sector_name="Technology", market="US",
        sector_member_symbols=["AAPL"], liquid_mover_symbols=["AAPL"], excluded_symbols=set(),
        as_of="2026-08-16",
    )
    assert result[0] == SectorSuggestion(
        symbol="AAPL", market="US", sector_name="Technology", gics_sector_id="45",
        discovered_at="2026-08-16",
        reason="Technology is showing the strongest relative momentum right now; AAPL is a liquid name in it you don't currently track.",
    )


def test_build_suggestions_empty_when_no_overlap():
    result = build_suggestions(
        gics_sector_id="45", sector_name="Technology", market="US",
        sector_member_symbols=["AAPL"], liquid_mover_symbols=["MSFT"], excluded_symbols=set(),
    )
    assert result == []


# ---- fetch_suggestions_for_sector (orchestration) -------------------------------------------------

class _FakeMarket:
    def __init__(self, value):
        self.value = value


class _FakeQuoteClient:
    def __init__(self, industry_stocks, scanner_items):
        self._industry_stocks = industry_stocks
        self._scanner_items = scanner_items

    def get_industry_stocks(self, gics_sector_id, market=None):
        return self._industry_stocks

    def market_scanner(self, market=None, filters=None, sort_field_data=None, page=0, page_size=100, cursor_id=None):
        class _Result:
            items = self._scanner_items
        return _Result()


class _FakeScannerItem:
    def __init__(self, symbol):
        self.symbol = symbol


def test_fetch_suggestions_for_sector_end_to_end():
    client = _FakeQuoteClient(
        industry_stocks=[{"symbol": "AAPL"}, {"symbol": "MSFT"}, {"symbol": "RARE"}],
        scanner_items=[_FakeScannerItem("AAPL"), _FakeScannerItem("MSFT")],
    )

    result = fetch_suggestions_for_sector(
        client, gics_sector_id="45", sector_name="Technology", market=_FakeMarket("US"),
        excluded_symbols={"MSFT"},
    )

    assert [s.symbol for s in result] == ["AAPL"]
    assert result[0].market == "US"


# ---- load/save round trip -------------------------------------------------

def test_load_suggestions_empty_when_file_missing(tmp_path):
    assert load_suggestions(str(tmp_path / "does_not_exist.json")) == []


def test_save_then_load_suggestions_round_trips(tmp_path):
    path = str(tmp_path / "sector_suggestions.json")
    original = [SectorSuggestion(
        symbol="AAPL", market="US", sector_name="Technology", gics_sector_id="45",
        discovered_at="2026-08-16", reason="test reason",
    )]
    save_suggestions(path, original)
    assert load_suggestions(path) == original
