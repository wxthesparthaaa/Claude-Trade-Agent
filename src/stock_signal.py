"""
Stock/ETF selection signal: momentum + trailing dividend yield, blended with
an optional news tilt (see news_scanner.py) into one composite score used to
rank candidates. Deliberately simple -- two hard numeric factors plus one
externally-supplied qualitative tilt, not a multi-factor black box.

Pure logic, no network -- takes plain (date, close) price series and
(date, amount) dividend series, same shape tiger_stock_bars_adapter.py and
tiger_dividend_adapter.py already produce.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple


def momentum_score(prices: List[Tuple[date, float]], lookback_days: int = 126, skip_recent_days: int = 21) -> float:
    """
    Classic 6-month-minus-1-month momentum: total return from
    `lookback_days` trading days ago up to `skip_recent_days` trading days
    ago (skipping the most recent month avoids chasing short-term
    mean-reverting noise). Returns a plain fractional return, e.g. 0.15 = 15%.
    """
    if len(prices) < lookback_days + 1:
        raise ValueError(f"Need at least {lookback_days + 1} price points, got {len(prices)}")

    closes = [p[1] for p in prices]
    start_idx = len(closes) - 1 - lookback_days
    end_idx = len(closes) - 1 - skip_recent_days
    if end_idx <= start_idx:
        raise ValueError("skip_recent_days must be smaller than lookback_days")

    start_price = closes[start_idx]
    end_price = closes[end_idx]
    if start_price <= 0:
        raise ValueError("start_price must be positive")

    return (end_price - start_price) / start_price


def trailing_dividend_yield(
    prices: List[Tuple[date, float]],
    dividends: List[Tuple[date, float]],
    trailing_days: int = 365,
) -> float:
    """
    Sum of dividends paid in the trailing `trailing_days` window, divided by
    the most recent close. Returns 0.0 if there's no dividend history
    (growth stocks/ETFs) rather than raising -- absence of a dividend is a
    valid, common case, not an error.
    """
    if not prices:
        raise ValueError("prices must be non-empty")

    last_date, last_price = prices[-1]
    if last_price <= 0:
        raise ValueError("last_price must be positive")

    cutoff = last_date - timedelta(days=trailing_days)
    trailing_total = sum(amount for d, amount in dividends if cutoff <= d <= last_date)
    return trailing_total / last_price


def composite_score(
    momentum: float,
    div_yield: float,
    news_tilt: float = 0.0,
    sector_tilt: float = 0.0,
    weights: Dict[str, float] = None,
) -> float:
    """
    Simple weighted sum, not a black box: default weights favor momentum
    (the primary satellite-sleeve signal) with dividend yield, news tilt,
    and sector tilt as secondary adjustments. news_tilt is expected in
    [-1, 1], synthesized externally by news_scanner.py from that day's
    headlines. sector_tilt is expected in [-1, 1] too, synthesized
    externally by sector_rotation.get_sector_tilt from the symbol's GICS
    sector's current relative-strength rank -- this function doesn't
    compute either tilt itself, just blends them in. A weights dict with
    no "sector_tilt" key (e.g. DIVIDEND_SCORING_WEIGHTS) makes this a
    no-op contribution regardless of the tilt's value, via weights.get's
    0.0 default below.
    """
    weights = weights or {"momentum": 0.6, "div_yield": 0.3, "news_tilt": 0.1, "sector_tilt": 0.1}
    return (
        weights.get("momentum", 0.0) * momentum
        + weights.get("div_yield", 0.0) * div_yield
        + weights.get("news_tilt", 0.0) * news_tilt
        + weights.get("sector_tilt", 0.0) * sector_tilt
    )


def rank_candidates(scores: Dict[str, float]) -> List[str]:
    """Returns symbols sorted by score, descending."""
    return [symbol for symbol, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


@dataclass
class SymbolScore:
    momentum: float
    div_yield: float
    score: float
    price: float


def score_symbol(
    price_series: List[Tuple[date, float]],
    dividends: List[Tuple[date, float]],
    lookback_days: int = 126,
    skip_recent_days: int = 21,
    news_tilt: float = 0.0,
    sector_tilt: float = 0.0,
    weights: Dict[str, float] = None,
) -> Optional[SymbolScore]:
    """
    One symbol's full scoring pipeline (momentum -> dividend yield ->
    composite), shared by the backtest and live execution paths so both
    score identically -- returns None rather than raising when there isn't
    enough history yet, since "not eligible this period" is a normal,
    expected outcome, not an error.
    """
    if len(price_series) < lookback_days + 1:
        return None
    try:
        momentum = momentum_score(price_series, lookback_days=lookback_days, skip_recent_days=skip_recent_days)
    except ValueError:
        return None
    div_yield = trailing_dividend_yield(price_series, dividends)
    score = composite_score(momentum, div_yield, news_tilt, sector_tilt, weights)
    return SymbolScore(momentum=momentum, div_yield=div_yield, score=score, price=price_series[-1][1])
