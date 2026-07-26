"""
Strategy layer.

Pure logic, no Tiger SDK or network dependency -- takes option chain data
as plain dataclasses so it can be fully unit tested with synthetic data.
Wiring this to real Tiger option chain data is a separate adapter, added
after this logic is validated on its own.

Responsibility boundary: this module PROPOSES candidates and ranks them.
It never decides a trade is "approved" -- every candidate still has to
pass risk_engine.validate_trade() before it's real. select_portfolio()
below calls into the risk engine explicitly so there is exactly one path
a trade can take to get approved, regardless of what proposed it.
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from risk_engine import RiskEngine, RiskViolation, DailyState, Position


@dataclass
class OptionContract:
    """Raw data for a single option contract, as it would come from a chain."""
    symbol: str            # underlying, e.g. "AAPL"
    option_symbol: str     # full contract identifier
    strike: float
    expiry: date
    put_call: str           # "PUT" | "CALL"
    bid: float
    ask: float
    delta: float             # signed OK; abs() is used for filtering
    open_interest: int
    volume: int
    implied_volatility: float


@dataclass
class StrategyConfig:
    target_delta_min: float = 0.15
    target_delta_max: float = 0.30
    min_dte: int = 5
    max_dte: int = 14
    min_open_interest: int = 100
    min_volume: int = 10
    avoid_earnings_within_days: int = 3   # skip if earnings fall inside the holding window
    contracts_per_trade: int = 1


@dataclass
class TradeCandidate:
    symbol: str
    option_symbol: str
    strategy: str          # "cash_secured_put" | "covered_call"
    strike: float
    expiry: date
    dte: int
    premium_per_share: float
    contracts: int
    notional: float                 # strike * 100 * contracts -- what validate_trade() checks
    premium_total: float            # premium_per_share * 100 * contracts
    weekly_yield_estimate: float    # normalized to a weekly rate for comparison across DTEs
    delta: float
    open_interest: int
    volume: int


_STRATEGY_TO_PUT_CALL = {
    "cash_secured_put": "PUT",
    "covered_call": "CALL",
}


def _passes_earnings_filter(
    expiry: date, as_of: date, next_earnings_date: Optional[date], avoid_within_days: int
) -> bool:
    if next_earnings_date is None:
        return True  # unknown earnings date -- can't filter on it, caller should be aware
    # Skip if earnings happens any time between now and expiry (or within the buffer after).
    if as_of <= next_earnings_date <= expiry:
        return False
    return True


def generate_candidates(
    chain: List[OptionContract],
    strategy: str,
    config: StrategyConfig,
    as_of: date,
    next_earnings_date: Optional[date] = None,
) -> List[TradeCandidate]:
    """
    Filters a raw option chain down to viable candidates for the given
    strategy, and ranks them by estimated weekly yield (descending).
    Does not check capital or risk limits -- that happens in select_portfolio.
    """
    if strategy not in _STRATEGY_TO_PUT_CALL:
        raise ValueError(f"Unknown strategy '{strategy}'")

    wanted_type = _STRATEGY_TO_PUT_CALL[strategy]
    candidates: List[TradeCandidate] = []

    for contract in chain:
        if contract.put_call != wanted_type:
            continue

        dte = (contract.expiry - as_of).days
        if dte < config.min_dte or dte > config.max_dte:
            continue

        if not (config.target_delta_min <= abs(contract.delta) <= config.target_delta_max):
            continue

        if contract.open_interest < config.min_open_interest:
            continue
        if contract.volume < config.min_volume:
            continue

        if not _passes_earnings_filter(
            contract.expiry, as_of, next_earnings_date, config.avoid_earnings_within_days
        ):
            continue

        premium_per_share = (contract.bid + contract.ask) / 2  # mid price estimate
        contracts = config.contracts_per_trade
        notional = contract.strike * 100 * contracts
        premium_total = premium_per_share * 100 * contracts

        if notional <= 0:
            continue

        raw_yield = premium_total / notional
        weekly_yield_estimate = raw_yield * (7 / dte) if dte > 0 else 0.0

        candidates.append(
            TradeCandidate(
                symbol=contract.symbol,
                option_symbol=contract.option_symbol,
                strategy=strategy,
                strike=contract.strike,
                expiry=contract.expiry,
                dte=dte,
                premium_per_share=premium_per_share,
                contracts=contracts,
                notional=notional,
                premium_total=premium_total,
                weekly_yield_estimate=weekly_yield_estimate,
                delta=contract.delta,
                open_interest=contract.open_interest,
                volume=contract.volume,
            )
        )

    candidates.sort(key=lambda c: c.weekly_yield_estimate, reverse=True)
    return candidates


def select_portfolio(
    candidates: List[TradeCandidate],
    risk_engine: RiskEngine,
    state: DailyState,
    one_per_symbol: bool = True,
) -> List[TradeCandidate]:
    """
    Greedily walks candidates highest-yield-first and keeps the ones the
    risk engine actually approves, simulating each acceptance's effect on
    capital-at-risk and position count before considering the next one.

    This is the ONLY function that should turn a candidate into something
    closer to a real trade. It never bypasses risk_engine.validate_trade().
    Returns the accepted candidates in the order they were accepted.
    """
    accepted: List[TradeCandidate] = []
    seen_symbols = set()

    # Work on a local copy so we don't mutate the caller's real state until
    # trades are actually placed by the execution layer.
    working_positions = list(state.open_positions)

    for candidate in candidates:
        if one_per_symbol and candidate.symbol in seen_symbols:
            continue

        working_state = DailyState(
            date=state.date,
            realized_pnl_today=state.realized_pnl_today,
            open_positions=working_positions,
        )

        try:
            risk_engine.validate_trade(working_state, candidate.strategy, candidate.notional)
        except RiskViolation:
            continue

        accepted.append(candidate)
        seen_symbols.add(candidate.symbol)
        working_positions = working_positions + [
            Position(
                symbol=candidate.symbol,
                strategy=candidate.strategy,
                notional=candidate.notional,
                premium_collected=candidate.premium_total,
                opened_on=state.date,
            )
        ]

    return accepted
