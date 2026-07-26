"""
Backtest engine for the cash-secured-put weekly income strategy, using
real historical STOCK closes plus the Black-Scholes model from
options_pricing.py to reconstruct theoretical weekly premiums.

Pure logic -- takes a plain list of (date, close) tuples, so it's fully
unit-testable with synthetic price series. The only network-touching piece
is a separate adapter (tiger_stock_bars_adapter.py) that fetches real
prices and converts them into this same format.
"""
import math
from dataclasses import dataclass
from datetime import date
from typing import List, Tuple

from options_pricing import put_price, solve_strike_for_put_delta


@dataclass
class WeeklyResult:
    week_start: date
    spot: float
    strike: float
    dte_days: int
    implied_vol_used: float
    premium_per_share: float
    contracts: int
    notional: float
    premium_total: float
    close_at_expiry: float
    assigned: bool
    pnl: float
    weekly_yield: float


def realized_volatility(closes: List[float], annualization_factor: float = 252) -> float:
    """
    Annualized realized volatility from a list of daily closes, using
    log returns. Needs at least 2 closes; more (e.g. 20+) is meaningfully
    more stable.
    """
    if len(closes) < 2:
        raise ValueError("Need at least 2 closes to compute volatility")
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / max(1, len(log_returns) - 1)
    daily_vol = math.sqrt(variance)
    return daily_vol * math.sqrt(annualization_factor)


def run_backtest(
    prices: List[Tuple[date, float]],
    target_delta: float = 0.20,
    dte_days: int = 7,
    trading_days_per_period: int = 5,
    vol_window: int = 20,
    rate: float = 0.045,
    contracts: int = 1,
) -> List[WeeklyResult]:
    """
    prices: chronologically sorted list of (date, close), daily.
    Simulates non-overlapping weekly cash-secured put sells: each week,
    estimate realized vol from the trailing window, solve for the strike
    matching target_delta, price it via Black-Scholes, then check the
    actual historical close `trading_days_per_period` trading days later
    to determine assignment and realized PnL.
    """
    if len(prices) < vol_window + trading_days_per_period + 1:
        raise ValueError(
            f"Need at least {vol_window + trading_days_per_period + 1} price points, "
            f"got {len(prices)}"
        )

    closes = [p[1] for p in prices]
    dates = [p[0] for p in prices]
    results: List[WeeklyResult] = []

    i = vol_window
    while i + trading_days_per_period < len(closes):
        trailing = closes[i - vol_window: i + 1]
        vol = realized_volatility(trailing)
        spot = closes[i]
        dte_years = dte_days / 365.0

        strike = round(solve_strike_for_put_delta(spot, target_delta, dte_years, vol, rate), 2)
        premium_per_share = put_price(spot, strike, dte_years, vol, rate)

        expiry_idx = i + trading_days_per_period
        close_at_expiry = closes[expiry_idx]
        assigned = close_at_expiry < strike

        notional = strike * 100 * contracts
        premium_total = premium_per_share * 100 * contracts
        loss_if_assigned = max(0.0, strike - close_at_expiry) * 100 * contracts
        pnl = premium_total - loss_if_assigned
        weekly_yield = premium_total / notional if notional > 0 else 0.0

        results.append(
            WeeklyResult(
                week_start=dates[i],
                spot=spot,
                strike=strike,
                dte_days=dte_days,
                implied_vol_used=vol,
                premium_per_share=round(premium_per_share, 4),
                contracts=contracts,
                notional=notional,
                premium_total=round(premium_total, 2),
                close_at_expiry=close_at_expiry,
                assigned=assigned,
                pnl=round(pnl, 2),
                weekly_yield=weekly_yield,
            )
        )
        i += trading_days_per_period

    return results


def summarize(results: List[WeeklyResult]) -> dict:
    if not results:
        return {"weeks": 0}
    total_pnl = sum(r.pnl for r in results)
    assigned_weeks = sum(1 for r in results if r.assigned)
    avg_weekly_yield = sum(r.weekly_yield for r in results) / len(results)
    avg_weekly_pnl = total_pnl / len(results)
    return {
        "weeks": len(results),
        "assigned_weeks": assigned_weeks,
        "assignment_rate": assigned_weeks / len(results),
        "total_pnl": round(total_pnl, 2),
        "avg_weekly_pnl": round(avg_weekly_pnl, 2),
        "avg_weekly_yield": avg_weekly_yield,
        "worst_week_pnl": round(min(r.pnl for r in results), 2),
        "best_week_pnl": round(max(r.pnl for r in results), 2),
    }
