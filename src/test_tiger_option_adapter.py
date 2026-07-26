"""
Run with:
    pytest tests/test_tiger_option_adapter.py -v

Only tests parse_option_chain_df -- the pure logic half of the adapter.
The fetch_* functions require a real Tiger connection and are exercised
manually via scripts/fetch_live_chain.py instead, since network calls
don't belong in an automated unit test.
"""
import sys
import os
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
from tiger_option_adapter import parse_option_chain_df


def expiry_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def synthetic_chain_df(rows):
    return pd.DataFrame(rows)


def test_parses_valid_rows():
    exp = date(2026, 8, 7)
    df = synthetic_chain_df([
        {
            "symbol": "AAPL", "expiry": expiry_ms(exp), "identifier": "AAPL 260807P00185000",
            "strike": 185.0, "put_call": "PUT", "volume": 120, "latest_price": 1.25,
            "pre_close": 1.30, "open_interest": 340, "multiplier": 100,
            "implied_vol": 0.32, "delta": -0.22, "gamma": 0.01, "theta": -0.03,
            "vega": 0.05, "rho": 0.01, "bid_price": 1.20, "ask_price": 1.30,
        }
    ])
    contracts = parse_option_chain_df(df, "AAPL")
    assert len(contracts) == 1
    c = contracts[0]
    assert c.symbol == "AAPL"
    assert c.strike == 185.0
    assert c.put_call == "PUT"
    assert c.bid == 1.20
    assert c.ask == 1.30
    assert c.delta == -0.22
    assert c.open_interest == 340
    assert c.volume == 120
    assert c.expiry == exp


def test_skips_rows_with_missing_bid_ask():
    exp = date(2026, 8, 7)
    df = synthetic_chain_df([
        {
            "symbol": "AAPL", "expiry": expiry_ms(exp), "identifier": "AAPL 260807P00185000",
            "strike": 185.0, "put_call": "PUT", "volume": 0, "latest_price": 0.0,
            "pre_close": 1.30, "open_interest": 340, "multiplier": 100,
            "implied_vol": 0.32, "delta": -0.22, "gamma": 0.01, "theta": -0.03,
            "vega": 0.05, "rho": 0.01, "bid_price": None, "ask_price": None,
        },
        {
            "symbol": "AAPL", "expiry": expiry_ms(exp), "identifier": "AAPL 260807P00180000",
            "strike": 180.0, "put_call": "PUT", "volume": 50, "latest_price": 0.9,
            "pre_close": 0.95, "open_interest": 200, "multiplier": 100,
            "implied_vol": 0.30, "delta": -0.18, "gamma": 0.01, "theta": -0.02,
            "vega": 0.04, "rho": 0.01, "bid_price": 0.85, "ask_price": 0.95,
        },
    ])
    contracts = parse_option_chain_df(df, "AAPL")
    assert len(contracts) == 1
    assert contracts[0].strike == 180.0


def test_empty_dataframe_returns_empty_list():
    df = synthetic_chain_df([])
    contracts = parse_option_chain_df(df, "AAPL")
    assert contracts == []


def test_parsed_contracts_feed_directly_into_strategy_layer():
    """Integration check: adapter output is a valid input to generate_candidates."""
    from strategy import StrategyConfig, generate_candidates

    exp = date(2026, 8, 7)
    df = synthetic_chain_df([
        {
            "symbol": "AAPL", "expiry": expiry_ms(exp), "identifier": "AAPL 260807P00185000",
            "strike": 185.0, "put_call": "PUT", "volume": 120, "latest_price": 1.25,
            "pre_close": 1.30, "open_interest": 340, "multiplier": 100,
            "implied_vol": 0.32, "delta": -0.22, "gamma": 0.01, "theta": -0.03,
            "vega": 0.05, "rho": 0.01, "bid_price": 1.20, "ask_price": 1.30,
        }
    ])
    contracts = parse_option_chain_df(df, "AAPL")
    candidates = generate_candidates(
        contracts, "cash_secured_put", StrategyConfig(min_dte=1, max_dte=30), as_of=date(2026, 7, 31)
    )
    assert len(candidates) == 1
    assert candidates[0].symbol == "AAPL"
