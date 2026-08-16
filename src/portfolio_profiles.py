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
    JOURNAL_PATH, JOURNAL_PATH_DIVIDEND,
    CHANGELOG_PATH, CHANGELOG_PATH_DIVIDEND,
    SCAN_SETTINGS_PATH, SHORTLIST_PATH, SCAN_SETTINGS_PATH_DIVIDEND, SHORTLIST_PATH_DIVIDEND,
    PAUSED_SYMBOLS_PATH, PAUSED_SYMBOLS_PATH_DIVIDEND,
    EXTRA_UNIVERSE_PATH, EXTRA_UNIVERSE_PATH_DIVIDEND,
    SECTOR_SUGGESTIONS_PATH, SECTOR_SUGGESTIONS_PATH_DIVIDEND,
)
from universe_extra import load_extra_universe

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
    journal_path: str
    changelog_path: str
    scan_settings_path: str
    shortlist_path: str
    paused_symbols_path: str
    extra_universe_path: str
    sector_suggestions_path: str
    scoring_weights: Optional[Dict[str, float]] = None  # None -> stock_signal.score_symbol's own default
    confidence_scale: Optional[float] = None  # None -> the confidence/shortlist/autopilot system is off for this profile


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
        journal_path=JOURNAL_PATH,
        changelog_path=CHANGELOG_PATH,
        scan_settings_path=SCAN_SETTINGS_PATH,
        shortlist_path=SHORTLIST_PATH,
        paused_symbols_path=PAUSED_SYMBOLS_PATH,
        extra_universe_path=EXTRA_UNIVERSE_PATH,
        sector_suggestions_path=SECTOR_SUGGESTIONS_PATH,
        # Sigmoid scale for confidence.score_to_confidence: chosen so a
        # solid momentum candidate (score~0.15, ~20-25% momentum under
        # the 0.6/0.3/0.1 default weights) lands ~73% confidence, a
        # neutral score sits at exactly 50%, and a weak one (score~-0.15)
        # lands ~27% -- see src/confidence.py.
        confidence_scale=0.15,
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
        journal_path=JOURNAL_PATH_DIVIDEND,
        changelog_path=CHANGELOG_PATH_DIVIDEND,
        scan_settings_path=SCAN_SETTINGS_PATH_DIVIDEND,
        shortlist_path=SHORTLIST_PATH_DIVIDEND,
        paused_symbols_path=PAUSED_SYMBOLS_PATH_DIVIDEND,
        extra_universe_path=EXTRA_UNIVERSE_PATH_DIVIDEND,
        sector_suggestions_path=SECTOR_SUGGESTIONS_PATH_DIVIDEND,
        scoring_weights=DIVIDEND_SCORING_WEIGHTS,
        # Sigmoid scale for confidence.score_to_confidence, calibrated
        # against real decision_log_dividend.json history (23 scored
        # decisions, range ~0.0058-0.0838) -- dividend's yield-first
        # scoring produces much smaller score magnitudes than growth's
        # momentum-first one, so it needs its own, much smaller scale.
        # At 0.06, a strong yield pick (score~0.08, e.g. HDV/MO) lands
        # ~70%+ confidence while a weak one (score~0.01) sits near 50%,
        # a comparable spread to growth's own calibration.
        confidence_scale=0.06,
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


def effective_universe(profile: PortfolioProfile) -> List[UniverseEntry]:
    """profile.universe (the static, code-defined list) plus any symbols
    a human has approved adding via app.py's POST /universe/add route
    (see universe_extra.py) -- computed fresh on every call (a single
    small JSON read) rather than baked into the profile at import time,
    so an approval takes effect on the very next scan/dashboard load, no
    process restart needed. profile.universe itself is left untouched --
    it's still the same list assert_universes_disjoint checked above."""
    extra = load_extra_universe(profile.extra_universe_path)
    return profile.universe + [
        UniverseEntry(symbol=e.symbol, market=e.market, currency=e.currency, exchange=e.exchange, sleeve=e.sleeve)
        for e in extra
    ]


def validate_new_universe_entry(symbol: str, target_profile: PortfolioProfile) -> None:
    """Raises ValueError if `symbol` already appears in EITHER profile's
    effective universe (static + already-approved extras) -- the runtime
    counterpart to assert_universes_disjoint, which only ever checked
    the static universe at import and has no way to see a runtime
    addition. Call this BEFORE persisting an approval (app.py's
    POST /universe/add), not just at display time, so two
    near-simultaneous approvals for the same symbol in different
    profiles can't both succeed."""
    for profile in ALL_PROFILES:
        for entry in effective_universe(profile):
            if entry.symbol == symbol:
                raise ValueError(
                    f"'{symbol}' is already in the '{profile.name}' portfolio's universe -- "
                    "a symbol can only belong to one portfolio (Tiger reports one combined "
                    "position per symbol for the whole account)."
                )
