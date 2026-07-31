"""
Core-satellite portfolio construction. Reflects the user's explicit "chase
the target harder" choice: a concentrated satellite sleeve of momentum picks
alongside a smaller, steadier core sleeve of ETFs/dividend names -- while
still enforcing max_single_position_pct so nothing ever reaches 100% of
capital, and filtering out HK/SG names whose board lot doesn't actually fit
the account before they ever reach a position size decision.

Pure logic, no network -- consumes plain dicts/dataclasses that the Tiger
adapters (tiger_stock_bars_adapter, tiger_trade_metas_adapter) produce.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from macro_regime import apply_regime_tilt
from tiger_trade_metas_adapter import LotInfo, DEFAULT_LOT_SIZE


@dataclass
class PortfolioConfig:
    core_pct: float = 0.40
    satellite_pct: float = 0.60
    max_core_positions: int = 2
    max_satellite_positions: int = 3
    max_single_position_pct: float = 0.35   # hard cap regardless of sleeve -- nothing hits 100%
    min_position_pct: float = 0.10          # below this, drop the position rather than dilute further


@dataclass
class ScoredCandidate:
    symbol: str
    sleeve: str    # "core" | "satellite"
    score: float
    price: float


@dataclass
class PlannedPosition:
    symbol: str
    sleeve: str
    target_notional: float
    target_pct: float


def filter_affordable_by_lot(
    symbol_prices: Dict[str, float],
    lot_infos: Dict[str, LotInfo],
    available_capital: float,
    max_position_pct: float,
) -> List[str]:
    """
    Keeps a symbol only if one board lot fits within max_position_pct of
    available_capital. Symbols missing from lot_infos default to
    DEFAULT_LOT_SIZE (1 share/lot, matching US behavior) rather than being
    dropped for lack of data.
    """
    max_position_notional = available_capital * max_position_pct
    affordable = []
    for symbol, price in symbol_prices.items():
        lot_size = lot_infos[symbol].lot_size if symbol in lot_infos else DEFAULT_LOT_SIZE
        lot_cost = lot_size * price
        if lot_cost <= max_position_notional:
            affordable.append(symbol)
    return affordable


def allocate_portfolio(
    candidates: List[ScoredCandidate],
    config: PortfolioConfig,
    capital: float,
    regime_tilts: Optional[Dict[str, float]] = None,
) -> List[PlannedPosition]:
    """
    Splits capital into core/satellite budgets (optionally tilted by the
    current macro regime), then within each sleeve takes the top-scoring
    candidates up to that sleeve's position cap and splits the sleeve's
    budget evenly among them -- capped per-position at
    max_single_position_pct of total capital. If an even split would fall
    below min_position_pct, positions are dropped (not diluted further)
    until the remaining ones clear the floor.

    Any leftover budget from the max_single_position_pct cap is left
    uninvested this period rather than redistributed -- a deliberate
    simplification for this first pass.
    """
    base_budgets = {"core": capital * config.core_pct, "satellite": capital * config.satellite_pct}
    if regime_tilts:
        base_budgets = apply_regime_tilt(base_budgets, regime_tilts)

    max_positions = {"core": config.max_core_positions, "satellite": config.max_satellite_positions}
    max_single = capital * config.max_single_position_pct
    min_single = capital * config.min_position_pct

    planned: List[PlannedPosition] = []
    for sleeve in ("core", "satellite"):
        sleeve_candidates = sorted(
            [c for c in candidates if c.sleeve == sleeve],
            key=lambda c: c.score,
            reverse=True,
        )[: max_positions[sleeve]]
        if not sleeve_candidates:
            continue

        budget = base_budgets.get(sleeve, 0.0)
        n = len(sleeve_candidates)
        while n > 1 and budget / n < min_single:
            n -= 1
        sleeve_candidates = sleeve_candidates[:n]
        if budget / n < min_single:
            continue  # even a single position can't clear the floor -- skip this sleeve

        per_position = min(budget / n, max_single)
        for c in sleeve_candidates:
            planned.append(
                PlannedPosition(
                    symbol=c.symbol,
                    sleeve=sleeve,
                    target_notional=per_position,
                    target_pct=per_position / capital,
                )
            )

    return planned
