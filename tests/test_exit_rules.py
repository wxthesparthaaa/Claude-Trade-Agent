"""
Run with:
    pytest tests/test_exit_rules.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from exit_rules import ExitConfig, check_stop_loss, check_momentum_reversal


def test_stop_loss_triggers_when_breached():
    decision = check_stop_loss(entry_price=100.0, current_price=83.0, config=ExitConfig(stop_loss_pct=0.15))
    assert decision.should_exit is True
    assert "stop_loss" in decision.reason


def test_stop_loss_does_not_trigger_within_bounds():
    decision = check_stop_loss(entry_price=100.0, current_price=90.0, config=ExitConfig(stop_loss_pct=0.15))
    assert decision.should_exit is False
    assert decision.reason is None


def test_stop_loss_exactly_at_threshold_triggers():
    decision = check_stop_loss(entry_price=100.0, current_price=85.0, config=ExitConfig(stop_loss_pct=0.15))
    assert decision.should_exit is True


def test_stop_loss_raises_on_nonpositive_entry():
    with pytest.raises(ValueError):
        check_stop_loss(entry_price=0.0, current_price=50.0, config=ExitConfig())


def test_momentum_reversal_triggers_below_threshold():
    decision = check_momentum_reversal(current_momentum=-0.10, config=ExitConfig(momentum_exit_threshold=-0.05))
    assert decision.should_exit is True
    assert "momentum_reversal" in decision.reason


def test_momentum_reversal_does_not_trigger_above_threshold():
    decision = check_momentum_reversal(current_momentum=0.02, config=ExitConfig(momentum_exit_threshold=-0.05))
    assert decision.should_exit is False
