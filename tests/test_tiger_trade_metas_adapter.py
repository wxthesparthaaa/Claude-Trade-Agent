"""
Run with:
    pytest tests/test_tiger_trade_metas_adapter.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
from tiger_trade_metas_adapter import parse_trade_metas_df, LotInfo, DEFAULT_LOT_SIZE


def test_parses_valid_rows():
    df = pd.DataFrame([
        {"symbol": "00700", "lot_size": 100, "min_tick": 0.2, "spread_scale": 1},
        {"symbol": "VOO", "lot_size": 1, "min_tick": 0.01, "spread_scale": 1},
    ])
    result = parse_trade_metas_df(df)
    assert result["00700"] == LotInfo(lot_size=100, min_tick=0.2)
    assert result["VOO"] == LotInfo(lot_size=1, min_tick=0.01)


def test_missing_lot_size_defaults():
    df = pd.DataFrame([{"symbol": "X", "lot_size": float("nan"), "min_tick": float("nan"), "spread_scale": 1}])
    result = parse_trade_metas_df(df)
    assert result["X"].lot_size == DEFAULT_LOT_SIZE
    assert result["X"].min_tick == 0.01


def test_empty_dataframe_returns_empty_dict():
    assert parse_trade_metas_df(pd.DataFrame()) == {}


def test_none_returns_empty_dict():
    assert parse_trade_metas_df(None) == {}
