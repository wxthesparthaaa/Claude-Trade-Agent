"""
Run with:
    pytest tests/test_tiger_dividend_adapter.py -v
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
from tiger_dividend_adapter import parse_dividend_df


def test_parses_valid_rows_grouped_by_symbol():
    df = pd.DataFrame([
        {"symbol": "SCHD", "amount": 0.68, "currency": "USD",
         "announced_date": "2026-05-01", "execute_date": "2026-06-15", "record_date": "2026-06-16", "pay_date": "2026-06-30"},
        {"symbol": "SCHD", "amount": 0.70, "currency": "USD",
         "announced_date": "2026-02-01", "execute_date": "2026-03-15", "record_date": "2026-03-16", "pay_date": "2026-03-30"},
        {"symbol": "D05", "amount": 0.54, "currency": "SGD",
         "announced_date": "2026-04-01", "execute_date": "2026-05-10", "record_date": "2026-05-11", "pay_date": "2026-05-30"},
    ])
    result = parse_dividend_df(df)
    assert set(result.keys()) == {"SCHD", "D05"}
    assert result["SCHD"] == [(date(2026, 3, 15), 0.70), (date(2026, 6, 15), 0.68)]
    assert result["D05"] == [(date(2026, 5, 10), 0.54)]


def test_empty_dataframe_returns_empty_dict():
    assert parse_dividend_df(pd.DataFrame()) == {}


def test_none_returns_empty_dict():
    assert parse_dividend_df(None) == {}
