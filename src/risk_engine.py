"""
Risk & rules engine.

This module has ZERO dependency on Tiger's SDK or any network call — it is
pure logic so it can be unit tested in isolation. Every trade the agent
ever considers must pass through validate_trade() here before it reaches
the execution layer. Nothing else in the system is allowed to bypass it,
including the LLM scoring layer added later.

Design principle: the weekly income target is informational only. It is
never used to relax a risk check. If hitting the target would require
breaking a limit, the correct behavior is to not hit the target that week.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List


@dataclass
class RiskConfig:
    max_capital_at_risk: float = 10000.0   # hard ceiling on total notional across open positions
    max_daily_loss: float = 200.0          # realized loss in a day that halts all new trades
    max_risk_per_trade_pct: float = 0.10   # no single trade may risk more than this fraction of the cap
    max_concurrent_positions: int = 5
    weekly_income_target: float = 100.0    # informational target, never overrides checks above
    allowed_strategies: tuple = ("cash_secured_put", "covered_call")
    kill_switch: bool = False              # manual override — set True to halt everything instantly


@dataclass
class Position:
    symbol: str
    strategy: str           # must be in RiskConfig.allowed_strategies
    notional: float         # capital committed if assigned (strike * 100 * contracts)
    premium_collected: float
    opened_on: date


@dataclass
class DailyState:
    date: date
    realized_pnl_today: float = 0.0
    open_positions: List[Position] = field(default_factory=list)


class RiskViolation(Exception):
    """
    Raised when a proposed trade fails a hard check. This must always
    propagate — never catch and silently continue past it.
    """
    pass


class RiskEngine:
    def __init__(self, config: RiskConfig):
        self.config = config

    def _capital_committed(self, state: DailyState) -> float:
        return sum(p.notional for p in state.open_positions)

    def check_kill_switch(self):
        if self.config.kill_switch:
            raise RiskViolation("Kill switch is active. No trades permitted.")

    def check_daily_loss_limit(self, state: DailyState):
        if state.realized_pnl_today <= -abs(self.config.max_daily_loss):
            raise RiskViolation(
                f"Daily loss limit hit: realized PnL {state.realized_pnl_today:.2f} "
                f"<= -{self.config.max_daily_loss:.2f}. Trading halted for today."
            )

    def check_concurrent_positions(self, state: DailyState):
        if len(state.open_positions) >= self.config.max_concurrent_positions:
            raise RiskViolation(
                f"Max concurrent positions reached "
                f"({len(state.open_positions)}/{self.config.max_concurrent_positions})."
            )

    def check_capital_cap(self, state: DailyState, proposed_notional: float):
        committed = self._capital_committed(state)
        if committed + proposed_notional > self.config.max_capital_at_risk:
            raise RiskViolation(
                f"Proposed trade (${proposed_notional:.2f}) would push capital at risk "
                f"to ${committed + proposed_notional:.2f}, exceeding cap of "
                f"${self.config.max_capital_at_risk:.2f}."
            )

    def check_per_trade_risk(self, proposed_notional: float):
        max_allowed = self.config.max_capital_at_risk * self.config.max_risk_per_trade_pct
        if proposed_notional > max_allowed:
            raise RiskViolation(
                f"Proposed trade (${proposed_notional:.2f}) exceeds max per-trade risk "
                f"of ${max_allowed:.2f} ({self.config.max_risk_per_trade_pct:.0%} of capital cap)."
            )

    def check_strategy_allowed(self, strategy: str):
        if strategy not in self.config.allowed_strategies:
            raise RiskViolation(
                f"Strategy '{strategy}' is not in the allowed list: "
                f"{self.config.allowed_strategies}."
            )

    def validate_trade(self, state: DailyState, strategy: str, proposed_notional: float) -> bool:
        """
        Runs every hard check in a fixed order. Raises RiskViolation on the
        first failure. Returns True only if every single check passes.
        """
        self.check_kill_switch()
        self.check_daily_loss_limit(state)
        self.check_strategy_allowed(strategy)
        self.check_concurrent_positions(state)
        self.check_capital_cap(state, proposed_notional)
        self.check_per_trade_risk(proposed_notional)
        return True

    def required_weekly_yield(self, capital: float) -> float:
        """
        Returns the weekly premium yield (as a fraction, e.g. 0.02 = 2%)
        needed on `capital` to hit the configured weekly income target.
        Informational only -- never used to override checks above.
        """
        if capital <= 0:
            raise ValueError("capital must be positive")
        return self.config.weekly_income_target / capital
