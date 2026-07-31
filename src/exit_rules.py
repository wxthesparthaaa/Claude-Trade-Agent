"""
Per-position exit rules, checked more frequently than the full monthly
rebalance -- this is what makes "when to sell" a real decision distinct
from just periodically re-ranking and letting unselected names fall out.
Two triggers:
  - a hard stop-loss (protects against a single name cratering between
    scheduled rebalances)
  - a momentum-reversal exit (gets out of a name whose trend turns before
    the next scheduled rebalance would otherwise catch it)
Both are pure numeric checks, no network.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExitConfig:
    stop_loss_pct: float = 0.15              # exit if down this much from entry price
    momentum_exit_threshold: float = -0.05    # exit if rolling momentum drops below this


@dataclass
class ExitDecision:
    should_exit: bool
    reason: Optional[str] = None  # human-readable, e.g. "stop_loss: down 16.2% from entry"


def check_stop_loss(entry_price: float, current_price: float, config: ExitConfig) -> ExitDecision:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    ret = (current_price - entry_price) / entry_price
    if ret <= -config.stop_loss_pct:
        return ExitDecision(should_exit=True, reason=f"stop_loss: down {ret:.1%} from entry")
    return ExitDecision(should_exit=False)


def check_momentum_reversal(current_momentum: float, config: ExitConfig) -> ExitDecision:
    if current_momentum < config.momentum_exit_threshold:
        return ExitDecision(
            should_exit=True,
            reason=(
                f"momentum_reversal: momentum at {current_momentum:.1%}, "
                f"below {config.momentum_exit_threshold:.1%} threshold"
            ),
        )
    return ExitDecision(should_exit=False)
