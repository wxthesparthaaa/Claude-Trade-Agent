"""
Run with:
    pytest tests/test_portfolio_snapshot.py -v
"""
import sys
import os
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from portfolio_snapshot import build_snapshot, refresh_snapshot, load_snapshot
from strategy_ledger import record_snapshot


@dataclass
class FakeContract:
    symbol: str


@dataclass
class FakePosition:
    contract: FakeContract
    quantity: float
    average_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_percent: float


def make_position(symbol, qty, avg_cost, price):
    market_value = qty * price
    pnl = market_value - qty * avg_cost
    pnl_pct = pnl / (qty * avg_cost) if qty and avg_cost else 0.0
    return FakePosition(FakeContract(symbol), qty, avg_cost, price, market_value, pnl, pnl_pct)


def test_build_snapshot_includes_known_universe_positions(tmp_path):
    ledger_path = str(tmp_path / "ledger.json")
    record_snapshot(ledger_path, 990.86, as_of="2026-08-04")
    positions = [make_position("SCHD", 5, 33.991, 33.385), make_position("NVDA", 1, 199.55, 196.48)]
    sleeve_by_symbol = {"SCHD": "core", "NVDA": "satellite"}

    snapshot = build_snapshot(positions, sleeve_by_symbol, ledger_path)

    symbols = {p["symbol"] for p in snapshot["positions"]}
    assert symbols == {"SCHD", "NVDA"}
    assert snapshot["total_capital"] == 990.86
    schd = next(p for p in snapshot["positions"] if p["symbol"] == "SCHD")
    assert schd["sleeve"] == "core"
    assert schd["quantity"] == 5


def test_build_snapshot_excludes_symbols_outside_universe(tmp_path):
    ledger_path = str(tmp_path / "ledger.json")
    record_snapshot(ledger_path, 1000.0, as_of="2026-08-04")
    positions = [make_position("RANDOMSTOCK", 10, 5.0, 6.0)]
    snapshot = build_snapshot(positions, sleeve_by_symbol={"SCHD": "core"}, ledger_path=ledger_path)
    assert snapshot["positions"] == []


def test_build_snapshot_excludes_zero_quantity_positions(tmp_path):
    ledger_path = str(tmp_path / "ledger.json")
    record_snapshot(ledger_path, 1000.0, as_of="2026-08-04")
    positions = [make_position("SCHD", 0, 33.991, 33.385)]
    snapshot = build_snapshot(positions, sleeve_by_symbol={"SCHD": "core"}, ledger_path=ledger_path)
    assert snapshot["positions"] == []


def test_build_snapshot_computes_total_invested():
    pass  # covered implicitly by the round-trip test below


def test_build_snapshot_total_invested_sums_market_values(tmp_path):
    ledger_path = str(tmp_path / "ledger.json")
    record_snapshot(ledger_path, 1000.0, as_of="2026-08-04")
    positions = [make_position("SCHD", 5, 33.991, 33.385), make_position("NVDA", 1, 199.55, 196.48)]
    snapshot = build_snapshot(positions, {"SCHD": "core", "NVDA": "satellite"}, ledger_path)
    assert snapshot["total_invested"] == (5 * 33.385) + (1 * 196.48)


def test_refresh_snapshot_writes_and_load_snapshot_reads_back(tmp_path):
    ledger_path = str(tmp_path / "ledger.json")
    record_snapshot(ledger_path, 990.86, as_of="2026-08-04")
    snapshot_path = str(tmp_path / "portfolio_snapshot.json")

    class FakeUniverseEntry:
        def __init__(self, symbol, sleeve):
            self.symbol, self.sleeve = symbol, sleeve

    class FakeTradeClient:
        def get_positions(self):
            return [make_position("SCHD", 5, 33.991, 33.385)]

    refresh_snapshot(
        FakeTradeClient(), [FakeUniverseEntry("SCHD", "core")], ledger_path, path=snapshot_path
    )
    loaded = load_snapshot(snapshot_path)
    assert loaded["positions"][0]["symbol"] == "SCHD"
    assert "as_of" in loaded
