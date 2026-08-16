"""
Run with:
    pytest tests/test_fred_adapter.py -v
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fred_adapter import parse_fred_csv


def test_parse_fred_csv_basic():
    csv_text = "observation_date,T10YIE\n2026-01-02,2.31\n2026-01-03,2.33\n"
    result = parse_fred_csv(csv_text)
    assert result == [(date(2026, 1, 2), 2.31), (date(2026, 1, 3), 2.33)]


def test_parse_fred_csv_skips_missing_empty_value():
    csv_text = "observation_date,T10YIE\n2026-01-02,2.31\n2026-01-20,\n2026-01-21,2.35\n"
    result = parse_fred_csv(csv_text)
    assert result == [(date(2026, 1, 2), 2.31), (date(2026, 1, 21), 2.35)]


def test_parse_fred_csv_skips_dot_placeholder():
    """Not the confirmed-live format, but tolerated in case FRED ever
    uses "." for a different series -- same defensive posture."""
    csv_text = "observation_date,INDPRO\n2026-01-01,102.5\n2026-02-01,.\n"
    result = parse_fred_csv(csv_text)
    assert result == [(date(2026, 1, 1), 102.5)]


def test_parse_fred_csv_returns_chronologically_sorted():
    csv_text = "observation_date,X\n2026-02-01,2.0\n2026-01-01,1.0\n"
    result = parse_fred_csv(csv_text)
    assert result == [(date(2026, 1, 1), 1.0), (date(2026, 2, 1), 2.0)]


def test_parse_fred_csv_empty_when_only_header():
    assert parse_fred_csv("observation_date,X\n") == []


def test_parse_fred_csv_empty_string():
    assert parse_fred_csv("") == []


def test_parse_fred_csv_skips_malformed_date():
    csv_text = "observation_date,X\nnot-a-date,1.0\n2026-01-01,2.0\n"
    result = parse_fred_csv(csv_text)
    assert result == [(date(2026, 1, 1), 2.0)]
