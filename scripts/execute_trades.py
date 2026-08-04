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
import time
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
from strategy_ledger import load_or_init_ledger, latest_capital, apply_trade_and_snapshot
from telegram_notifier import get_telegram_config, send_message, format_order_placed_update
from state_paths import REGIME_PATH, NEWS_PATH, DECISION_LOG_PATH, LEDGER_PATH
from github_state_sync import pull_state_from_github, push_state_to_github

INITIAL_CAPITAL = 1000.0
MOMENTUM_LOOKBACK_DAYS = 126
MOMENTUM_SKIP_DAYS = 21

_MARKET_ENUM = {"US": Market.US, "HK": Market.HK, "SG": Market.SG}
_SLEEVE_TO_STRATEGY = {"core": "core_hold", "satellite": "satellite_momentum"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                         help="Actually place orders. Without this flag, computes and prints only.")
    args = parser.parse_args()

    pulled = pull_state_from_github()
    if pulled:
        print(f"Pulled {pulled} state file(s) from GitHub before starting.\n")

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
    affordable_candidates = all_candidates
    if lot_infos and all_candidates:
        affordable_symbols = set(filter_affordable_by_lot(
            symbol_prices={c.symbol: c.price for c in all_candidates},
            lot_infos=lot_infos, available_capital=capital, max_position_pct=config.max_single_position_pct,
        ))
        affordable_candidates = [c for c in all_candidates if c.symbol in affordable_symbols]

    planned = allocate_portfolio(affordable_candidates, config, capital=capital, regime_tilts=regime_tilts)

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
    planned_symbols = {p.symbol for p in planned}

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

    # First: gate the actual order instructions through the risk engine --
    # this determines which orders get placed, independent of the fuller
    # rationale trail built below.
    instruction_outcomes = {}  # symbol -> (action, reason)
    approved_instructions = []
    for instr in instructions:
        sleeve = sleeve_by_symbol.get(instr.symbol, "unknown")
        if halted:
            instruction_outcomes[instr.symbol] = ("reject", "risk engine drawdown halt is active -- no new orders")
            continue
        strategy_key = _SLEEVE_TO_STRATEGY.get(sleeve, "core_hold")
        try:
            risk_engine.validate_trade(state, strategy_key, instr.notional)
            approved_instructions.append(instr)
            action = "buy" if instr.action == "BUY" else "sell"
            instruction_outcomes[instr.symbol] = (action, exit_reasons.get(instr.symbol, instr.reason))
        except RiskViolation as e:
            instruction_outcomes[instr.symbol] = ("reject", f"risk engine blocked: {e}")

    # Then: a full rationale trail for every scored candidate today (buy/
    # hold/reject), not just the ones that needed a new order -- mirrors
    # stock_backtest.py's decision log so "why" is answered for a no-change
    # day too, not just when something actually moves.
    decisions = []
    affordable_symbols_set = {c.symbol for c in affordable_candidates}
    for c in all_candidates:
        if c.symbol in instruction_outcomes:
            action, reason = instruction_outcomes[c.symbol]
            decisions.append(DecisionRecord(date=str(date.today()), action=action, symbol=c.symbol,
                                             sleeve=c.sleeve, reason=reason, score=c.score))
        elif c.symbol not in affordable_symbols_set:
            decisions.append(DecisionRecord(
                date=str(date.today()), action="reject", symbol=c.symbol, sleeve=c.sleeve,
                reason=f"board lot unaffordable at current equity ${capital:,.0f}", score=c.score,
            ))
        elif c.symbol in planned_symbols:
            action = "hold" if c.symbol in current_positions else "buy"
            decisions.append(DecisionRecord(date=str(date.today()), action=action, symbol=c.symbol,
                                             sleeve=c.sleeve, reason=f"top {c.sleeve} pick this period", score=c.score))
        else:
            decisions.append(DecisionRecord(
                date=str(date.today()), action="reject", symbol=c.symbol, sleeve=c.sleeve,
                reason=f"ranked below the {c.sleeve} sleeve's position cap", score=c.score,
            ))

    for symbol, reason in exit_reasons.items():
        if symbol not in instruction_outcomes:
            decisions.append(DecisionRecord(date=str(date.today()), action="sell", symbol=symbol,
                                             sleeve=sleeve_by_symbol.get(symbol, "unknown"), reason=reason))

    candidate_symbols = {c.symbol for c in all_candidates}
    for symbol in current_positions:
        if symbol in instruction_outcomes or symbol in exit_reasons or symbol in candidate_symbols:
            continue
        decisions.append(DecisionRecord(
            date=str(date.today()), action="sell", symbol=symbol, sleeve=sleeve_by_symbol.get(symbol, "unknown"),
            reason="dropped -- no longer eligible (insufficient history/momentum data today)",
        ))

    write_decision_log(DECISION_LOG_PATH, str(date.today()), decisions)
    push_state_to_github(DECISION_LOG_PATH)
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
    successfully_placed = []
    placed_order_ids = []
    for instr in approved_instructions:
        entry = universe_by_symbol[instr.symbol]
        contract = build_contract(instr.symbol, currency=entry.currency, exchange=entry.exchange)
        order = place_market_order(
            trade_client, account=client_config.account, contract=contract,
            action=instr.action, quantity=instr.quantity,
        )
        print(f"  Placed {instr.action} {instr.quantity} {instr.symbol} -> order id {order.id}")
        successfully_placed.append(instr)
        placed_order_ids.append(order.id)

    # Give the paper account a moment to report fills, then pull the real
    # fill price + commission per order rather than the sizing-time estimate.
    time.sleep(2)
    orders_by_id = {o.id: o for o in (trade_client.get_orders() or [])}

    cash_delta = 0.0
    for instr, order_id in zip(successfully_placed, placed_order_ids):
        filled = orders_by_id.get(order_id)
        if filled is not None and filled.status == "FILLED" and filled.filled_cash_amount is not None:
            cash_amount = filled.filled_cash_amount + (filled.commission or 0.0)
        else:
            cash_amount = instr.notional  # fallback: sizing-time estimate if fill data isn't ready yet
        cash_delta += -cash_amount if instr.action == "BUY" else cash_amount

    raw_positions_after = trade_client.get_positions() or []
    total_invested_after = sum(
        p.market_value for p in raw_positions_after
        if p.contract.symbol in sleeve_by_symbol and p.market_value
    )

    ledger = apply_trade_and_snapshot(LEDGER_PATH, cash_delta=cash_delta, positions_value_now=total_invested_after)
    push_state_to_github(LEDGER_PATH)
    print(f"\nLedger updated: cash_reserve=${ledger['cash_reserve']:,.2f}, "
          f"total capital=${latest_capital(ledger):,.2f}")

    notification_text = format_order_placed_update(successfully_placed, capital, total_invested_after)
    print(f"\n{notification_text}")

    try:
        telegram_config = get_telegram_config()
        send_message(notification_text, telegram_config.bot_token, telegram_config.chat_id)
        print("\nSent order confirmation to Telegram.")
    except FileNotFoundError as e:
        print(f"\nTelegram not configured, skipping notification: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
