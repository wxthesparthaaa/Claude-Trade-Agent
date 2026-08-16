"""
Run with:
    pytest tests/test_tiger_industry_adapter.py -v
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_industry_adapter import (
    SectorTag, parse_gics_sector_id, parse_industry_stocks, parse_liquid_movers,
    get_gics_sector_id, get_gics_sector_id_cached, load_sector_tags, save_sector_tags,
    GICS_CACHE_MAX_AGE_DAYS,
)


# ---- parse_gics_sector_id -------------------------------------------------

def test_parse_gics_sector_id_returns_top_level_gsector():
    raw = [
        {"industry_level": "GSECTOR", "id": "45", "name_en": "Information Technology"},
        {"industry_level": "GGROUP", "id": "4520", "name_en": "Technology Hardware & Equipment"},
        {"industry_level": "GIND", "id": "452020", "name_en": "Technology Hardware, Storage & Peripherals"},
    ]
    assert parse_gics_sector_id(raw) == "45"


def test_parse_gics_sector_id_none_when_no_gsector_entry():
    assert parse_gics_sector_id([{"industry_level": "GGROUP", "id": "4520"}]) is None


def test_parse_gics_sector_id_none_when_empty_or_none():
    assert parse_gics_sector_id([]) is None
    assert parse_gics_sector_id(None) is None


# ---- parse_industry_stocks -------------------------------------------------

def test_parse_industry_stocks_extracts_symbols():
    raw = [
        {"symbol": "AAPL", "company_name": "Apple", "market": "US"},
        {"symbol": "MSFT", "company_name": "Microsoft", "market": "US"},
    ]
    assert parse_industry_stocks(raw) == ["AAPL", "MSFT"]


def test_parse_industry_stocks_skips_entries_without_symbol():
    assert parse_industry_stocks([{"company_name": "no symbol here"}]) == []


def test_parse_industry_stocks_empty_when_none():
    assert parse_industry_stocks(None) == []


# ---- parse_liquid_movers -------------------------------------------------

class _FakeScannerItem:
    def __init__(self, symbol):
        self.symbol = symbol


def test_parse_liquid_movers_extracts_symbols():
    items = [_FakeScannerItem("NTNX"), _FakeScannerItem("U")]
    assert parse_liquid_movers(items) == ["NTNX", "U"]


def test_parse_liquid_movers_empty_when_none():
    assert parse_liquid_movers(None) == []


# ---- get_gics_sector_id -------------------------------------------------

class _FakeQuoteClient:
    def __init__(self, industry_by_symbol=None, raise_for=None):
        self.industry_by_symbol = industry_by_symbol or {}
        self.raise_for = raise_for or set()
        self.calls = []

    def get_stock_industry(self, symbol, market=None, sec_type=None):
        self.calls.append(symbol)
        if symbol in self.raise_for:
            raise RuntimeError("Tiger API error")
        return self.industry_by_symbol.get(symbol, [])


def test_get_gics_sector_id_returns_none_for_sg_without_calling_tiger():
    """SG is a confirmed, permanent API gap -- must not even attempt the call."""
    client = _FakeQuoteClient()
    assert get_gics_sector_id(client, "D05.SI", "SG") is None
    assert client.calls == []


def test_get_gics_sector_id_works_for_us():
    client = _FakeQuoteClient(industry_by_symbol={
        "AAPL": [{"industry_level": "GSECTOR", "id": "45"}],
    })
    assert get_gics_sector_id(client, "AAPL", "US") == "45"


def test_get_gics_sector_id_works_for_hk():
    client = _FakeQuoteClient(industry_by_symbol={
        "00700": [{"industry_level": "GSECTOR", "id": "50"}],
    })
    assert get_gics_sector_id(client, "00700", "HK") == "50"


def test_get_gics_sector_id_swallows_errors_and_returns_none():
    client = _FakeQuoteClient(raise_for={"BADSYM"})
    assert get_gics_sector_id(client, "BADSYM", "US") is None


# ---- sector-tag cache -------------------------------------------------

def test_load_sector_tags_empty_when_file_missing(tmp_path):
    assert load_sector_tags(str(tmp_path / "does_not_exist.json")) == {}


def test_save_then_load_sector_tags_round_trips(tmp_path):
    path = str(tmp_path / "sector_tags.json")
    original = {
        "AAPL": SectorTag(symbol="AAPL", gics_sector_id="45", looked_up_at="2026-08-01"),
        "SPY": SectorTag(symbol="SPY", gics_sector_id=None, looked_up_at="2026-08-01"),
    }
    save_sector_tags(path, original)
    loaded = load_sector_tags(path)
    assert loaded == original


def test_get_gics_sector_id_cached_uses_cache_within_max_age():
    client = _FakeQuoteClient(industry_by_symbol={"AAPL": [{"industry_level": "GSECTOR", "id": "45"}]})
    cache = {"AAPL": SectorTag(symbol="AAPL", gics_sector_id="99", looked_up_at=date.today().isoformat())}

    result = get_gics_sector_id_cached(client, "AAPL", "US", cache)

    assert result == "99"  # stale cached value returned, not re-fetched
    assert client.calls == []


def test_get_gics_sector_id_cached_refreshes_when_stale():
    client = _FakeQuoteClient(industry_by_symbol={"AAPL": [{"industry_level": "GSECTOR", "id": "45"}]})
    old_date = (date.today() - timedelta(days=GICS_CACHE_MAX_AGE_DAYS + 1)).isoformat()
    cache = {"AAPL": SectorTag(symbol="AAPL", gics_sector_id="99", looked_up_at=old_date)}

    result = get_gics_sector_id_cached(client, "AAPL", "US", cache)

    assert result == "45"  # re-fetched, cache updated
    assert client.calls == ["AAPL"]
    assert cache["AAPL"].gics_sector_id == "45"
    assert cache["AAPL"].looked_up_at == date.today().isoformat()


def test_get_gics_sector_id_cached_fetches_when_symbol_not_in_cache():
    client = _FakeQuoteClient(industry_by_symbol={"MSFT": [{"industry_level": "GSECTOR", "id": "45"}]})
    cache = {}

    result = get_gics_sector_id_cached(client, "MSFT", "US", cache)

    assert result == "45"
    assert "MSFT" in cache
