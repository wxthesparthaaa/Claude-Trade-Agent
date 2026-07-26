"""
Fetches historical stock price bars from Tiger (free, under the Historical
- Stocks/ETF quota) and converts them into the plain (date, close) tuples
that backtest.py consumes. Same split as the option chain adapter:
fetch_* touches the network, parse_* is pure and unit-testable offline.
"""
from datetime import date, datetime, timezone
from typing import List, Tuple

import pandas as pd


def fetch_stock_bars(quote_client, symbol: str, limit: int = 250):
    """
    The only function that calls Tiger's historical bars endpoint.
    limit=250 trading days is roughly one year -- enough for a meaningful
    weekly backtest with the default 20-day volatility window.
    """
    from tigeropen.common.consts import BarPeriod
    return quote_client.get_bars([symbol], period=BarPeriod.DAY, limit=limit)


def parse_stock_bars_df(df: pd.DataFrame) -> List[Tuple[date, float]]:
    """
    Pure logic -- no network. Converts Tiger's get_bars DataFrame into a
    chronologically sorted list of (date, close) tuples.
    """
    if df is None or len(df) == 0:
        return []

    time_col = "time" if "time" in df.columns else "date"
    rows = []
    for _, row in df.iterrows():
        raw_time = row[time_col]
        if isinstance(raw_time, (int, float)):
            d = datetime.fromtimestamp(raw_time / 1000, tz=timezone.utc).date()
        else:
            d = pd.to_datetime(raw_time).date()
        rows.append((d, float(row["close"])))

    rows.sort(key=lambda r: r[0])
    return rows
