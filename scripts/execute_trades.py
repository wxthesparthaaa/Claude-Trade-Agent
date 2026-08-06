"""
Run with:
    python scripts/execute_trades.py           (dry run -- computes and prints only)
    python scripts/execute_trades.py --live    (actually places orders against Tiger)

Thin CLI wrapper around src/scan_workflow.py::run_scan() (scoring, exit
checks, target allocation, reconciliation, risk-gating, decision log --
the same computation the automated daily scan and the dashboard's "Scan
Now" button use) and src/order_execution.py::execute_instructions() (the
only code path that places a real order, shared with the dashboard's
single-instruction /approve/<id> route).

Defaults to a dry run: everything is computed, scored, and logged, but no
order is placed unless --live is passed. This script targets whatever
account tiger_client.get_client_config() is pointed at -- verify that's
still the paper account before ever passing --live.
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.trade.trade_client import TradeClient

from scan_workflow import run_scan
from order_execution import execute_instructions
from decision_log import format_decision_summary, write_decision_log
from state_paths import DECISION_LOG_PATH
from github_state_sync import pull_state_from_github, push_state_to_github


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

    print(f"Scoring candidates as of today...")
    result = run_scan(quote_client, trade_client)

    if result.halted:
        print(f"\n*** RISK ENGINE HALT: {result.halt_reason} ***\n")

    write_decision_log(DECISION_LOG_PATH, result.as_of, result.decisions)
    push_state_to_github(DECISION_LOG_PATH)
    print(format_decision_summary(result.as_of, result.decisions))

    print(f"\n{len(result.approved_instructions)} order(s) approved to place:")
    for instr in result.approved_instructions:
        print(f"  {instr.action} {instr.quantity} {instr.symbol} (~${instr.notional:,.2f}) -- {instr.reason}")

    if not args.live:
        print("\nDRY RUN -- no orders placed. Re-run with --live to actually submit these to the account "
              "tiger_client.get_client_config() is pointed at.")
        return

    if not result.approved_instructions:
        print("\nLIVE mode, but nothing to place.")
        return

    print("\nLIVE MODE -- placing orders now.")
    universe_by_symbol = {e.symbol: e for e in result.universe}
    execution = execute_instructions(
        trade_client, client_config, universe_by_symbol, result.approved_instructions,
        result.sleeve_by_symbol, result.capital,
    )
    for instr, order_id in zip(execution.placed, execution.order_ids):
        print(f"  Placed {instr.action} {instr.quantity} {instr.symbol} -> order id {order_id}")

    print(f"\nLedger updated: total capital=${execution.new_capital:,.2f}")
    print(f"\n{execution.telegram_text}")
    print("\nSent order confirmation to Telegram." if execution.telegram_sent
          else "\nTelegram not configured, skipping notification.")

    print("\nDone.")


if __name__ == "__main__":
    main()
