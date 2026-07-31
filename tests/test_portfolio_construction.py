"""
Run with:
    pytest tests/test_portfolio_construction.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from portfolio_construction import (
    PortfolioConfig, ScoredCandidate, PlannedPosition,
    filter_affordable_by_lot, allocate_portfolio,
)
from tiger_trade_metas_adapter import LotInfo


def test_filter_affordable_by_lot_excludes_expensive_board_lot():
    # 0700.HK at $50/share, lot_size=100 -> $5,000/lot, way over a $1,000*0.35 cap
    prices = {"00700": 50.0, "SCHD": 80.0}
    lot_infos = {"00700": LotInfo(lot_size=100, min_tick=0.2), "SCHD": LotInfo(lot_size=1, min_tick=0.01)}
    result = filter_affordable_by_lot(prices, lot_infos, available_capital=1000.0, max_position_pct=0.35)
    assert result == ["SCHD"]


def test_filter_affordable_by_lot_defaults_missing_symbol_to_lot_size_one():
    prices = {"NVDA": 100.0}
    result = filter_affordable_by_lot(prices, {}, available_capital=1000.0, max_position_pct=0.35)
    assert result == ["NVDA"]


def test_allocate_portfolio_respects_position_caps():
    config = PortfolioConfig(max_core_positions=1, max_satellite_positions=2)
    candidates = [
        ScoredCandidate("VOO", "core", score=0.05, price=500.0),
        ScoredCandidate("SCHD", "core", score=0.03, price=80.0),  # should be dropped (cap=1)
        ScoredCandidate("NVDA", "satellite", score=0.30, price=120.0),
        ScoredCandidate("AMD", "satellite", score=0.20, price=150.0),
        ScoredCandidate("META", "satellite", score=0.10, price=500.0),  # should be dropped (cap=2)
    ]
    planned = allocate_portfolio(candidates, config, capital=1000.0)
    symbols = {p.symbol for p in planned}
    assert symbols == {"VOO", "NVDA", "AMD"}


def test_allocate_portfolio_caps_single_position_pct():
    config = PortfolioConfig(max_core_positions=1, max_satellite_positions=1, max_single_position_pct=0.35)
    candidates = [ScoredCandidate("VOO", "core", score=0.05, price=500.0)]
    planned = allocate_portfolio(candidates, config, capital=1000.0)
    voo = next(p for p in planned if p.symbol == "VOO")
    assert voo.target_notional <= 1000.0 * 0.35 + 1e-9


def test_allocate_portfolio_nothing_reaches_100_percent():
    config = PortfolioConfig()
    candidates = [ScoredCandidate("NVDA", "satellite", score=0.5, price=100.0)]
    planned = allocate_portfolio(candidates, config, capital=1000.0)
    assert all(p.target_pct < 1.0 for p in planned)


def test_allocate_portfolio_applies_regime_tilt():
    config = PortfolioConfig(max_core_positions=1, max_satellite_positions=1, max_single_position_pct=1.0)
    candidates = [
        ScoredCandidate("VOO", "core", score=0.05, price=500.0),
        ScoredCandidate("NVDA", "satellite", score=0.30, price=120.0),
    ]
    baseline = allocate_portfolio(candidates, config, capital=1000.0)
    tilted = allocate_portfolio(candidates, config, capital=1000.0, regime_tilts={"satellite": 1.5, "core": 0.5})

    baseline_satellite = next(p for p in baseline if p.symbol == "NVDA").target_notional
    tilted_satellite = next(p for p in tilted if p.symbol == "NVDA").target_notional
    assert tilted_satellite > baseline_satellite


def test_allocate_portfolio_empty_candidates_returns_empty():
    assert allocate_portfolio([], PortfolioConfig(), capital=1000.0) == []


def test_allocate_portfolio_drops_sleeve_below_min_position_floor():
    # satellite budget is tiny relative to min_position_pct -> sleeve should be skipped entirely
    config = PortfolioConfig(core_pct=0.99, satellite_pct=0.01, min_position_pct=0.10, max_satellite_positions=1)
    candidates = [ScoredCandidate("NVDA", "satellite", score=0.5, price=100.0)]
    planned = allocate_portfolio(candidates, config, capital=1000.0)
    assert planned == []
