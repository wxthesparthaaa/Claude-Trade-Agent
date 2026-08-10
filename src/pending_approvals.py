"""
Builds the "pending approvals" list from a scan result -- the actionable
buy/sell instructions a human can review (rationale + projected impact)
on the dashboard and approve individually. The whole file is replaced by
each scan, since prices/targets/current positions are only valid as of
that scan -- an unapproved item from a prior scan is superseded, not
merged, once a fresh scan runs.
"""
import json
import os
from dataclasses import dataclass, asdict
from typing import List, Optional

from risk_engine import RiskConfig

_SLEEVE_TO_STRATEGY = {"core": "core_hold", "satellite": "satellite_momentum"}
_SHORT_STRATEGY_KEY = "satellite_short"


@dataclass
class PendingApproval:
    id: str
    symbol: str
    action: str
    quantity: int
    notional: float
    reason: str
    sleeve: str
    strategy_key: str
    score: Optional[float]
    currency: str
    exchange: str
    price_at_scan: float
    current_position_qty: int
    target_pct: Optional[float]
    capital_at_scan: float
    projected_position_pct: float
    projected_total_utilization_pct: float
    position_type: str = "long"   # "long" | "short" | "cover" -- for dashboard/review badging only,
                                   # not a distinct order type (see order_execution.py's docstring)
    confidence_pct: Optional[float] = None  # None unless the scanned profile has confidence gating on (growth)


def _position_type(action: str, current_qty: int) -> str:
    if action == "SELL" and current_qty <= 0:
        return "short"    # opening or adding to a short (current_qty is 0 or already negative)
    if action == "BUY" and current_qty < 0:
        return "cover"    # buying back a short, partially or in full
    return "long"


def build_pending_approvals(scan_result, max_capital_at_risk: Optional[float] = None) -> List[PendingApproval]:
    """
    scan_result: a scan_workflow.ScanResult. max_capital_at_risk should be
    the scanned profile's own risk_config.max_capital_at_risk (defaults to
    RiskConfig()'s default only for callers that don't have a profile in
    scope, e.g. older tests) -- using the wrong cap here would misreport
    utilization for any profile whose cap isn't the $1,000 default (the
    dividend portfolio's is $30,000).
    """
    max_cap = max_capital_at_risk if max_capital_at_risk is not None else RiskConfig().max_capital_at_risk
    target_pct_by_symbol = {p.symbol: p.target_pct for p in scan_result.planned}
    score_by_symbol = {c.symbol: c.score for c in scan_result.all_candidates}
    # abs() -- a short's negative target_notional must ADD to total exposure/utilization,
    # not net against the long side's positive notional.
    total_planned_notional = sum(abs(p.target_notional) for p in scan_result.planned)
    projected_total_utilization_pct = total_planned_notional / max_cap if max_cap else 0.0
    universe_by_symbol = {e.symbol: e for e in scan_result.universe}

    items = []
    for instr in scan_result.approved_instructions:
        entry = universe_by_symbol.get(instr.symbol)
        current_position = scan_result.current_positions.get(instr.symbol)
        current_qty = current_position.quantity if current_position else 0
        sleeve = scan_result.sleeve_by_symbol.get(instr.symbol, "unknown")
        target_pct = target_pct_by_symbol.get(instr.symbol)
        position_type = _position_type(instr.action, current_qty)
        strategy_key = _SHORT_STRATEGY_KEY if position_type in ("short", "cover") else _SLEEVE_TO_STRATEGY.get(sleeve, "core_hold")

        items.append(PendingApproval(
            id=f"{scan_result.as_of}-{instr.symbol}-{instr.action}",
            symbol=instr.symbol,
            action=instr.action,
            quantity=instr.quantity,
            notional=instr.notional,
            reason=instr.reason,
            sleeve=sleeve,
            strategy_key=strategy_key,
            score=score_by_symbol.get(instr.symbol),
            currency=entry.currency if entry else "USD",
            exchange=entry.exchange if entry else "",
            price_at_scan=scan_result.price_by_symbol.get(instr.symbol, 0.0),
            current_position_qty=current_qty,
            target_pct=target_pct,
            capital_at_scan=scan_result.capital,
            projected_position_pct=target_pct or 0.0,
            projected_total_utilization_pct=projected_total_utilization_pct,
            position_type=position_type,
            confidence_pct=scan_result.confidence_by_symbol.get(instr.symbol),
        ))
    return items


def write_pending_approvals(path: str, items: List[PendingApproval], scan_id: str) -> None:
    data = {"scan_id": scan_id, "items": [asdict(i) for i in items]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_pending_approvals(path: str) -> dict:
    if not os.path.exists(path):
        return {"scan_id": None, "items": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_pending_approval(path: str, approval_id: str) -> Optional[dict]:
    data = load_pending_approvals(path)
    return next((i for i in data["items"] if i["id"] == approval_id), None)


def remove_pending_approval(path: str, approval_id: str) -> dict:
    data = load_pending_approvals(path)
    data["items"] = [i for i in data["items"] if i["id"] != approval_id]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data
