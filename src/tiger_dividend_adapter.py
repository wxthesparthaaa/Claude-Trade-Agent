"""
Fetches corporate dividend history from Tiger and converts it into plain
per-symbol (date, amount) lists, following the same fetch/parse split as
tiger_stock_bars_adapter.py: fetch_* touches the network, parse_* is pure
and unit-testable offline.
"""
from datetime import date
from typing import Dict, List, Tuple

import pandas as pd


def fetch_corporate_dividends(quote_client, symbols: List[str], market: str, begin_date: str, end_date: str):
    """
    The only function that calls Tiger's corporate dividend endpoint.
    market is a tigeropen.common.consts.Market value (e.g. Market.US);
    begin_date/end_date are "YYYY-MM-DD" strings.
    """
    return quote_client.get_corporate_dividend(
        symbols, market=market, begin_date=begin_date, end_date=end_date
    )


def parse_dividend_df(df: pd.DataFrame) -> Dict[str, List[Tuple[date, float]]]:
    """
    Pure logic -- no network. Converts Tiger's get_corporate_dividend
    DataFrame into {symbol: [(execute_date, amount_per_share), ...]},
    chronologically sorted per symbol. Uses execute_date (the date the
    dividend actually affects the share price) rather than announced_date.
    """
    if df is None or len(df) == 0:
        return {}

    result: Dict[str, List[Tuple[date, float]]] = {}
    for _, row in df.iterrows():
        symbol = row["symbol"]
        raw_date = row["execute_date"]
        d = pd.to_datetime(raw_date).date()
        amount = float(row["amount"])
        result.setdefault(symbol, []).append((d, amount))

    for symbol in result:
        result[symbol].sort(key=lambda r: r[0])

    return result
