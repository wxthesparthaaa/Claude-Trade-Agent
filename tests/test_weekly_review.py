"""
Run with:
    pytest tests/test_weekly_review.py -v
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from weekly_review import (
    compute_week_stats, propose_strategy_adjustments, append_to_changelog,
    WeekStats, ProposedChange, BOUNDED_PARAMETERS, MAX_WEEKLY_ADJUSTMENT,
)


def test_compute_week_stats_basic_math():
    stats = compute_week_stats(
        equity_curve=[1000.0, 1020.0, 1010.0],
        position_returns={"NVDA": 0.05, "SCHD": -0.01},
        target_monthly_pct=0.10,
        week_start="2026-07-27",
        week_end="2026-08-02",
    )
    assert stats.realized_pct == pytest.approx(0.01)
    assert stats.best_position == "NVDA"
    assert stats.worst_position == "SCHD"
    assert stats.max_intraweek_drawdown_pct == pytest.approx(round((1020.0 - 1010.0) / 1020.0, 4))


def test_compute_week_stats_raises_on_insufficient_data():
    with pytest.raises(ValueError):
        compute_week_stats([1000.0], {}, 0.10, "2026-07-27", "2026-08-02")


def test_compute_week_stats_handles_empty_positions():
    stats = compute_week_stats([1000.0, 1000.0], {}, 0.10, "2026-07-27", "2026-08-02")
    assert stats.best_position is None
    assert stats.worst_position is None


def test_propose_adjustments_nudges_momentum_when_target_missed():
    stats = compute_week_stats([1000.0, 990.0], {}, target_monthly_pct=0.10,
                                week_start="2026-07-27", week_end="2026-08-02")
    changes = propose_strategy_adjustments({"momentum": 0.6, "div_yield": 0.3}, stats)
    momentum_changes = [c for c in changes if c.parameter == "momentum"]
    assert len(momentum_changes) == 1
    assert momentum_changes[0].new_value == pytest.approx(0.6 + MAX_WEEKLY_ADJUSTMENT)


def test_propose_adjustments_never_exceeds_bounded_max():
    stats = compute_week_stats([1000.0, 990.0], {}, target_monthly_pct=0.10,
                                week_start="2026-07-27", week_end="2026-08-02")
    _, hi = BOUNDED_PARAMETERS["momentum"]
    changes = propose_strategy_adjustments({"momentum": hi - 0.01, "div_yield": 0.3}, stats)
    momentum_changes = [c for c in changes if c.parameter == "momentum"]
    assert momentum_changes[0].new_value <= hi


def test_propose_adjustments_no_change_when_target_hit_and_drawdown_low():
    stats = compute_week_stats([1000.0, 1050.0], {}, target_monthly_pct=0.01,
                                week_start="2026-07-27", week_end="2026-08-02")
    changes = propose_strategy_adjustments({"momentum": 0.6, "div_yield": 0.3}, stats)
    assert changes == []


def test_propose_adjustments_never_touches_risk_config_fields():
    stats = compute_week_stats([1000.0, 500.0], {}, target_monthly_pct=0.10,
                                week_start="2026-07-27", week_end="2026-08-02")
    changes = propose_strategy_adjustments({"momentum": 0.6, "div_yield": 0.3}, stats)
    touched_params = {c.parameter for c in changes}
    assert touched_params.issubset(set(BOUNDED_PARAMETERS.keys()))


def test_append_to_changelog_creates_and_appends(tmp_path):
    path = str(tmp_path / "changelog.json")
    stats = WeekStats("2026-07-20", "2026-07-26", 0.02, -0.01, 0.05, "NVDA", "SCHD")
    changes = [ProposedChange("momentum", 0.6, 0.65, "test reason")]
    append_to_changelog(path, stats, changes, lessons="First week, nothing dramatic.")

    stats2 = WeekStats("2026-07-27", "2026-08-02", 0.03, 0.01, 0.02, "AMD", "VOO")
    append_to_changelog(path, stats2, [], lessons="Second week, on target.")

    with open(path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    assert len(entries) == 2
    assert entries[0]["week_start"] == "2026-07-20"
    assert entries[0]["changes"][0]["parameter"] == "momentum"
    assert entries[1]["lessons"] == "Second week, on target."
    assert entries[0]["pause_changes"] == []  # defaults to an empty list, not missing/None


def test_append_to_changelog_stores_pause_changes(tmp_path):
    path = str(tmp_path / "changelog.json")
    stats = WeekStats("2026-07-20", "2026-07-26", 0.02, -0.01, 0.05, "NVDA", "SCHD")
    append_to_changelog(
        path, stats, [], lessons="Mixed week.",
        pause_changes=["Auto-paused SCHD for 2 weeks: net-negative 3 weeks running"],
    )

    with open(path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    assert entries[0]["pause_changes"] == ["Auto-paused SCHD for 2 weeks: net-negative 3 weeks running"]
