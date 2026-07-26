"""
Run with:
    python scripts/run_backtest.py

Pulls real historical AAPL daily closes (free, no paid options permission
needed) and runs the weekly cash-secured-put backtest against them, using
the Black-Scholes model to reconstruct theoretical premiums.

Reminder: this is a MODEL of what a 20-delta weekly put would have paid,
not replayed real option quotes. Treat the output as "is this target
plausible in shape," not "this is exactly what I'd have earned."
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient

from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df
from backtest import run_backtest, summarize

SYMBOL = "AAPL"
TARGET_DELTA = 0.20
DTE_DAYS = 7
CONTRACTS = 1          # scale this up in analysis, not by changing risk limits
CAPITAL_FOR_SCALING = 25000  # your actual cap, used only to show a scaled estimate below


def main():
    client_config = get_client_config()
    quote_client = QuoteClient(client_config)

    print(f"Fetching ~1 year of historical daily bars for {SYMBOL}...")
    df = fetch_stock_bars(quote_client, SYMBOL, limit=250)
    prices = parse_stock_bars_df(df)
    print(f"Got {len(prices)} daily closes, {prices[0][0]} to {prices[-1][0]}.")

    results = run_backtest(
        prices, target_delta=TARGET_DELTA, dte_days=DTE_DAYS,
        trading_days_per_period=5, vol_window=20, contracts=CONTRACTS,
    )
    summary = summarize(results)

    print(f"\n--- Backtest summary: {SYMBOL}, {TARGET_DELTA:.0%} delta weekly puts, "
          f"{CONTRACTS} contract ---")
    for k, v in summary.items():
        print(f"{k}: {v}")

    if summary["weeks"] > 0:
        avg_notional = sum(r.notional for r in results) / len(results)
        implied_contracts_for_target = CAPITAL_FOR_SCALING / avg_notional if avg_notional > 0 else 0
        print(f"\nAt ~${avg_notional:,.0f} notional per contract, your ${CAPITAL_FOR_SCALING:,.0f} "
              f"cap could roughly support {implied_contracts_for_target:.1f}x this position size "
              f"(diversified across different underlyings in practice, not all on AAPL).")
        print(f"Scaled avg weekly PnL estimate: "
              f"${summary['avg_weekly_pnl'] * implied_contracts_for_target:,.2f}/week "
              f"(illustrative only -- real diversification changes this).")

    print("\nRun complete. This used only free historical stock data -- no paid permission required.")


if __name__ == "__main__":
    main()
