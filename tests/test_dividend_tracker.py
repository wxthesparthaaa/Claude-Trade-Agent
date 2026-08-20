"""
Run with:
    pytest tests/test_dividend_tracker.py -v
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trade_journal import JournalEntry
from dividend_tracker import (
    DividendPayment, DividendSummary, parse_corporate_dividend, fetch_dividend_events,
    compute_dividends_earned, refresh_dividends_earned, load_dividends_earned, save_dividends_earned,
)


class _FakeRow(dict):
    pass


class _FakeDataFrame:
    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def iterrows(self):
        return enumerate(self._rows)


# ---- parse_corporate_dividend -------------------------------------------------

def test_parse_corporate_dividend_extracts_dividend_rows_only():
    df = _FakeDataFrame([
        _FakeRow(symbol="VYM", action_type="DIVIDEND", amount=0.85, currency="USD",
                 execute_date="2026-06-15", pay_date="2026-06-20"),
        _FakeRow(symbol="VYM", action_type="SPLIT", amount=0.0, currency="USD",
                 execute_date="2026-06-15", pay_date=""),
    ])
    events = parse_corporate_dividend(df)
    assert events == [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                        "execute_date": "2026-06-15", "pay_date": "2026-06-20"}]


def test_parse_corporate_dividend_empty_when_none_or_empty():
    assert parse_corporate_dividend(None) == []
    assert parse_corporate_dividend(_FakeDataFrame([])) == []


# ---- fetch_dividend_events -------------------------------------------------

class _FakeQuoteClient:
    def __init__(self, df_by_market=None, raise_for=None):
        self._df_by_market = df_by_market or {}
        self._raise_for = raise_for or set()
        self.calls = []

    def get_corporate_dividend(self, symbols, market, begin_date, end_date):
        self.calls.append((tuple(symbols), market))
        if market in self._raise_for:
            raise RuntimeError("Tiger API error")
        return self._df_by_market.get(market)


def test_fetch_dividend_events_groups_by_symbol():
    from tigeropen.common.consts import Market
    df = _FakeDataFrame([
        _FakeRow(symbol="VYM", action_type="DIVIDEND", amount=0.85, currency="USD",
                 execute_date="2026-06-15", pay_date="2026-06-20"),
    ])
    client = _FakeQuoteClient(df_by_market={Market.US: df})
    events = fetch_dividend_events(client, {"US": ["VYM"]}, "2026-01-01", "2026-08-20")
    assert events == {"VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                                "execute_date": "2026-06-15", "pay_date": "2026-06-20"}]}


def test_fetch_dividend_events_one_market_failure_does_not_lose_others():
    from tigeropen.common.consts import Market
    df = _FakeDataFrame([
        _FakeRow(symbol="00002", action_type="DIVIDEND", amount=1.2, currency="HKD",
                 execute_date="2026-05-01", pay_date="2026-05-10"),
    ])
    client = _FakeQuoteClient(df_by_market={Market.HK: df}, raise_for={Market.SG})
    events = fetch_dividend_events(client, {"HK": ["00002"], "SG": ["C38U.SI"]}, "2026-01-01", "2026-08-20")
    assert "00002" in events
    assert "C38U.SI" not in events


def test_fetch_dividend_events_skips_unknown_market():
    client = _FakeQuoteClient()
    events = fetch_dividend_events(client, {"MOON": ["XYZ"]}, "2026-01-01", "2026-08-20")
    assert events == {}
    assert client.calls == []


# ---- compute_dividends_earned -------------------------------------------------

def _entry(symbol, quantity, opened_at, closed_at=None, position_type="long"):
    return JournalEntry(symbol=symbol, sleeve="core", position_type=position_type, quantity=quantity,
                         entry_price=100.0, confidence_pct=None, reason="", opened_at=opened_at,
                         status="CLOSED" if closed_at else "OPEN", closed_at=closed_at)


def test_compute_dividends_earned_multiplies_shares_by_amount():
    entries = [_entry("VYM", 10, opened_at="2026-01-01")]
    events = {"VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                        "execute_date": "2026-06-15", "pay_date": "2026-06-20"}]}
    summary = compute_dividends_earned(entries, events, year=2026)
    assert summary.total_by_currency == {"USD": 8.5}
    assert summary.payments[0].shares_held == 10
    assert summary.payments[0].total_amount == 8.5


def test_compute_dividends_earned_excludes_dividend_before_position_opened():
    entries = [_entry("VYM", 10, opened_at="2026-07-01")]  # opened AFTER the ex-date below
    events = {"VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                        "execute_date": "2026-06-15", "pay_date": "2026-06-20"}]}
    summary = compute_dividends_earned(entries, events, year=2026)
    assert summary.payments == []


def test_compute_dividends_earned_excludes_dividend_after_position_closed():
    entries = [_entry("VYM", 10, opened_at="2026-01-01", closed_at="2026-05-01")]
    events = {"VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                        "execute_date": "2026-06-15", "pay_date": "2026-06-20"}]}
    summary = compute_dividends_earned(entries, events, year=2026)
    assert summary.payments == []


def test_compute_dividends_earned_includes_dividend_while_position_was_open():
    entries = [_entry("VYM", 10, opened_at="2026-01-01", closed_at="2026-08-01")]
    events = {"VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                        "execute_date": "2026-06-15", "pay_date": "2026-06-20"}]}
    summary = compute_dividends_earned(entries, events, year=2026)
    assert len(summary.payments) == 1


def test_compute_dividends_earned_excludes_wrong_year():
    entries = [_entry("VYM", 10, opened_at="2025-01-01")]
    events = {"VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                        "execute_date": "2025-06-15", "pay_date": "2025-06-20"}]}
    summary = compute_dividends_earned(entries, events, year=2026)
    assert summary.payments == []


def test_compute_dividends_earned_skips_short_positions():
    entries = [_entry("VYM", 10, opened_at="2026-01-01", position_type="short")]
    events = {"VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD",
                        "execute_date": "2026-06-15", "pay_date": "2026-06-20"}]}
    summary = compute_dividends_earned(entries, events, year=2026)
    assert summary.payments == []


def test_compute_dividends_earned_sums_multiple_currencies_separately():
    entries = [_entry("VYM", 10, opened_at="2026-01-01"), _entry("00002", 100, opened_at="2026-01-01")]
    events = {
        "VYM": [{"symbol": "VYM", "amount": 0.85, "currency": "USD", "execute_date": "2026-06-15", "pay_date": ""}],
        "00002": [{"symbol": "00002", "amount": 1.2, "currency": "HKD", "execute_date": "2026-05-01", "pay_date": ""}],
    }
    summary = compute_dividends_earned(entries, events, year=2026)
    assert summary.total_by_currency == {"USD": 8.5, "HKD": 120.0}


def test_compute_dividends_earned_note_when_no_payments():
    summary = compute_dividends_earned([], {}, year=2026)
    assert summary.payments == []
    assert summary.note != ""


def test_compute_dividends_earned_sorts_payments_by_ex_date():
    entries = [_entry("VYM", 10, opened_at="2026-01-01")]
    events = {"VYM": [
        {"symbol": "VYM", "amount": 0.85, "currency": "USD", "execute_date": "2026-06-15", "pay_date": ""},
        {"symbol": "VYM", "amount": 0.80, "currency": "USD", "execute_date": "2026-03-15", "pay_date": ""},
    ]}
    summary = compute_dividends_earned(entries, events, year=2026)
    assert [p.ex_date for p in summary.payments] == ["2026-03-15", "2026-06-15"]


# ---- refresh_dividends_earned -------------------------------------------------

def test_refresh_dividends_earned_returns_note_when_no_long_positions():
    summary = refresh_dividends_earned(_FakeQuoteClient(), [], market_by_symbol={})
    assert summary.payments == []
    assert "No long positions" in summary.note


def test_refresh_dividends_earned_defaults_missing_market_to_us():
    from tigeropen.common.consts import Market
    entries = [_entry("VYM", 10, opened_at="2026-01-01")]
    df = _FakeDataFrame([
        _FakeRow(symbol="VYM", action_type="DIVIDEND", amount=0.85, currency="USD",
                 execute_date="2026-06-15", pay_date=""),
    ])
    client = _FakeQuoteClient(df_by_market={Market.US: df})
    summary = refresh_dividends_earned(client, entries, market_by_symbol={}, year=2026)
    assert summary.total_by_currency == {"USD": 8.5}


# ---- load/save round trip -------------------------------------------------

def test_load_dividends_earned_none_when_file_missing(tmp_path):
    assert load_dividends_earned(str(tmp_path / "does_not_exist.json")) is None


def test_save_then_load_dividends_earned_round_trips(tmp_path):
    path = str(tmp_path / "dividends_earned.json")
    original = DividendSummary(
        as_of="2026-08-20", year=2026, total_by_currency={"USD": 8.5},
        payments=[DividendPayment(symbol="VYM", amount_per_share=0.85, shares_held=10, total_amount=8.5,
                                   currency="USD", ex_date="2026-06-15", pay_date="2026-06-20")],
    )
    save_dividends_earned(path, original)
    assert load_dividends_earned(path) == original
