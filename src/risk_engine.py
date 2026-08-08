"""
Risk & rules engine.

This module has ZERO dependency on Tiger's SDK or any network call — it is
pure logic so it can be unit tested in isolation. Every trade the agent
ever considers must pass through validate_trade() here before it reaches
the execution layer. Nothing else in the system is allowed to bypass it,
including the LLM scoring layer added later.

Design principle: the monthly income target is informational only for the
hard checks below -- it never relaxes check_kill_switch/check_daily_loss_limit/
check_capital_cap/check_max_drawdown. The user explicitly chose an aggressive,
concentrated position-sizing posture (higher max_risk_per_trade_pct) over a
conservative one to give the 10%/month target a real shot -- that tradeoff is
expressed in the config VALUES below, not by weakening the checks themselves.
max_drawdown_pct is the one hard floor kept regardless: no strategy is allowed
to run the account to zero even under an aggressive posture.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List


@dataclass
class RiskConfig:
    max_capital_at_risk: float = 1000.0    # hard ceiling on total notional across open positions
    max_daily_loss: float = 150.0          # realized loss in a day that halts all new trades
    max_risk_per_trade_pct: float = 0.35   # concentrated by design -- see module docstring
    max_concurrent_positions: int = 5
    max_drawdown_pct: float = 0.25         # peak-to-trough equity drawdown that halts trading
    monthly_income_target: float = 100.0   # 10% of $1,000 -- informational, never overrides checks
    allowed_strategies: tuple = ("core_hold", "satellite_momentum")
    kill_switch: bool = False              # manual override — set True to halt everything instantly
    max_short_exposure_pct: float = 0.15   # of max_capital_at_risk, aggregate across all short positions
    max_short_positions: int = 1           # "if the opportunity arises" -- rare/selective, not a standing sleeve


@dataclass
class Position:
    symbol: str
    strategy: str           # must be in RiskConfig.allowed_strategies
    notional: float         # capital committed if assigned (strike * 100 * contracts) -- always a magnitude, never signed
    premium_collected: float
    opened_on: date
    direction: str = "long"  # "long" | "short" -- defaults to "long" so every existing caller is unaffected


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

    def check_short_exposure(self, state: DailyState, proposed_notional: float):
        """
        Aggregate short exposure is riskier than aggregate long exposure --
        a short's loss is theoretically unlimited, unlike a long which
        floors at zero -- so this is a hard cap on top of (not instead of)
        check_capital_cap/check_per_trade_risk, which already apply to any
        trade regardless of direction.
        """
        existing_shorts = [p for p in state.open_positions if p.direction == "short"]
        committed_short = sum(p.notional for p in existing_shorts)
        max_allowed = self.config.max_capital_at_risk * self.config.max_short_exposure_pct
        if committed_short + proposed_notional > max_allowed:
            raise RiskViolation(
                f"Proposed short (${proposed_notional:.2f}) would push aggregate short "
                f"exposure to ${committed_short + proposed_notional:.2f}, exceeding the "
                f"short-exposure cap of ${max_allowed:.2f} "
                f"({self.config.max_short_exposure_pct:.0%} of capital cap)."
            )
        if len(existing_shorts) >= self.config.max_short_positions:
            raise RiskViolation(
                f"Max short positions reached ({len(existing_shorts)}/"
                f"{self.config.max_short_positions})."
            )

    def check_max_drawdown(self, equity_curve: List[float]):
        """
        Peak-to-trough drawdown check over an equity curve (backtest or
        live). This is the one hard floor kept even under the aggressive,
        concentrated posture described in the module docstring -- no
        strategy is allowed to keep trading once it's given back more than
        max_drawdown_pct from its high-water mark.
        """
        if len(equity_curve) < 2:
            return
        peak = equity_curve[0]
        for value in equity_curve[1:]:
            peak = max(peak, value)
            if peak <= 0:
                continue
            drawdown = (peak - value) / peak
            if drawdown >= self.config.max_drawdown_pct:
                raise RiskViolation(
                    f"Max drawdown limit hit: {drawdown:.1%} decline from peak "
                    f"${peak:.2f}, limit is {self.config.max_drawdown_pct:.0%}. "
                    "Trading halted."
                )

    def validate_trade(
        self, state: DailyState, strategy: str, proposed_notional: float, direction: str = "long"
    ) -> bool:
        """
        Runs every hard check in a fixed order. Raises RiskViolation on the
        first failure. Returns True only if every single check passes.
        direction defaults to "long" so every existing call site (which
        never passed it) is unaffected; check_short_exposure only runs
        when direction == "short".
        """
        self.check_kill_switch()
        self.check_daily_loss_limit(state)
        self.check_strategy_allowed(strategy)
        self.check_concurrent_positions(state)
        self.check_capital_cap(state, proposed_notional)
        self.check_per_trade_risk(proposed_notional)
        if direction == "short":
            self.check_short_exposure(state, proposed_notional)
        return True

    def required_monthly_yield(self, capital: float) -> float:
        """
        Returns the monthly return (as a fraction, e.g. 0.10 = 10%) needed
        on `capital` to hit the configured monthly income target.
        Informational only -- never used to override checks above.
        """
        if capital <= 0:
            raise ValueError("capital must be positive")
        return self.config.monthly_income_target / capital
