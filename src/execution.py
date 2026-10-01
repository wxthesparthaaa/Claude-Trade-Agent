"""
Reconciles the strategy's target portfolio (from portfolio_construction)
against actual current Tiger positions, and produces concrete order
instructions -- buys for new/increased target positions, sells for
decreased or dropped ones.

This is pure logic: it decides WHAT orders should be placed, not how to
place them (that's tiger_order_adapter.py, the only module that actually
calls Tiger's order API) or whether they're allowed (every instruction here
still has to pass risk_engine.validate_trade() before it's placed -- this
module doesn't check risk limits itself).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from portfolio_construction import PlannedPosition


@dataclass
class CurrentPosition:
    symbol: str
    quantity: int
    average_cost: float


@dataclass
class OrderInstruction:
    symbol: str
    action: str    # "BUY" | "SELL"
    quantity: int
    notional: float
    reason: str


def round_to_lot(raw_quantity: float, lot_size: int) -> int:
    """
    Floors to the nearest whole number of board lots -- deliberately never
    rounds up in magnitude. Rounding to nearest could push a position's
    actual notional above its target (and therefore above a risk cap it
    was sized to respect) purely from rounding, which would then get the
    whole order rejected by the risk engine instead of a slightly smaller
    one going through. Undershooting a target by less than one lot is far
    more benign than that.

    Sign-aware: a negative raw_quantity represents a short target (see
    reconcile_positions) -- floors the magnitude and reapplies the sign,
    rather than the earlier behavior of collapsing any negative input to
    zero (which would have killed short-position sizing entirely).
    """
    lot_size = lot_size if lot_size > 0 else 1
    sign = -1 if raw_quantity < 0 else 1
    lots = int(abs(raw_quantity) // lot_size)
    return sign * lots * lot_size


def reconcile_positions(
    target_positions: List[PlannedPosition],
    current_positions: Dict[str, CurrentPosition],
    prices: Dict[str, float],
    lot_size_by_symbol: Optional[Dict[str, int]] = None,
    rebalance_band_pct: float = 0.0,
) -> List[OrderInstruction]:
    """
    target_positions: this rebalance's desired holdings (from
        portfolio_construction.allocate_portfolio).
    current_positions: {symbol: CurrentPosition} for whatever Tiger
        actually reports is held right now.
    prices: {symbol: latest price}, used to convert target notional into a
        target share quantity.
    lot_size_by_symbol: missing symbols default to a lot size of 1 (US-style).
    rebalance_band_pct: for a symbol ALREADY held and still a target,
        skip trimming/topping-up if its current notional is within this
        fraction of target_notional (e.g. 0.20 = leave it alone while
        between 80%-120% of target) -- defaults to 0.0 (no band, exact
        match every time), so every existing caller is unaffected. A
        brand-new entry (not currently held) always goes through
        regardless of the band; this only throttles re-trimming a
        position that's already basically at target. Added after a real
        incident: with no band, re-targeting to the EXACT dollar target
        on every single scan generated dozens of 1-4 share trims per
        symbol per month (see decision_log.json's "reduce/increase
        toward target X% of capital" entries), each paying close to a
        flat per-order commission -- confirmed live, growth paid $146 in
        commissions against a total realized trading loss of $126 over
        the same window; the fee drag alone exceeded the entire P&L.
    """
    lot_size_by_symbol = lot_size_by_symbol or {}
    instructions: List[OrderInstruction] = []
    target_symbols = set()

    for target in target_positions:
        price = prices.get(target.symbol)
        if price is None or price <= 0:
            continue
        target_symbols.add(target.symbol)

        lot_size = lot_size_by_symbol.get(target.symbol, 1)
        target_qty = round_to_lot(target.target_notional / price, lot_size)
        current_position = current_positions.get(target.symbol, CurrentPosition(target.symbol, 0, 0.0))
        current_qty = current_position.quantity
        delta = target_qty - current_qty

        if delta != 0 and current_qty != 0 and rebalance_band_pct > 0:
            current_notional = current_qty * price
            drift = abs(current_notional - target.target_notional)
            if drift <= abs(target.target_notional) * rebalance_band_pct:
                continue  # already close enough to target -- leave it alone

        if delta > 0:
            instructions.append(OrderInstruction(
                symbol=target.symbol, action="BUY", quantity=delta, notional=delta * price,
                reason=f"increase toward target {target.target_pct:.0%} of capital ({target.sleeve})",
            ))
        elif delta < 0:
            instructions.append(OrderInstruction(
                symbol=target.symbol, action="SELL", quantity=-delta, notional=-delta * price,
                reason=f"reduce toward target {target.target_pct:.0%} of capital ({target.sleeve})",
            ))

    for symbol, position in current_positions.items():
        if symbol in target_symbols or position.quantity == 0:
            continue
        price = prices.get(symbol, position.average_cost)
        if position.quantity > 0:
            instructions.append(OrderInstruction(
                symbol=symbol, action="SELL", quantity=position.quantity, notional=position.quantity * price,
                reason="no longer a target position -- full exit",
            ))
        else:
            qty = -position.quantity
            instructions.append(OrderInstruction(
                symbol=symbol, action="BUY", quantity=qty, notional=qty * price,
                reason="no longer a target position -- full cover",
            ))

    return instructions
