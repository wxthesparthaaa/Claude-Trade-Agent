"""
Simplified Black-Scholes option pricing, used ONLY for backtesting against
historical STOCK price data (which is free). Tiger's free tier doesn't
include historical option chain snapshots -- only bars for contracts you
already know the identifier of (hindsight bias) or live chain data
(needs the paid OPT permission). This model lets us reconstruct
theoretical premiums from real historical stock prices instead.

This is a MODEL, not replayed real market quotes. Real premiums differ
due to bid/ask spread, volatility skew, and supply/demand. Treat backtest
output as directionally informative about whether a target is plausible,
not as a promise of real fills.
"""
import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_d1_d2(spot: float, strike: float, dte_years: float, vol: float, rate: float = 0.045):
    if dte_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        raise ValueError("spot, strike, dte_years, and vol must all be positive")
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * dte_years) / (vol * math.sqrt(dte_years))
    d2 = d1 - vol * math.sqrt(dte_years)
    return d1, d2


def put_price(spot: float, strike: float, dte_years: float, vol: float, rate: float = 0.045) -> float:
    d1, d2 = bs_d1_d2(spot, strike, dte_years, vol, rate)
    return strike * math.exp(-rate * dte_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def put_delta(spot: float, strike: float, dte_years: float, vol: float, rate: float = 0.045) -> float:
    d1, _ = bs_d1_d2(spot, strike, dte_years, vol, rate)
    return _norm_cdf(d1) - 1.0  # negative, matches Tiger's put delta sign convention


def call_price(spot: float, strike: float, dte_years: float, vol: float, rate: float = 0.045) -> float:
    d1, d2 = bs_d1_d2(spot, strike, dte_years, vol, rate)
    return spot * _norm_cdf(d1) - strike * math.exp(-rate * dte_years) * _norm_cdf(d2)


def call_delta(spot: float, strike: float, dte_years: float, vol: float, rate: float = 0.045) -> float:
    d1, _ = bs_d1_d2(spot, strike, dte_years, vol, rate)
    return _norm_cdf(d1)


def solve_strike_for_put_delta(
    spot: float,
    target_delta: float,
    dte_years: float,
    vol: float,
    rate: float = 0.045,
    tolerance: float = 0.001,
    max_iter: int = 100,
) -> float:
    """
    Finds the strike whose theoretical put delta is closest to
    -abs(target_delta), via bisection. target_delta is given as a positive
    magnitude (e.g. 0.20), matching how StrategyConfig expresses it.
    """
    target = -abs(target_delta)
    lo, hi = spot * 0.5, spot * 1.2
    mid = spot
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        d = put_delta(spot, mid, dte_years, vol, rate)
        if abs(d - target) < tolerance:
            return mid
        if d < target:   # too negative -> strike too high, search lower half
            hi = mid
        else:
            lo = mid
    return mid
