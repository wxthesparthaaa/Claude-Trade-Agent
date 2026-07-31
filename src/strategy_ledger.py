"""
Tracks the strategy's own capital (starting at $1,000) separately from
whatever Tiger's paper account balance actually is -- the paper account
defaults to $1,000,000 in sandbox cash, which has nothing to do with the
capital this strategy is meant to manage. Until the order-execution module
exists, this ledger simply carries the last value forward (no trades are
being placed yet, so there's nothing to update it with) -- once real
(paper) trades exist, the execution layer is responsible for appending
realized snapshots here, not this module.
"""
import json
import os
from datetime import date
from typing import Optional


def load_or_init_ledger(path: str, initial_capital: float) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    ledger = {"history": [{"date": date.today().isoformat(), "capital": initial_capital}]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    return ledger


def record_snapshot(path: str, capital: float, as_of: Optional[str] = None) -> dict:
    as_of = as_of or date.today().isoformat()
    ledger = {"history": []}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            ledger = json.load(f)
    ledger["history"].append({"date": as_of, "capital": capital})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    return ledger


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
