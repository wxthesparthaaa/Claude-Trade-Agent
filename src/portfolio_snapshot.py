"""
Refreshes a read-only cache of current Tiger positions for the dashboard
to display without hitting Tiger's API on every page view.

Hard boundary, enforced here by NOT importing it: this module must never
import tiger_order_adapter.place_market_order or execute_trades.main --
it only ever reads account state, never decides or places anything. If a
future change needs those, that's a sign it doesn't belong in this file.
"""
import json
from datetime import datetime, timezone
from typing import Dict, List

from state_paths import SNAPSHOT_PATH
from strategy_ledger import load_or_init_ledger, latest_capital, get_cash_reserve

INITIAL_CAPITAL = 1000.0


def build_snapshot(raw_positions: List, sleeve_by_symbol: Dict[str, str], ledger_path: str) -> dict:
    """
    Pure transform -- no network. raw_positions is whatever
    trade_client.get_positions() returned (or an equivalent list of
    objects with .contract.symbol, .quantity, .average_cost,
    .market_price, .market_value, .unrealized_pnl, .unrealized_pnl_percent).
    """
    positions = []
    for p in raw_positions or []:
        symbol = p.contract.symbol
        if symbol not in sleeve_by_symbol or not p.quantity or p.quantity <= 0:
            continue
        positions.append({
            "symbol": symbol,
            "sleeve": sleeve_by_symbol[symbol],
            "quantity": int(p.quantity),
            "average_cost": float(p.average_cost or 0.0),
            "market_price": float(p.market_price or 0.0),
            "market_value": float(p.market_value or 0.0),
            "unrealized_pnl": float(p.unrealized_pnl or 0.0),
            "unrealized_pnl_pct": float(p.unrealized_pnl_percent or 0.0),
        })

    ledger = load_or_init_ledger(ledger_path, INITIAL_CAPITAL)
    total_invested = sum(pos["market_value"] for pos in positions)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "positions": positions,
        "total_capital": latest_capital(ledger),
        "cash_reserve": get_cash_reserve(ledger),
        "total_invested": total_invested,
    }


def refresh_snapshot(trade_client, universe, ledger_path: str, path: str = SNAPSHOT_PATH) -> dict:
    """The only function here that touches the network -- everything else is pure."""
    sleeve_by_symbol = {e.symbol: e.sleeve for e in universe}
    raw_positions = trade_client.get_positions() or []
    snapshot = build_snapshot(raw_positions, sleeve_by_symbol, ledger_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    return snapshot


def load_snapshot(path: str = SNAPSHOT_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
