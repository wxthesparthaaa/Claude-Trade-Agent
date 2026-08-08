"""
RSP/SPY market-breadth signal: equal-weight S&P 500 divided by cap-weight
S&P 500. Rising = the average stock is starting to beat the mega-caps
("broadening"); falling = the opposite ("narrowing"). The user's stated
rule -- "always stick with the wave, get ready to turn at the edges" --
is implemented as two deliberately quantitative pieces, not visual/
candlestick pattern-recognition (consistent with every other signal in
this codebase; see stock_signal.py's docstring on "two hard numeric
factors... not a multi-factor black box"):

  - trend ("stick with the wave"): a standard systematic trend proxy --
    the ratio's position relative to a short and a long moving average.
  - at_edge ("get ready to turn"): a z-score of the ratio's recent rate
    of change against its own trailing history, the SAME statistical
    technique cot_adapter.parse_cot_positioning already uses, flagged
    honestly as a "this move is stretched, be cautious" risk flag, not a
    reversal-timing prediction.

Fetch/parse split like every other adapter here: fetch_breadth_prices is
the only function that touches the network (reusing the existing
tiger_stock_bars_adapter, unchanged), everything else is pure.
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df

RATIO_MA_SHORT_DAYS = 20
RATIO_MA_LONG_DAYS = 100
ROC_LOOKBACK_DAYS = 20
EXTREME_Z = 2.0
TILT_MAGNITUDE = 0.1

RSP_SYMBOL = "RSP"
SPY_SYMBOL = "SPY"


@dataclass
class BreadthSignal:
    as_of: str
    ratio: float
    ma_short: float
    ma_long: float
    trend: str          # "broadening" | "narrowing" | "flat"
    roc: float
    roc_zscore: float
    at_edge: bool
    tilt: float          # bounded 0.9-1.1, same convention as cot_adapter.positioning_to_tilt


def fetch_breadth_prices(quote_client, lookback_days: int = 252):
    """The only function here that touches the network."""
    rsp_df = fetch_stock_bars(quote_client, RSP_SYMBOL, limit=lookback_days + 30)
    spy_df = fetch_stock_bars(quote_client, SPY_SYMBOL, limit=lookback_days + 30)
    return parse_stock_bars_df(rsp_df), parse_stock_bars_df(spy_df)


def compute_ratio_series(
    rsp_prices: List[Tuple[date, float]], spy_prices: List[Tuple[date, float]]
) -> List[Tuple[date, float]]:
    """Pure -- aligns the two series by date and divides RSP by SPY."""
    spy_by_date = {d: p for d, p in spy_prices}
    return [(d, rsp / spy_by_date[d]) for d, rsp in rsp_prices if d in spy_by_date and spy_by_date[d] > 0]


def _moving_average(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _zscore(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / max(1, len(values) - 1)
    std = variance ** 0.5
    return (values[-1] - mean) / std if std > 0 else 0.0


def compute_breadth_signal(
    ratio_series: List[Tuple[date, float]],
    ma_short_days: int = RATIO_MA_SHORT_DAYS,
    ma_long_days: int = RATIO_MA_LONG_DAYS,
    roc_lookback_days: int = ROC_LOOKBACK_DAYS,
    extreme_z: float = EXTREME_Z,
    tilt_magnitude: float = TILT_MAGNITUDE,
) -> Optional[BreadthSignal]:
    """
    Pure -- no network. ratio_series is oldest-first (date, ratio) pairs,
    as compute_ratio_series produces. Returns None if there isn't enough
    history yet for the long moving average plus a rate-of-change window,
    same "not eligible yet" convention used throughout this codebase.
    """
    required = ma_long_days + roc_lookback_days
    if len(ratio_series) < required:
        return None

    dates = [d for d, _ in ratio_series]
    values = [v for _, v in ratio_series]

    ma_short = _moving_average(values, ma_short_days)
    ma_long = _moving_average(values, ma_long_days)
    ratio = values[-1]

    if ma_short is None or ma_long is None:
        return None

    if ratio > ma_long and ma_short > ma_long:
        trend = "broadening"
    elif ratio < ma_long and ma_short < ma_long:
        trend = "narrowing"
    else:
        trend = "flat"

    roc_series = [
        (values[i] - values[i - roc_lookback_days]) / values[i - roc_lookback_days]
        for i in range(roc_lookback_days, len(values))
        if values[i - roc_lookback_days] > 0
    ]
    roc = roc_series[-1] if roc_series else 0.0
    z = _zscore(roc_series)
    at_edge = abs(z) >= extreme_z

    clamped = max(-extreme_z, min(extreme_z, z))
    if trend == "broadening":
        tilt = 1.0 + tilt_magnitude * (clamped / extreme_z if clamped > 0 else 0.0)
    elif trend == "narrowing":
        tilt = 1.0 + tilt_magnitude * (clamped / extreme_z if clamped < 0 else 0.0)
    else:
        tilt = 1.0

    return BreadthSignal(
        as_of=dates[-1].isoformat() if hasattr(dates[-1], "isoformat") else str(dates[-1]),
        ratio=round(ratio, 5),
        ma_short=round(ma_short, 5),
        ma_long=round(ma_long, 5),
        trend=trend,
        roc=round(roc, 4),
        roc_zscore=round(z, 3),
        at_edge=at_edge,
        tilt=round(tilt, 4),
    )
