"""
Bundles everything that used to be hardcoded to the one growth portfolio
into a PortfolioProfile, so the same scan/execute/dashboard pipeline can
run against either the existing $1,000 growth/momentum portfolio or a
new dividend/income portfolio -- both live in the SAME Tiger account,
tracked as separate internal ledgers (the user's explicit choice), not
separate brokerage accounts.

Hard constraint this creates, enforced by the assertion at the bottom of
this module: Tiger reports one combined position per symbol for the
whole account -- it has no concept of "these shares belong to the
dividend ledger, those to growth." A symbol can therefore only ever
belong to ONE profile's universe, or the two ledgers would silently
mis-attribute each other's fills. Keeping the universes disjoint is far
simpler than trying to solve cross-attribution, and there's no real need
for both portfolios to hold the same ticker.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from universe import UniverseEntry, DEFAULT_UNIVERSE, DIVIDEND_UNIVERSE
from portfolio_construction import PortfolioConfig
from risk_engine import RiskConfig
from state_paths import (
    LEDGER_PATH, DECISION_LOG_PATH, SNAPSHOT_PATH, PENDING_APPROVALS_PATH,
    LEDGER_PATH_DIVIDEND, DECISION_LOG_PATH_DIVIDEND, SNAPSHOT_PATH_DIVIDEND, PENDING_APPROVALS_PATH_DIVIDEND,
)

DIVIDEND_PORTFOLIO_CAPITAL_ENV = "DIVIDEND_PORTFOLIO_CAPITAL"

# Yield-first scoring, vs. growth's momentum-first default (stock_signal's
# own built-in default: {"momentum": 0.6, "div_yield": 0.3, "news_tilt": 0.1}).
DIVIDEND_SCORING_WEIGHTS = {"momentum": 0.2, "div_yield": 0.7, "news_tilt": 0.1}


@dataclass
class PortfolioProfile:
    name: str                     # "growth" | "dividend" -- also the ?portfolio= query param value
    initial_capital: float
    universe: List[UniverseEntry]
    portfolio_config: PortfolioConfig
    risk_config: RiskConfig
    allow_short: bool
    active: bool
    ledger_path: str
    decision_log_path: str
    snapshot_path: str
    pending_approvals_path: str
    scoring_weights: Optional[Dict[str, float]] = None  # None -> stock_signal.score_symbol's own default


def _dividend_capital_from_env() -> float:
    raw = os.environ.get(DIVIDEND_PORTFOLIO_CAPITAL_ENV, "0")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _build_growth_profile() -> PortfolioProfile:
    return PortfolioProfile(
        name="growth",
        initial_capital=1000.0,
        universe=DEFAULT_UNIVERSE,
        portfolio_config=PortfolioConfig(),
        risk_config=RiskConfig(
            max_capital_at_risk=1000.0,
            allowed_strategies=("core_hold", "satellite_momentum", "satellite_short"),
        ),
        allow_short=True,
        active=True,
        ledger_path=LEDGER_PATH,
        decision_log_path=DECISION_LOG_PATH,
        snapshot_path=SNAPSHOT_PATH,
        pending_approvals_path=PENDING_APPROVALS_PATH,
    )


def _build_dividend_profile() -> PortfolioProfile:
    capital = _dividend_capital_from_env()
    return PortfolioProfile(
        name="dividend",
        initial_capital=capital,
        universe=DIVIDEND_UNIVERSE,
        portfolio_config=PortfolioConfig(
            core_pct=1.0, satellite_pct=0.0,
            max_core_positions=8, max_satellite_positions=0,
            max_single_position_pct=0.15, min_position_pct=0.05,
        ),
        risk_config=RiskConfig(
            max_capital_at_risk=capital,
            allowed_strategies=("core_hold",),   # explicitly excludes satellite_momentum/satellite_short
        ),
        allow_short=False,
        active=capital > 0,
        ledger_path=LEDGER_PATH_DIVIDEND,
        decision_log_path=DECISION_LOG_PATH_DIVIDEND,
        snapshot_path=SNAPSHOT_PATH_DIVIDEND,
        pending_approvals_path=PENDING_APPROVALS_PATH_DIVIDEND,
        scoring_weights=DIVIDEND_SCORING_WEIGHTS,
    )


GROWTH_PROFILE = _build_growth_profile()
DIVIDEND_PROFILE = _build_dividend_profile()

ALL_PROFILES = (GROWTH_PROFILE, DIVIDEND_PROFILE)
PROFILES_BY_NAME = {p.name: p for p in ALL_PROFILES}
ACTIVE_PROFILES = [p for p in ALL_PROFILES if p.active]


def assert_universes_disjoint(profiles=ALL_PROFILES) -> None:
    """
    Tiger reports one combined position per symbol for the whole account
    -- if two profiles' universes shared a symbol, their ledgers would
    mis-attribute each other's fills. Fails loudly at import time (and is
    directly unit tested) rather than silently corrupting state later.
    """
    seen = {}
    for profile in profiles:
        for entry in profile.universe:
            if entry.symbol in seen and seen[entry.symbol] != profile.name:
                raise AssertionError(
                    f"Symbol '{entry.symbol}' appears in both '{seen[entry.symbol]}' and "
                    f"'{profile.name}' portfolio universes -- universes must stay disjoint, "
                    "since Tiger reports one combined position per symbol for the account."
                )
            seen[entry.symbol] = profile.name


assert_universes_disjoint()


def get_profile(name: str) -> PortfolioProfile:
    if name not in PROFILES_BY_NAME:
        raise ValueError(f"Unknown portfolio profile '{name}' -- expected one of {list(PROFILES_BY_NAME)}")
    return PROFILES_BY_NAME[name]
