"""
Run with:
    pytest tests/test_execution.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from execution import reconcile_positions, round_to_lot, CurrentPosition, OrderInstruction
from portfolio_construction import PlannedPosition


def test_round_to_lot_floors_never_rounds_up():
    assert round_to_lot(9.4, lot_size=1) == 9
    assert round_to_lot(260.0, lot_size=100) == 200  # 2.6 lots -> floors to 2 lots, never up to 3
    assert round_to_lot(149.0, lot_size=100) == 100


def test_round_to_lot_negative_input_floors_magnitude_and_keeps_sign():
    # Negative raw_quantity represents a short target (see reconcile_positions
    # below) -- deliberately no longer collapses to zero; floors the magnitude
    # to a lot and reapplies the sign, same floor-never-round-up discipline as
    # the positive case.
    assert round_to_lot(-5.0, lot_size=1) == -5
    assert round_to_lot(-260.0, lot_size=100) == -200  # -2.6 lots -> floors magnitude to 2 lots
    assert round_to_lot(-149.0, lot_size=100) == -100


def test_round_to_lot_defaults_zero_lot_size_to_one():
    assert round_to_lot(5.0, lot_size=0) == 5


def test_reconcile_new_position_produces_buy():
    # raw target qty = 350/100 = 3.5 shares -> floors to 3, never rounds up to 4
    # (which would exceed the $350 target the caller sized this position to).
    targets = [PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=350.0, target_pct=0.35)]
    instructions = reconcile_positions(targets, current_positions={}, prices={"NVDA": 100.0})
    assert len(instructions) == 1
    assert instructions[0] == OrderInstruction("NVDA", "BUY", 3, 300.0, instructions[0].reason)


def test_reconcile_increasing_position_produces_partial_buy():
    targets = [PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=500.0, target_pct=0.5)]
    current = {"NVDA": CurrentPosition("NVDA", quantity=2, average_cost=90.0)}
    instructions = reconcile_positions(targets, current, prices={"NVDA": 100.0})
    assert len(instructions) == 1
    assert instructions[0].action == "BUY"
    assert instructions[0].quantity == 3  # target 5 shares - current 2 = 3


def test_reconcile_decreasing_position_produces_sell():
    targets = [PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=100.0, target_pct=0.1)]
    current = {"NVDA": CurrentPosition("NVDA", quantity=5, average_cost=90.0)}
    instructions = reconcile_positions(targets, current, prices={"NVDA": 100.0})
    assert len(instructions) == 1
    assert instructions[0].action == "SELL"
    assert instructions[0].quantity == 4  # current 5 - target 1 = 4


def test_reconcile_dropped_position_produces_full_exit():
    current = {"AMD": CurrentPosition("AMD", quantity=3, average_cost=150.0)}
    instructions = reconcile_positions([], current, prices={"AMD": 160.0})
    assert len(instructions) == 1
    assert instructions[0].action == "SELL"
    assert instructions[0].quantity == 3
    assert "no longer a target" in instructions[0].reason


def test_reconcile_no_change_produces_no_instructions():
    targets = [PlannedPosition(symbol="NVDA", sleeve="satellite", target_notional=500.0, target_pct=0.5)]
    current = {"NVDA": CurrentPosition("NVDA", quantity=5, average_cost=90.0)}
    instructions = reconcile_positions(targets, current, prices={"NVDA": 100.0})
    assert instructions == []


def test_reconcile_skips_target_with_missing_price():
    targets = [PlannedPosition(symbol="UNKNOWN", sleeve="core", target_notional=100.0, target_pct=0.1)]
    instructions = reconcile_positions(targets, {}, prices={})
    assert instructions == []


def test_reconcile_respects_lot_size():
    # raw target qty = 6000/50 = 120 shares -> 1.2 lots of 100 -> floors to 1 lot (100 shares)
    targets = [PlannedPosition(symbol="00700", sleeve="satellite", target_notional=6000.0, target_pct=0.35)]
    instructions = reconcile_positions(
        targets, current_positions={}, prices={"00700": 50.0}, lot_size_by_symbol={"00700": 100}
    )
    assert len(instructions) == 1
    assert instructions[0].quantity == 100


def test_reconcile_lot_size_can_round_down_to_zero():
    # raw target qty = 350/50 = 7 shares -> 0.07 lots of 100 -> rounds down to 0 -> no order
    targets = [PlannedPosition(symbol="00700", sleeve="satellite", target_notional=350.0, target_pct=0.35)]
    instructions = reconcile_positions(
        targets, current_positions={}, prices={"00700": 50.0}, lot_size_by_symbol={"00700": 100}
    )
    assert instructions == []


def test_reconcile_zero_quantity_current_position_not_treated_as_dropped():
    current = {"AMD": CurrentPosition("AMD", quantity=0, average_cost=150.0)}
    instructions = reconcile_positions([], current, prices={"AMD": 160.0})
    assert instructions == []


def test_reconcile_negative_target_notional_opens_a_short_via_sell():
    # A short candidate is expressed as a NEGATIVE target_notional (see
    # scan_workflow's short-candidate pass) -- opening one from flat is a
    # plain SELL, mechanically identical to Tiger's own BUY/SELL-only API.
    targets = [PlannedPosition(symbol="AMD", sleeve="satellite", target_notional=-150.0, target_pct=-0.15)]
    instructions = reconcile_positions(targets, current_positions={}, prices={"AMD": 50.0})
    assert len(instructions) == 1
    assert instructions[0].action == "SELL"
    assert instructions[0].quantity == 3
    assert instructions[0].notional == 150.0


def test_reconcile_increasing_a_short_produces_additional_sell():
    targets = [PlannedPosition(symbol="AMD", sleeve="satellite", target_notional=-250.0, target_pct=-0.25)]
    current = {"AMD": CurrentPosition("AMD", quantity=-3, average_cost=50.0)}
    instructions = reconcile_positions(targets, current, prices={"AMD": 50.0})
    assert len(instructions) == 1
    assert instructions[0].action == "SELL"
    assert instructions[0].quantity == 2  # target -5 - current -3 = -2 -> SELL 2 more


def test_reconcile_partial_cover_produces_buy():
    targets = [PlannedPosition(symbol="AMD", sleeve="satellite", target_notional=-50.0, target_pct=-0.05)]
    current = {"AMD": CurrentPosition("AMD", quantity=-3, average_cost=50.0)}
    instructions = reconcile_positions(targets, current, prices={"AMD": 50.0})
    assert len(instructions) == 1
    assert instructions[0].action == "BUY"
    assert instructions[0].quantity == 2  # target -1 - current -3 = 2 -> BUY 2 to partially cover


def test_reconcile_dropped_short_produces_full_cover_via_buy():
    current = {"AMD": CurrentPosition("AMD", quantity=-3, average_cost=150.0)}
    instructions = reconcile_positions([], current, prices={"AMD": 160.0})
    assert len(instructions) == 1
    assert instructions[0].action == "BUY"
    assert instructions[0].quantity == 3
    assert "full cover" in instructions[0].reason
