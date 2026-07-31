"""
Fetches board-lot size and tick-size metadata from Tiger, used to filter out
HK/SG stocks whose minimum tradable lot doesn't actually fit a $1,000
account. Same fetch/parse split as the other Tiger adapters.
"""
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

DEFAULT_LOT_SIZE = 1  # matches US behavior (board lots of 1 share)


@dataclass
class LotInfo:
    lot_size: int
    min_tick: float


def fetch_trade_metas(quote_client, symbols: List[str]):
    """The only function that calls Tiger's trade-meta endpoint."""
    return quote_client.get_trade_metas(symbols)


def parse_trade_metas_df(df: pd.DataFrame) -> Dict[str, LotInfo]:
    """
    Pure logic -- no network. Converts Tiger's get_trade_metas DataFrame
    into {symbol: LotInfo}. Symbols not covered by this lookup should be
    treated by the caller as DEFAULT_LOT_SIZE (US-style, 1 share per lot).
    """
    if df is None or len(df) == 0:
        return {}

    result: Dict[str, LotInfo] = {}
    for _, row in df.iterrows():
        symbol = row["symbol"]
        lot_size = int(row["lot_size"]) if not pd.isna(row["lot_size"]) else DEFAULT_LOT_SIZE
        min_tick = float(row["min_tick"]) if not pd.isna(row["min_tick"]) else 0.01
        result[symbol] = LotInfo(lot_size=lot_size, min_tick=min_tick)

    return result
