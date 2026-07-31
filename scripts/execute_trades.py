"""
Run with:
    python scripts/execute_trades.py           (dry run -- computes and prints only)
    python scripts/execute_trades.py --live    (actually places orders against Tiger)

Scores today's candidates the same way the backtest does (via
stock_signal.score_symbol, so live and backtested behavior stay
consistent), applies the exit rules to whatever's currently held (not just
the rebalance ranking -- a real "when to sell" check), reconciles against
actual Tiger positions, and passes every resulting order through
risk_engine.validate_trade() before it's allowed anywhere near
tiger_order_adapter.place_market_order -- the only function in this whole
project that actually submits an order.

Defaults to a dry run: everything is computed, scored, and logged, but no
order is placed unless --live is passed. This script targets whatever
account tiger_client.get_client_config() is pointed at -- verify that's
still the paper account before ever passing --live.
"""
import sys
import os
import argparse
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.trade.trade_client import TradeClient
from tigeropen.common.consts import Market

from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df
from tiger_dividend_adapter import fetch_corporate_dividends, parse_dividend_df
from tiger_trade_metas_adapter import fetch_trade_metas, parse_trade_metas_df
from universe import DEFAULT_UNIVERSE
from stock_signal import score_symbol, momentum_score
from portfolio_construction import PortfolioConfig, ScoredCandidate, allocate_portfolio, filter_affordable_by_lot
from exit_rules import ExitConfig, check_stop_loss, check_momentum_reversal
from risk_engine import RiskConfig, RiskEngine, RiskViolation, DailyState, Position as RiskPosition
from execution import reconcile_positions, CurrentPosition
from tiger_order_adapter import build_contract, place_market_order
from decision_log import DecisionRecord, format_decision_summary, write_decision_log
from macro_regime import load_regime_signal
from news_scanner import load_news_signal, get_tilt
from strategy_ledger import load_or_init_ledger, latest_capital

INITIAL_CAPITAL = 1000.0
MOMENTUM_LOOKBACK_DAYS = 126
MOMENTUM_SKIP_DAYS = 21

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
REGIME_PATH = os.path.join(CONFIG_DIR, "regime.json")
NEWS_PATH = os.path.join(CONFIG_DIR, "news_signal.json")
DECISION_LOG_PATH = os.path.join(CONFIG_DIR, "decision_log.json")
LEDGER_PATH = os.path.join(CONFIG_DIR, "strategy_ledger.json")

_MARKET_ENUM = {"US": Market.US, "HK": Market.HK, "SG": Market.SG}
_SLEEVE_TO_STRATEGY = {"core": "core_hold", "satellite": "satellite_momentum"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                         help="Actually place orders. Without this flag, computes and prints only.")
    args = parser.parse_args()

    client_config = get_client_config()
    quote_client = QuoteClient(client_config)
    trade_client = TradeClient(client_config)

    universe = DEFAULT_UNIVERSE
    sleeve_by_symbol = {e.symbol: e.sleeve for e in universe}

    print(f"Scoring {len(universe)} candidates as of {date.today()}...")
    prices_by_symbol = {}
    for entry in universe:
        try:
            df = fetch_stock_bars(quote_client, entry.symbol, limit=MOMENTUM_LOOKBACK_DAYS + 30)
            prices = parse_stock_bars_df(df)
            if len(prices) >= MOMENTUM_LOOKBACK_DAYS + 1:
                prices_by_symbol[entry.symbol] = prices
        except Exception as e:
            print(f"  {entry.symbol}: bars fetch failed ({type(e).__name__}: {e}), skipping")

    dividends_by_symbol = {}
    by_market = {}
    for entry in universe:
        by_market.setdefault(entry.market, []).append(entry.symbol)
    begin_date = (date.today() - timedelta(days=365 * 2)).isoformat()
    end_date = date.today().isoformat()
    for market, symbols in by_market.items():
        try:
            df = fetch_corporate_dividends(quote_client, symbols, _MARKET_ENUM[market], begin_date, end_date)
            dividends_by_symbol.update(parse_dividend_df(df))
        except Exception as e:
            print(f"  Dividend fetch failed for {market} symbols ({type(e).__name__}: {e})")

    news_signals = {}
    if os.path.exists(NEWS_PATH):
        try:
            news_signals = load_news_signal(NEWS_PATH)
        except Exception as e:
            print(f"  Failed to load news signal ({type(e).__name__}: {e})")

    regime_tilts = None
    if os.path.exists(REGIME_PATH):
        try:
            regime_tilts = load_regime_signal(REGIME_PATH).sleeve_tilts
        except Exception as e:
            print(f"  Failed to load regime signal ({type(e).__name__}: {e})")

    all_candidates = []
    for symbol, prices in prices_by_symbol.items():
        tilt = get_tilt(news_signals, symbol) if news_signals else 0.0
        scored = score_symbol(
            prices, dividends_by_symbol.get(symbol, []),
            lookback_days=MOMENTUM_LOOKBACK_DAYS, skip_recent_days=MOMENTUM_SKIP_DAYS, news_tilt=tilt,
        )
        if scored is not None:
            all_candidates.append(ScoredCandidate(symbol=symbol, sleeve=sleeve_by_symbol[symbol],
                                                   score=scored.score, price=scored.price))

    try:
        lot_infos = parse_trade_metas_df(fetch_trade_metas(quote_client, [e.symbol for e in universe]))
    except Exception as e:
        print(f"  Trade metas fetch failed ({type(e).__name__}: {e}), proceeding without lot-size filtering")
        lot_infos = {}

    ledger = load_or_init_ledger(LEDGER_PATH, INITIAL_CAPITAL)
    capital = latest_capital(ledger)

    config = PortfolioConfig()
    affordable = all_candidates
    if lot_infos and all_candidates:
        affordable_symbols = set(filter_affordable_by_lot(
            symbol_prices={c.symbol: c.price for c in all_candidates},
            lot_infos=lot_infos, available_capital=capital, max_position_pct=config.max_single_position_pct,
        ))
        affordable = [c for c in all_candidates if c.symbol in affordable_symbols]

    planned = allocate_portfolio(affordable, config, capital=capital, regime_tilts=regime_tilts)

    raw_positions = trade_client.get_positions() or []
    current_positions = {}
    for p in raw_positions:
        symbol = p.contract.symbol
        if symbol in sleeve_by_symbol and p.quantity and p.quantity > 0:
            current_positions[symbol] = CurrentPosition(
                symbol=symbol, quantity=int(p.quantity), average_cost=float(p.average_cost or 0.0)
            )

    # Exit-rule check on whatever's currently held -- independent of this
    # period's rebalance ranking, this is the real "when to sell" check.
    exit_config = ExitConfig()
    exit_reasons = {}
    price_by_symbol = {c.symbol: c.price for c in all_candidates}
    for symbol, position in current_positions.items():
        current_price = price_by_symbol.get(symbol)
        if current_price is None:
            continue
        stop_decision = check_stop_loss(position.average_cost, current_price, exit_config)
        if stop_decision.should_exit:
            exit_reasons[symbol] = stop_decision.reason
            continue
        prices = prices_by_symbol.get(symbol)
        if prices:
            try:
                rolling_momentum = momentum_score(
                    prices, lookback_days=MOMENTUM_LOOKBACK_DAYS, skip_recent_days=MOMENTUM_SKIP_DAYS
                )
                mom_decision = check_momentum_reversal(rolling_momentum, exit_config)
                if mom_decision.should_exit:
                    exit_reasons[symbol] = mom_decision.reason
            except ValueError:
                pass

    planned = [p for p in planned if p.symbol not in exit_reasons]

    lot_size_by_symbol = {sym: info.lot_size for sym, info in lot_infos.items()}
    instructions = reconcile_positions(planned, current_positions, price_by_symbol, lot_size_by_symbol)

    risk_engine = RiskEngine(RiskConfig())
    equity_curve = [h["capital"] for h in ledger["history"]]
    halted = False
    try:
        risk_engine.check_max_drawdown(equity_curve)
    except RiskViolation as e:
        print(f"\n*** RISK ENGINE HALT: {e} ***\n")
        halted = True

    state = DailyState(
        date=date.today(),
        realized_pnl_today=0.0,
        open_positions=[
            RiskPosition(
                symbol=sym, strategy=_SLEEVE_TO_STRATEGY.get(sleeve_by_symbol.get(sym), "core_hold"),
                notional=pos.quantity * price_by_symbol.get(sym, pos.average_cost),
                premium_collected=0.0, opened_on=date.today(),
            )
            for sym, pos in current_positions.items()
        ],
    )

    decisions = []
    approved_instructions = []
    for instr in instructions:
        sleeve = sleeve_by_symbol.get(instr.symbol, "unknown")
        if halted:
            decisions.append(DecisionRecord(
                date=str(date.today()), action="reject", symbol=instr.symbol, sleeve=sleeve,
                reason="risk engine drawdown halt is active -- no new orders",
            ))
            continue
        strategy_key = _SLEEVE_TO_STRATEGY.get(sleeve, "core_hold")
        try:
            risk_engine.validate_trade(state, strategy_key, instr.notional)
            approved_instructions.append(instr)
            action = "buy" if instr.action == "BUY" else "sell"
            reason = exit_reasons.get(instr.symbol, instr.reason)
            decisions.append(DecisionRecord(date=str(date.today()), action=action, symbol=instr.symbol,
                                             sleeve=sleeve, reason=reason))
        except RiskViolation as e:
            decisions.append(DecisionRecord(
                date=str(date.today()), action="reject", symbol=instr.symbol, sleeve=sleeve,
                reason=f"risk engine blocked: {e}",
            ))

    write_decision_log(DECISION_LOG_PATH, str(date.today()), decisions)
    print(format_decision_summary(str(date.today()), decisions))

    print(f"\n{len(approved_instructions)} order(s) approved to place:")
    for instr in approved_instructions:
        print(f"  {instr.action} {instr.quantity} {instr.symbol} (~${instr.notional:,.2f}) -- {instr.reason}")

    if not args.live:
        print("\nDRY RUN -- no orders placed. Re-run with --live to actually submit these to the account "
              "tiger_client.get_client_config() is pointed at.")
        return

    if not approved_instructions:
        print("\nLIVE mode, but nothing to place.")
        return

    print("\nLIVE MODE -- placing orders now.")
    universe_by_symbol = {e.symbol: e for e in universe}
    for instr in approved_instructions:
        entry = universe_by_symbol[instr.symbol]
        contract = build_contract(instr.symbol, currency=entry.currency, exchange=entry.exchange)
        order = place_market_order(
            trade_client, account=client_config.account, contract=contract,
            action=instr.action, quantity=instr.quantity,
        )
        print(f"  Placed {instr.action} {instr.quantity} {instr.symbol} -> order id {order.id}")

    print("\nDone.")


if __name__ == "__main__":
    main()
