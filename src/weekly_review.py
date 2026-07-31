"""
Weekly self-learning review: turns a week's equity curve and realized
position returns into numeric stats, then proposes BOUNDED tactical
parameter adjustments (composite_score signal weights only) -- it never
touches RiskConfig (max_capital_at_risk, max_drawdown_pct,
max_risk_per_trade_pct, etc.), which stay user-controlled, consistent with
"risk engine hard limits always take precedence" established earlier in
this project.

The "lessons observed" narrative that goes in the Telegram digest is
composed by Claude each week when this runs (same judgment-call pattern as
the news tilt) -- this module only handles the numeric side and the
changelog persistence.
"""
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

# parameter -> (min, max): only these may ever be auto-adjusted, and only
# within this range. Nothing outside composite_score's own weights is
# touchable here.
BOUNDED_PARAMETERS = {
    "momentum": (0.3, 0.8),
    "div_yield": (0.1, 0.5),
    "news_tilt": (0.0, 0.3),
}
MAX_WEEKLY_ADJUSTMENT = 0.05  # a single week's proposal can't move a weight by more than this


@dataclass
class WeekStats:
    week_start: str
    week_end: str
    realized_pct: float
    vs_target_pct: float
    max_intraweek_drawdown_pct: float
    best_position: Optional[str]
    worst_position: Optional[str]


@dataclass
class ProposedChange:
    parameter: str
    old_value: float
    new_value: float
    reason: str


def compute_week_stats(
    equity_curve: List[float],
    position_returns: Dict[str, float],
    target_monthly_pct: float,
    week_start: str,
    week_end: str,
) -> WeekStats:
    """
    equity_curve: this week's equity snapshots (>=2 points).
    position_returns: {symbol: period_return_pct} for positions held this week.
    target_monthly_pct is pro-rated to a weekly-equivalent (divided by
    ~4.33 weeks/month) purely for an apples-to-apples comparison here --
    the actual risk-engine target (RiskConfig.monthly_income_target) stays
    monthly and is never changed by this module.
    """
    if len(equity_curve) < 2:
        raise ValueError("Need at least 2 equity points to compute week stats")

    realized_pct = (equity_curve[-1] / equity_curve[0]) - 1
    weekly_target = target_monthly_pct / 4.33

    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve[1:]:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)

    best = max(position_returns, key=position_returns.get) if position_returns else None
    worst = min(position_returns, key=position_returns.get) if position_returns else None

    return WeekStats(
        week_start=week_start,
        week_end=week_end,
        realized_pct=round(realized_pct, 4),
        vs_target_pct=round(realized_pct - weekly_target, 4),
        max_intraweek_drawdown_pct=round(max_dd, 4),
        best_position=best,
        worst_position=worst,
    )


def propose_strategy_adjustments(
    current_weights: Dict[str, float], week_stats: WeekStats
) -> List[ProposedChange]:
    """
    Deliberately simple, bounded heuristic: missing the weekly-equivalent
    target nudges the momentum weight up (the sleeve most responsive to
    "chase the target harder"); an elevated intraweek drawdown nudges the
    dividend-yield weight up (more defensive ballast). Each nudge is capped
    at MAX_WEEKLY_ADJUSTMENT and clamped to BOUNDED_PARAMETERS.
    """
    changes: List[ProposedChange] = []

    if week_stats.vs_target_pct < 0:
        old = current_weights.get("momentum", 0.6)
        _, hi = BOUNDED_PARAMETERS["momentum"]
        new = min(hi, old + MAX_WEEKLY_ADJUSTMENT)
        if new != old:
            changes.append(ProposedChange(
                parameter="momentum", old_value=old, new_value=round(new, 4),
                reason=f"Missed weekly-equivalent target by {abs(week_stats.vs_target_pct):.1%}; "
                       "nudging momentum weight up within its bounded range.",
            ))

    if week_stats.max_intraweek_drawdown_pct > 0.15:
        old = current_weights.get("div_yield", 0.3)
        _, hi = BOUNDED_PARAMETERS["div_yield"]
        new = min(hi, old + MAX_WEEKLY_ADJUSTMENT)
        if new != old:
            changes.append(ProposedChange(
                parameter="div_yield", old_value=old, new_value=round(new, 4),
                reason=f"Intraweek drawdown of {week_stats.max_intraweek_drawdown_pct:.1%} was elevated; "
                       "nudging dividend-yield weight up for more ballast.",
            ))

    return changes


def append_to_changelog(path: str, week_stats: WeekStats, changes: List[ProposedChange], lessons: str):
    """Appends one week's entry to a JSON list at `path`, creating it if needed."""
    entries = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)

    entries.append({
        "week_start": week_stats.week_start,
        "week_end": week_stats.week_end,
        "realized_pct": week_stats.realized_pct,
        "vs_target_pct": week_stats.vs_target_pct,
        "max_intraweek_drawdown_pct": week_stats.max_intraweek_drawdown_pct,
        "best_position": week_stats.best_position,
        "worst_position": week_stats.worst_position,
        "changes": [c.__dict__ for c in changes],
        "lessons": lessons,
    })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
