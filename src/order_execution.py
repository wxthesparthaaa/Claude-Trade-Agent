"""
Places one or more already risk-approved order instructions against
Tiger, updates the ledger with real fill data, and sends a Telegram
confirmation. This is the only code (besides tiger_order_adapter.py
itself) that ever calls place_market_order in response to an approved
instruction -- used identically by execute_trades.py's --live batch and
the dashboard's single-instruction /approve/<id> route (a list of one),
so there is exactly one place this sensitive logic lives, not two
independently-maintained copies of it.

Callers MUST have already validated every instruction through
risk_engine.validate_trade() -- this function does not re-check risk,
it only executes what's handed to it.
"""
import time
from dataclasses import dataclass
from typing import Dict, List

from tiger_order_adapter import build_contract, place_market_order
from strategy_ledger import apply_trade_and_snapshot, latest_capital
from telegram_notifier import get_telegram_config, send_message, format_order_placed_update
from state_paths import LEDGER_PATH
from github_state_sync import push_state_to_github, get_github_config


@dataclass
class ExecutionResult:
    placed: List
    order_ids: List
    cash_delta: float
    total_invested_after: float
    new_capital: float
    telegram_text: str
    telegram_sent: bool
    state_pushed: bool


def execute_instructions(
    trade_client,
    client_config,
    universe_by_symbol: Dict,
    instructions: List,
    sleeve_by_symbol: Dict[str, str],
    capital: float,
    ledger_path: str = LEDGER_PATH,
) -> ExecutionResult:
    placed = []
    order_ids = []
    for instr in instructions:
        entry = universe_by_symbol[instr.symbol]
        contract = build_contract(instr.symbol, currency=entry.currency, exchange=entry.exchange)
        order = place_market_order(
            trade_client, account=client_config.account, contract=contract,
            action=instr.action, quantity=instr.quantity,
        )
        placed.append(instr)
        order_ids.append(order.id)

    # Give the paper account a moment to report fills, then pull the real
    # fill price + commission per order rather than the sizing-time estimate.
    time.sleep(2)
    orders_by_id = {o.id: o for o in (trade_client.get_orders() or [])}

    cash_delta = 0.0
    for instr, order_id in zip(placed, order_ids):
        filled = orders_by_id.get(order_id)
        if filled is not None and filled.status == "FILLED" and filled.filled_cash_amount is not None:
            commission = filled.commission or 0.0
            # BUY: total cash outlay is the cost plus the fee (both reduce
            # cash). SELL: net proceeds are the sale amount MINUS the fee
            # (the fee is still a cost, just netted against what you
            # receive rather than added on top).
            if instr.action == "BUY":
                cash_delta -= filled.filled_cash_amount + commission
            else:
                cash_delta += filled.filled_cash_amount - commission
        else:
            # Fallback: sizing-time estimate if fill data isn't ready yet
            # -- commission is unknown in this case, so it's not modeled.
            cash_delta += -instr.notional if instr.action == "BUY" else instr.notional

    raw_positions_after = trade_client.get_positions() or []
    total_invested_after = sum(
        p.market_value for p in raw_positions_after
        if p.contract.symbol in sleeve_by_symbol and p.market_value
    )

    ledger = apply_trade_and_snapshot(ledger_path, cash_delta=cash_delta, positions_value_now=total_invested_after)
    state_pushed = push_state_to_github(ledger_path)
    if not state_pushed:
        print(
            "\n*** WARNING: the updated ledger was NOT pushed to GitHub after this trade "
            f"(cash_reserve is only correct in the local copy at {ledger_path} right now). "
            "GITHUB_TOKEN/GITHUB_REPO may not be set in this environment -- if so, the next "
            "process that reads state from GitHub (Render, or another local run) won't see "
            "this trade's effect on cash_reserve until it's pushed manually. This exact "
            "failure mode has caused a real ledger drift before. ***\n"
        )

    telegram_text = format_order_placed_update(placed, capital, total_invested_after)
    telegram_sent = False
    try:
        telegram_config = get_telegram_config()
        send_message(telegram_text, telegram_config.bot_token, telegram_config.chat_id)
        telegram_sent = True
    except FileNotFoundError:
        pass

    return ExecutionResult(
        placed=placed,
        order_ids=order_ids,
        cash_delta=cash_delta,
        total_invested_after=total_invested_after,
        new_capital=latest_capital(ledger),
        telegram_text=telegram_text,
        telegram_sent=telegram_sent,
        state_pushed=state_pushed,
    )
