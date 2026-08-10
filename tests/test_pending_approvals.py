"""
Run with:
    pytest tests/test_pending_approvals.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from pending_approvals import (
    build_pending_approvals, write_pending_approvals, load_pending_approvals,
    find_pending_approval, remove_pending_approval,
)
from scan_workflow import ScanResult
from portfolio_construction import ScoredCandidate, PlannedPosition
from execution import OrderInstruction, CurrentPosition
from universe import UniverseEntry


def make_scan_result(**overrides):
    defaults = dict(
        profile_name="growth",
        as_of="2026-08-06",
        universe=[UniverseEntry("NVDA", "US", "USD", "", "satellite")],
        sleeve_by_symbol={"NVDA": "satellite"},
        all_candidates=[ScoredCandidate(symbol="NVDA", sleeve="satellite", score=0.42, price=200.0)],
        affordable_candidates=[ScoredCandidate(symbol="NVDA", sleeve="satellite", score=0.42, price=200.0)],
        planned=[PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=350.0, target_pct=0.35)],
        current_positions={},
        price_by_symbol={"NVDA": 200.0},
        exit_reasons={},
        instructions=[OrderInstruction("NVDA", "BUY", 1, 200.0, "top satellite pick")],
        instruction_outcomes={"NVDA": ("buy", "top satellite pick")},
        approved_instructions=[OrderInstruction("NVDA", "BUY", 1, 200.0, "top satellite pick")],
        decisions=[],
        capital=1000.0,
        halted=False,
        halt_reason=None,
    )
    defaults.update(overrides)
    return ScanResult(**defaults)


def test_build_pending_approvals_basic_fields():
    result = make_scan_result()
    items = build_pending_approvals(result)
    assert len(items) == 1
    item = items[0]
    assert item.id == "2026-08-06-NVDA-BUY"
    assert item.symbol == "NVDA"
    assert item.action == "BUY"
    assert item.sleeve == "satellite"
    assert item.strategy_key == "satellite_momentum"
    assert item.score == 0.42
    assert item.currency == "USD"
    assert item.target_pct == 0.35
    assert item.current_position_qty == 0
    assert item.position_type == "long"


def test_build_pending_approvals_includes_confidence_when_present():
    result = make_scan_result(confidence_by_symbol={"NVDA": 81.4})
    item = build_pending_approvals(result)[0]
    assert item.confidence_pct == 81.4


def test_build_pending_approvals_confidence_defaults_to_none():
    result = make_scan_result()  # confidence_by_symbol defaults to {} (confidence gating off)
    item = build_pending_approvals(result)[0]
    assert item.confidence_pct is None


def test_build_pending_approvals_labels_a_short_open():
    result = make_scan_result(
        planned=[PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=-150.0, target_pct=-0.15)],
        instructions=[OrderInstruction("NVDA", "SELL", 1, 200.0, "increase toward target -15% of capital")],
        approved_instructions=[OrderInstruction("NVDA", "SELL", 1, 200.0, "increase toward target -15% of capital")],
        current_positions={},
    )
    item = build_pending_approvals(result)[0]
    assert item.position_type == "short"
    assert item.strategy_key == "satellite_short"
    assert item.action == "SELL"


def test_build_pending_approvals_labels_a_cover():
    result = make_scan_result(
        planned=[],
        current_positions={"NVDA": CurrentPosition("NVDA", quantity=-3, average_cost=200.0)},
        instructions=[OrderInstruction("NVDA", "BUY", 3, 600.0, "no longer a target position -- full cover")],
        approved_instructions=[OrderInstruction("NVDA", "BUY", 3, 600.0, "no longer a target position -- full cover")],
    )
    item = build_pending_approvals(result)[0]
    assert item.position_type == "cover"
    assert item.strategy_key == "satellite_short"
    assert item.current_position_qty == -3


def test_build_pending_approvals_utilization_uses_absolute_value_for_shorts():
    # A short's negative target_notional must ADD to utilization, not net
    # against a long position's positive notional.
    result = make_scan_result(
        planned=[
            PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=350.0, target_pct=0.35),
            PlannedPosition(symbol="AMD", sleeve="satellite", target_notional=-150.0, target_pct=-0.15),
        ],
    )
    items = build_pending_approvals(result, max_capital_at_risk=1000.0)
    assert items[0].projected_total_utilization_pct == pytest.approx((350.0 + 150.0) / 1000.0)


def test_build_pending_approvals_uses_caller_supplied_capital_cap():
    # e.g. the dividend profile's $30,000 cap, not RiskConfig()'s $1,000 default.
    result = make_scan_result(
        planned=[PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=3500.0, target_pct=0.35)],
    )
    items = build_pending_approvals(result, max_capital_at_risk=30000.0)
    assert items[0].projected_total_utilization_pct == pytest.approx(3500.0 / 30000.0)


def test_build_pending_approvals_uses_current_position_qty():
    result = make_scan_result(current_positions={"NVDA": CurrentPosition("NVDA", quantity=3, average_cost=190.0)})
    items = build_pending_approvals(result)
    assert items[0].current_position_qty == 3


def test_build_pending_approvals_computes_projected_utilization():
    result = make_scan_result()
    items = build_pending_approvals(result)
    from risk_engine import RiskConfig
    expected = 350.0 / RiskConfig().max_capital_at_risk
    assert items[0].projected_total_utilization_pct == expected


def test_build_pending_approvals_empty_when_no_approved_instructions():
    result = make_scan_result(approved_instructions=[])
    assert build_pending_approvals(result) == []


def test_write_and_load_pending_approvals_round_trip(tmp_path):
    path = str(tmp_path / "pending_approvals.json")
    items = build_pending_approvals(make_scan_result())
    write_pending_approvals(path, items, scan_id="2026-08-06")

    data = load_pending_approvals(path)
    assert data["scan_id"] == "2026-08-06"
    assert len(data["items"]) == 1
    assert data["items"][0]["symbol"] == "NVDA"


def test_load_pending_approvals_returns_empty_when_no_file(tmp_path):
    data = load_pending_approvals(str(tmp_path / "does_not_exist.json"))
    assert data == {"scan_id": None, "items": []}


def test_find_pending_approval_locates_by_id(tmp_path):
    path = str(tmp_path / "pending_approvals.json")
    write_pending_approvals(path, build_pending_approvals(make_scan_result()), scan_id="2026-08-06")
    found = find_pending_approval(path, "2026-08-06-NVDA-BUY")
    assert found is not None
    assert found["symbol"] == "NVDA"


def test_find_pending_approval_returns_none_when_missing(tmp_path):
    path = str(tmp_path / "pending_approvals.json")
    write_pending_approvals(path, build_pending_approvals(make_scan_result()), scan_id="2026-08-06")
    assert find_pending_approval(path, "does-not-exist") is None


def test_remove_pending_approval_removes_only_matching_item(tmp_path):
    path = str(tmp_path / "pending_approvals.json")
    result = make_scan_result(
        all_candidates=[
            ScoredCandidate(symbol="NVDA", sleeve="satellite", score=0.42, price=200.0),
            ScoredCandidate(symbol="AMD", sleeve="satellite", score=0.30, price=150.0),
        ],
        planned=[
            PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=350.0, target_pct=0.35),
            PlannedPosition(symbol="AMD", sleeve="satellite", target_notional=250.0, target_pct=0.25),
        ],
        price_by_symbol={"NVDA": 200.0, "AMD": 150.0},
        approved_instructions=[
            OrderInstruction("NVDA", "BUY", 1, 200.0, "top pick"),
            OrderInstruction("AMD", "BUY", 1, 150.0, "second pick"),
        ],
    )
    write_pending_approvals(path, build_pending_approvals(result), scan_id="2026-08-06")

    data = remove_pending_approval(path, "2026-08-06-NVDA-BUY")
    remaining_ids = {i["id"] for i in data["items"]}
    assert remaining_ids == {"2026-08-06-AMD-BUY"}

    reloaded = load_pending_approvals(path)
    assert {i["id"] for i in reloaded["items"]} == {"2026-08-06-AMD-BUY"}
