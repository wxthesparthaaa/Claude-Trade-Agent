"""
Tracks the strategy's own capital (starting at $1,000) separately from
whatever Tiger's paper account balance actually is -- the paper account
defaults to $1,000,000 in sandbox cash, which has nothing to do with the
capital this strategy is meant to manage.

Total capital = cash_reserve + current market value of held positions.
A trade converts cash into stock value (or back) without changing total
equity, except for the real commission cost -- so cash_reserve is tracked
as its own running figure, only moved by apply_trade_and_snapshot() at
the moment a trade executes, while the daily "capital" history reflects
mark-to-market total equity at each snapshot. Before any trade exists,
cash_reserve == initial_capital and positions value is zero, so capital
stays flat -- exactly the placeholder behavior this module had before any
real trade existed.
"""
import json
import os
from datetime import date
from typing import Optional


def load_or_init_ledger(path: str, initial_capital: float) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    ledger = {
        "cash_reserve": initial_capital,
        "history": [{"date": date.today().isoformat(), "capital": initial_capital}],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    return ledger


def record_snapshot(path: str, capital: float, as_of: Optional[str] = None) -> dict:
    """Appends a capital snapshot without touching cash_reserve -- used when
    no trade happened (e.g. a daily carry-forward or a mark-to-market-only
    update)."""
    as_of = as_of or date.today().isoformat()
    ledger = {"history": []}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            ledger = json.load(f)
    ledger["history"].append({"date": as_of, "capital": capital})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    return ledger


def get_cash_reserve(ledger: dict) -> float:
    """Falls back to the latest capital snapshot for ledgers written before
    cash_reserve existed (treats them as fully uninvested at that point)."""
    if "cash_reserve" in ledger:
        return ledger["cash_reserve"]
    return latest_capital(ledger)


def apply_trade_and_snapshot(
    path: str, cash_delta: float, positions_value_now: float, as_of: Optional[str] = None
) -> dict:
    """
    Call this once, right after a batch of orders is placed and filled.

    cash_delta: net change to cash_reserve from this batch (negative for
        buys including commission, positive for sells net of commission).
    positions_value_now: total market value of ALL currently held
        positions, refetched fresh -- not analytically derived, so it
        reflects real fills and any price movement since scoring.
    """
    as_of = as_of or date.today().isoformat()
    ledger = {"history": []}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            ledger = json.load(f)

    new_cash_reserve = get_cash_reserve(ledger) + cash_delta
    new_capital = new_cash_reserve + positions_value_now

    ledger["cash_reserve"] = new_cash_reserve
    ledger["history"].append({"date": as_of, "capital": new_capital})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    return ledger


def mark_to_market_snapshot(path: str, positions_value_now: float, as_of: Optional[str] = None) -> dict:
    """
    Re-anchors today's capital to reflect current market prices without a
    trade -- cash_reserve is unchanged, only the positions portion is
    repriced. This is what the daily report calls every day so capital
    actually moves with the market, not just at trade time.
    """
    return apply_trade_and_snapshot(path, cash_delta=0.0, positions_value_now=positions_value_now, as_of=as_of)


def latest_capital(ledger: dict) -> float:
    if not ledger["history"]:
        raise ValueError("Ledger has no history")
    return ledger["history"][-1]["capital"]


def capital_n_entries_ago(ledger: dict, n: int) -> float:
    """
    Capital as of n snapshots before the latest one (n=1 -> previous entry).
    Clamps to the oldest entry if history is shorter than requested.
    """
    history = ledger["history"]
    if not history:
        raise ValueError("Ledger has no history")
    idx = max(0, len(history) - 1 - n)
    return history[idx]["capital"]
