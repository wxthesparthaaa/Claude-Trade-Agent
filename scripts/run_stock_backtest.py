"""
Run with:
    python scripts/run_stock_backtest.py

Fetches real historical bars, dividends, and board-lot metadata for
DEFAULT_UNIVERSE via Tiger's paper account, then runs the core-satellite
backtest and prints results -- worst-period drawdown called out explicitly,
matching the honesty standard set by the options-era backtest sweep: don't
just report the average, report the worst case.

Uses config/regime.json if it exists (see macro_regime.py) to tilt sleeve
weights toward the currently-assessed macro regime; runs without a tilt if
that file hasn't been created yet.
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import Market

from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df
from tiger_dividend_adapter import fetch_corporate_dividends, parse_dividend_df
from tiger_trade_metas_adapter import fetch_trade_metas, parse_trade_metas_df
from universe import DEFAULT_UNIVERSE
from portfolio_construction import PortfolioConfig
from risk_engine import RiskConfig, RiskEngine
from stock_backtest import run_stock_backtest, summarize
from macro_regime import load_regime_signal
from decision_log import format_decision_summary, write_decision_log

INITIAL_CAPITAL = 1000.0
REGIME_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "regime.json")
DECISION_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "decision_log.json")

_MARKET_ENUM = {"US": Market.US, "HK": Market.HK, "SG": Market.SG}


def main():
    client_config = get_client_config()
    quote_client = QuoteClient(client_config)

    symbols = [e.symbol for e in DEFAULT_UNIVERSE]
    print(f"Fetching bars, dividends, and trade metas for {len(symbols)} symbols...\n")

    prices_by_symbol = {}
    for entry in DEFAULT_UNIVERSE:
        try:
            df = fetch_stock_bars(quote_client, entry.symbol, limit=750)  # ~3 years of daily bars
            prices = parse_stock_bars_df(df)
            if len(prices) < 150:
                print(f"{entry.symbol}: only {len(prices)} price points, skipping")
                continue
            prices_by_symbol[entry.symbol] = prices
        except Exception as e:
            print(f"{entry.symbol}: bars fetch failed ({type(e).__name__}: {e}), skipping")

    dividends_by_symbol = {}
    begin_date = (date.today() - timedelta(days=365 * 3)).isoformat()
    end_date = date.today().isoformat()
    by_market = {}
    for entry in DEFAULT_UNIVERSE:
        by_market.setdefault(entry.market, []).append(entry.symbol)
    for market, market_symbols in by_market.items():
        try:
            df = fetch_corporate_dividends(
                quote_client, market_symbols, _MARKET_ENUM[market], begin_date, end_date
            )
            dividends_by_symbol.update(parse_dividend_df(df))
        except Exception as e:
            print(f"Dividend fetch failed for {market} symbols ({type(e).__name__}: {e})")

    try:
        trade_metas_df = fetch_trade_metas(quote_client, symbols)
        lot_infos = parse_trade_metas_df(trade_metas_df)
    except Exception as e:
        print(f"Trade metas fetch failed ({type(e).__name__}: {e}), proceeding without lot-size filtering")
        lot_infos = {}

    regime_tilts = None
    if os.path.exists(REGIME_PATH):
        try:
            regime = load_regime_signal(REGIME_PATH)
            regime_tilts = regime.sleeve_tilts
            print(f"Using regime signal from {regime.as_of}: {regime.regime} -> tilts {regime.sleeve_tilts}\n")
        except Exception as e:
            print(f"Failed to load regime signal ({type(e).__name__}: {e}), proceeding without a tilt\n")
    else:
        print("No config/regime.json found -- proceeding without a macro tilt\n")

    risk_engine = RiskEngine(RiskConfig())
    config = PortfolioConfig()

    try:
        results = run_stock_backtest(
            prices_by_symbol, dividends_by_symbol, DEFAULT_UNIVERSE, config, risk_engine,
            initial_capital=INITIAL_CAPITAL, regime_tilts=regime_tilts, lot_infos=lot_infos,
        )
    except ValueError as e:
        print(f"Backtest could not run: {e}")
        return

    summary = summarize(results, target_monthly_pct=risk_engine.config.monthly_income_target / INITIAL_CAPITAL)

    print(f"--- Backtest results ({summary['periods']} rebalance periods) ---")
    print(f"Total return: {summary['total_return_pct']:.1%}")
    print(f"Average period return: {summary['avg_period_return_pct']:.1%}")
    print(f"Best period: {summary['best_period_pct']:.1%}   Worst period: {summary['worst_period_pct']:.1%}")
    print(f"Max drawdown: {summary['max_drawdown_pct']:.1%}")
    print(f"Hit rate vs {risk_engine.config.monthly_income_target / INITIAL_CAPITAL:.0%}/period target: "
          f"{summary['hit_rate_vs_target']:.0%}")
    print(f"Final equity from ${INITIAL_CAPITAL:.2f}: ${summary['final_equity']:.2f}")
    print(f"Early exits (stop-loss/momentum-reversal, before the scheduled rebalance): {summary['early_exits']}")
    if summary["halted"]:
        print(f"\n*** Backtest HALTED early: {summary['halt_reason']} ***")

    if os.path.exists(DECISION_LOG_PATH):
        os.remove(DECISION_LOG_PATH)  # fresh log each backtest run, not appended across reruns

    print("\n--- Per-period detail (with sell rationale) ---")
    for r in results:
        symbols_held = ", ".join(f"{p.symbol}({p.target_pct:.0%})" for p in r.positions)
        print(f"{r.period_start}: return={r.period_return_pct:+.1%}  equity=${r.equity_after:,.2f}  "
              f"positions=[{symbols_held}]")
        for e in r.exits:
            print(f"    SOLD {e.symbol} on {e.exit_date}: {e.reason} (realized {e.return_at_exit:+.1%})")
        write_decision_log(DECISION_LOG_PATH, str(r.period_start), r.decisions)

    print(f"\nFull decision rationale for every period written to {DECISION_LOG_PATH}")
    print("\n--- Rationale for the most recent period ---")
    print(format_decision_summary(str(results[-1].period_start), results[-1].decisions))


if __name__ == "__main__":
    main()
