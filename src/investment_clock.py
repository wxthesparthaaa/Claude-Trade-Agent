"""
Investment Clock: the classic (growth, inflation) 2x2 macro-cycle
framework (Merrill Lynch / Trevor Greetham) -- maps rising/falling growth
crossed with rising/falling inflation into one of 4 quadrants, each with
its textbook best-performing equity sectors. Meant as CONTEXT to compare
against sector_rotation.py's mechanical ranking ("theory says X should
lead; actual flows show Y leading" is itself useful information), not as
an override or an input into it.

US only: growth/inflation trend data of usable quality doesn't exist for
free at HK/SG (this project's only other free macro sources -- CFTC COT
positioning, RSP/SPY breadth -- aren't growth/inflation proxies). Rather
than fabricate a number, hk_sg_unavailable_signal() states this plainly.

Growth proxy: INDPRO (Industrial Production Index, monthly) -- a real-
economy series, not survey-based (ISM PMI isn't freely available on
FRED). Inflation proxy: T10YIE (10-Year Breakeven Inflation Rate, daily,
market-implied) -- updates far more often than CPI's monthly lag, which
matters more for a trading app's cadence than textbook-standard CPI
would. Both fetched via fred_adapter.py, free, no API key.

Trend classification mirrors market_breadth.py's own short-MA-vs-long-MA
style, just applied to a single series instead of a ratio.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import List, Optional, Tuple

from fred_adapter import fetch_and_parse_series

INDPRO_SERIES = "INDPRO"
T10YIE_SERIES = "T10YIE"

GROWTH_MA_SHORT = 3      # months of INDPRO
GROWTH_MA_LONG = 12       # months of INDPRO
INFLATION_MA_SHORT = 20    # trading days of T10YIE
INFLATION_MA_LONG = 100    # trading days of T10YIE

# (growth_rising, inflation_rising) -> (quadrant name, textbook best sectors)
CLOCK_QUADRANTS = {
    (True, False): ("Recovery", ["Technology", "Consumer Discretionary", "Industrials"]),
    (True, True): ("Overheat", ["Energy", "Materials"]),
    (False, True): ("Stagflation", ["Consumer Staples", "Utilities", "Health Care"]),
    (False, False): ("Reflation", ["Utilities", "Health Care", "Consumer Staples"]),
}


@dataclass
class InvestmentClockSignal:
    as_of: str
    region: str              # "US" | "HK" | "SG"
    quadrant: str              # "Recovery" | "Overheat" | "Stagflation" | "Reflation" | ""
    growth_trend: str           # "rising" | "falling" | ""
    inflation_trend: str         # "rising" | "falling" | ""
    growth_value: float
    inflation_value: float
    best_sectors: List[str] = field(default_factory=list)
    note: str = ""


def _trend(series: List[Tuple[date, float]], ma_short: int, ma_long: int) -> Optional[str]:
    """Pure. "rising" if the short-window average is above the long-
    window average, else "falling". None if there isn't enough history."""
    if len(series) < ma_long:
        return None
    values = [v for _, v in series]
    short_avg = sum(values[-ma_short:]) / ma_short
    long_avg = sum(values[-ma_long:]) / ma_long
    return "rising" if short_avg > long_avg else "falling"


def compute_investment_clock(
    growth_series: List[Tuple[date, float]], inflation_series: List[Tuple[date, float]],
) -> Optional[InvestmentClockSignal]:
    """Pure -- no network. growth_series: INDPRO observations.
    inflation_series: T10YIE observations. Returns None if either series
    doesn't have enough history yet for its own moving averages."""
    growth_trend = _trend(growth_series, GROWTH_MA_SHORT, GROWTH_MA_LONG)
    inflation_trend = _trend(inflation_series, INFLATION_MA_SHORT, INFLATION_MA_LONG)
    if growth_trend is None or inflation_trend is None:
        return None

    quadrant, best_sectors = CLOCK_QUADRANTS[(growth_trend == "rising", inflation_trend == "rising")]

    return InvestmentClockSignal(
        as_of=date.today().isoformat(),
        region="US",
        quadrant=quadrant,
        growth_trend=growth_trend,
        inflation_trend=inflation_trend,
        growth_value=growth_series[-1][1],
        inflation_value=inflation_series[-1][1],
        best_sectors=best_sectors,
    )


def hk_sg_unavailable_signal(region: str) -> InvestmentClockSignal:
    return InvestmentClockSignal(
        as_of=date.today().isoformat(), region=region, quadrant="", growth_trend="", inflation_trend="",
        growth_value=0.0, inflation_value=0.0, best_sectors=[],
        note=f"No free growth/inflation data of usable quality exists for {region} -- the Investment Clock is US-only.",
    )


def refresh_investment_clock() -> InvestmentClockSignal:
    """Orchestrates a full refresh: fetches both FRED series and computes
    the current quadrant. Raises ValueError if there isn't enough history
    yet, and lets a real fetch failure propagate -- a scheduled-job
    caller should catch and skip, same convention as
    scheduled_breadth_update et al."""
    growth_series = fetch_and_parse_series(INDPRO_SERIES)
    inflation_series = fetch_and_parse_series(T10YIE_SERIES)
    signal = compute_investment_clock(growth_series, inflation_series)
    if signal is None:
        raise ValueError("Not enough FRED history yet to compute the Investment Clock")
    return signal


def load_investment_clock(path: str) -> Optional[InvestmentClockSignal]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return InvestmentClockSignal(**data)


def save_investment_clock(path: str, signal: InvestmentClockSignal) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(signal), f, indent=2)
