"""
Run with:
    pytest tests/test_sec_edgar_adapter.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sec_edgar_adapter import (
    parse_ticker_cik_map, parse_annual_diluted_eps, get_annual_eps,
)


def test_parse_ticker_cik_map_upper_cases_ticker_and_zero_pads_cik():
    raw = {"0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."}}
    assert parse_ticker_cik_map(raw) == {"AAPL": "0000320193"}


def test_parse_ticker_cik_map_returns_empty_dict_for_none():
    assert parse_ticker_cik_map(None) == {}


def test_parse_annual_diluted_eps_picks_most_recent_10k_fy_value():
    raw = {
        "units": {
            "USD/shares": [
                {"form": "10-K", "fp": "FY", "end": "2024-09-27", "val": 6.13},
                {"form": "10-K", "fp": "FY", "end": "2025-09-27", "val": 7.46},
                # Quarterly facts must be ignored even if more recent.
                {"form": "10-Q", "fp": "Q3", "end": "2026-06-27", "val": 2.02},
            ]
        }
    }
    assert parse_annual_diluted_eps(raw) == 7.46


def test_parse_annual_diluted_eps_returns_none_when_no_annual_fact_exists():
    raw = {"units": {"USD/shares": [{"form": "10-Q", "fp": "Q3", "end": "2026-06-27", "val": 2.02}]}}
    assert parse_annual_diluted_eps(raw) is None


def test_parse_annual_diluted_eps_returns_none_for_missing_data():
    assert parse_annual_diluted_eps(None) is None
    assert parse_annual_diluted_eps({}) is None


def test_get_annual_eps_returns_none_for_symbol_not_in_cik_map():
    assert get_annual_eps("00700", {"AAPL": "0000320193"}) is None


def test_get_annual_eps_looks_up_cik_and_fetches_facts(monkeypatch):
    import sec_edgar_adapter

    seen_ciks = []

    def fake_fetch(cik):
        seen_ciks.append(cik)
        return {"units": {"USD/shares": [{"form": "10-K", "fp": "FY", "end": "2025-09-27", "val": 7.46}]}}

    monkeypatch.setattr(sec_edgar_adapter, "fetch_diluted_eps_facts", fake_fetch)
    eps = get_annual_eps("aapl", {"AAPL": "0000320193"})
    assert eps == 7.46
    assert seen_ciks == ["0000320193"]
