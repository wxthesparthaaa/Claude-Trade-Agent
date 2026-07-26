"""
Bridges Tiger's option chain API to the OptionContract dataclass used by
strategy.py. Split deliberately into two kinds of function:

  - fetch_* functions: the ONLY places that touch the network / Tiger SDK.
  - parse_option_chain_df: pure logic, converts a DataFrame into
    List[OptionContract]. Fully unit-testable with a synthetic DataFrame
    that mirrors Tiger's documented schema -- no network needed to test it.

IMPORTANT -- weekends/holidays: Tiger's API generally still returns data
when markets are closed, but it reflects the last trading session's
snapshot, not live quotes. Treat weekend/holiday runs as "does the pipeline
work end to end," not as real trade-ready pricing.

IMPORTANT -- permissions: fetch_option_chain requires an active options
market data permission (this is separate from the free historical options
quota shown in your Tiger dashboard). If you haven't purchased a real-time
US options data package yet, expect a permission error here -- that's
expected, not a bug, until that add-on is active.
"""

from datetime import date, datetime, timezone
from typing import List

import pandas as pd

from strategy import OptionContract


def fetch_expirations(quote_client, symbol: str, market=None) -> pd.DataFrame:
    """The only function that calls Tiger's option expirations endpoint."""
    from tigeropen.common.consts import Market
    if market is None:
        market = Market.US
    return quote_client.get_option_expirations(symbols=[symbol], market=market)


def fetch_option_chain(
    quote_client,
    symbol: str,
    expiry: str,
    delta_min: float,
    delta_max: float,
    open_interest_min: int,
    market=None,
) -> pd.DataFrame:
    """The only function that calls Tiger's option chain endpoint."""
    from tigeropen.common.consts import Market
    from tigeropen.quote.domain.filter import OptionFilter
    if market is None:
        market = Market.US
    option_filter = OptionFilter(
        delta_min=delta_min,
        delta_max=delta_max,
        open_interest_min=open_interest_min,
    )
    return quote_client.get_option_chain(
        symbol=symbol,
        expiry=expiry,
        option_filter=option_filter,
        return_greek_value=True,
        market=market,
    )


def parse_option_chain_df(df: pd.DataFrame, symbol: str) -> List[OptionContract]:
    """
    Pure logic -- no network. Converts a Tiger get_option_chain DataFrame
    into List[OptionContract]. Rows with missing bid/ask are skipped rather
    than treated as 0, since 0 would look like free premium to the strategy
    layer rather than "data unavailable."
    """
    contracts: List[OptionContract] = []

    for _, row in df.iterrows():
        expiry_ms = row["expiry"]
        expiry_date = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc).date()

        bid = row.get("bid_price")
        ask = row.get("ask_price")
        if bid is None or ask is None or pd.isna(bid) or pd.isna(ask):
            continue

        contracts.append(
            OptionContract(
                symbol=symbol,
                option_symbol=row["identifier"],
                strike=float(row["strike"]),
                expiry=expiry_date,
                put_call=row["put_call"],
                bid=float(bid),
                ask=float(ask),
                delta=float(row["delta"]),
                open_interest=int(row["open_interest"]),
                volume=int(row["volume"]),
                implied_volatility=float(row["implied_vol"]),
            )
        )
    return contracts


def get_option_contracts_for_expiry(
    quote_client,
    symbol: str,
    expiry: str,
    put_call: str,
    delta_min: float,
    delta_max: float,
    open_interest_min: int,
    market=None,
) -> List[OptionContract]:
    """
    Convenience wrapper: fetch + parse + filter to one side (PUT or CALL),
    since Tiger's chain endpoint returns both calls and puts together.
    """
    df = fetch_option_chain(
        quote_client, symbol, expiry, delta_min, delta_max, open_interest_min, market
    )
    contracts = parse_option_chain_df(df, symbol)
    return [c for c in contracts if c.put_call == put_call]
