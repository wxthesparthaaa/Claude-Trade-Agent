"""
Run with:
    pytest tests/test_movers.py -v
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from movers import (
    MoverEntry, MoversSignal, parse_trade_rank, rank_movers, refresh_movers,
    load_movers, save_movers,
)


class _FakeRow(dict):
    """A dict that also supports pandas Series-style .get()."""
    pass


class _FakeDataFrame:
    """Minimal stand-in for a pandas DataFrame -- only what parse_trade_rank uses."""
    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def iterrows(self):
        return enumerate(self._rows)


# ---- parse_trade_rank -------------------------------------------------

def test_parse_trade_rank_extracts_fields_in_order():
    df = _FakeDataFrame([
        _FakeRow(symbol="NVDA", name="NVIDIA", change_rate=-0.02),
        _FakeRow(symbol="AMD", name="Advanced Micro Devices", change_rate=-0.06),
    ])
    entries = parse_trade_rank(df)
    assert entries == [
        MoverEntry(symbol="NVDA", name="NVIDIA", change_rate=-0.02, rank=1),
        MoverEntry(symbol="AMD", name="Advanced Micro Devices", change_rate=-0.06, rank=2),
    ]


def test_parse_trade_rank_falls_back_to_symbol_when_name_missing():
    df = _FakeDataFrame([_FakeRow(symbol="NVDA", change_rate=0.01)])
    entries = parse_trade_rank(df)
    assert entries[0].name == "NVDA"


def test_parse_trade_rank_empty_when_none_or_empty():
    assert parse_trade_rank(None) == []
    assert parse_trade_rank(_FakeDataFrame([])) == []


# ---- rank_movers -------------------------------------------------

class _FakeQuoteClient:
    def __init__(self, df=None, raise_error=False):
        self._df = df
        self._raise_error = raise_error

    def get_trade_rank(self, market):
        if self._raise_error:
            raise RuntimeError("Tiger API error")
        return self._df


def test_rank_movers_returns_unavailable_for_sg_without_calling_tiger():
    calls = []

    class TrackedClient:
        def get_trade_rank(self, market):
            calls.append(market)
            raise AssertionError("must not call Tiger for SG")

    signal = rank_movers(TrackedClient(), "SG")
    assert signal.region == "SG"
    assert signal.entries == []
    assert "isn't available for SG" in signal.note
    assert calls == []


def test_rank_movers_works_for_us():
    df = _FakeDataFrame([_FakeRow(symbol="NVDA", name="NVIDIA", change_rate=0.05)])
    signal = rank_movers(_FakeQuoteClient(df=df), "US")
    assert signal.region == "US"
    assert signal.entries[0].symbol == "NVDA"
    assert signal.note == ""


def test_rank_movers_swallows_errors_and_returns_empty():
    signal = rank_movers(_FakeQuoteClient(raise_error=True), "US")
    assert signal.entries == []
    assert signal.note != ""


# ---- refresh_movers -------------------------------------------------

def test_refresh_movers_covers_all_three_regions():
    df = _FakeDataFrame([_FakeRow(symbol="NVDA", name="NVIDIA", change_rate=0.05)])
    result = refresh_movers(_FakeQuoteClient(df=df))
    assert set(result.keys()) == {"US", "HK", "SG"}
    assert result["SG"].entries == []


# ---- load/save round trip -------------------------------------------------

def test_load_movers_empty_when_file_missing(tmp_path):
    assert load_movers(str(tmp_path / "does_not_exist.json")) == {}


def test_save_then_load_movers_round_trips(tmp_path):
    path = str(tmp_path / "movers.json")
    original = {
        "US": MoversSignal(as_of="2026-08-19", region="US", entries=[
            MoverEntry(symbol="NVDA", name="NVIDIA", change_rate=-0.02, rank=1),
        ]),
        "SG": MoversSignal(as_of="2026-08-19", region="SG", entries=[], note="unavailable"),
    }
    save_movers(path, original)
    assert load_movers(path) == original


def test_load_movers_defaults_entries_when_missing_from_old_file(tmp_path):
    import json
    path = str(tmp_path / "movers.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"US": {"as_of": "2026-08-19", "region": "US", "note": ""}}, f)
    loaded = load_movers(path)
    assert loaded["US"].entries == []
