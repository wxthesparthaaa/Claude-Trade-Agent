"""
Run with:
    pytest tests/test_order_execution.py -v

Uses fake TradeClient/UniverseEntry stand-ins -- no real network calls,
no real orders ever placed by these tests.
"""
import sys
import os
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import order_execution
from order_execution import execute_instructions
from execution import OrderInstruction


@dataclass
class FakeUniverseEntry:
    symbol: str
    currency: str
    exchange: str = ""


@dataclass
class FakeOrder:
    id: int
    status: str
    filled_cash_amount: float
    commission: float


@dataclass
class FakeContract:
    symbol: str
    market_value: float = 0.0


@dataclass
class FakePosition:
    contract: FakeContract
    market_value: float


class FakeTradeClient:
    def __init__(self, orders, positions_after):
        self._orders = orders
        self._positions_after = positions_after
        self.placed_orders = []
        self._next_id = 1

    def get_positions(self):
        return self._positions_after

    def get_orders(self):
        return self._orders

    def place_order(self, order):
        order.id = self._next_id
        self._next_id += 1
        self.placed_orders.append(order)


def _stub_no_telegram(monkeypatch):
    def raise_not_found():
        raise FileNotFoundError("not configured")
    monkeypatch.setattr(order_execution, "get_telegram_config", raise_not_found)


def _stub_no_github(monkeypatch):
    monkeypatch.setattr(order_execution, "push_state_to_github", lambda p: False)


def test_execute_instructions_buy_updates_ledger_and_reports(tmp_path, monkeypatch):
    _stub_no_telegram(monkeypatch)
    _stub_no_github(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")

    from strategy_ledger import load_or_init_ledger
    load_or_init_ledger(ledger_path, 1000.0)

    fake_orders = [FakeOrder(id=1, status="FILLED", filled_cash_amount=196.57, commission=2.98)]
    fake_positions_after = [FakePosition(FakeContract("NVDA"), market_value=196.48)]
    trade_client = FakeTradeClient(fake_orders, fake_positions_after)

    universe_by_symbol = {"NVDA": FakeUniverseEntry("NVDA", "USD")}
    instructions = [OrderInstruction("NVDA", "BUY", 1, 196.57, "top satellite pick")]

    class FakeClientConfig:
        account = "12345"

    result = execute_instructions(
        trade_client, FakeClientConfig(), universe_by_symbol, instructions,
        sleeve_by_symbol={"NVDA": "satellite"}, capital=1000.0, ledger_path=ledger_path,
    )

    assert len(trade_client.placed_orders) == 1
    assert result.order_ids == [1]
    assert result.cash_delta == -(196.57 + 2.98)
    assert result.total_invested_after == 196.48
    assert result.new_capital == pytest.approx(1000.0 - 199.55 + 196.48)
    assert "BUY 1 NVDA" in result.telegram_text
    assert result.telegram_sent is False  # Telegram unconfigured in this test


def test_execute_instructions_sell_nets_commission_from_proceeds(tmp_path, monkeypatch):
    # Regression test for a real bug this test caught: commission was being
    # ADDED to sell proceeds instead of subtracted, overstating cash_reserve
    # by 2x the commission on every future sell (never exercised before
    # since every real trade so far had been a BUY).
    _stub_no_telegram(monkeypatch)
    _stub_no_github(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")

    from strategy_ledger import load_or_init_ledger, apply_trade_and_snapshot
    load_or_init_ledger(ledger_path, 1000.0)
    apply_trade_and_snapshot(ledger_path, cash_delta=-500.0, positions_value_now=500.0, as_of="2026-08-01")

    fake_orders = [FakeOrder(id=1, status="FILLED", filled_cash_amount=510.0, commission=3.0)]
    trade_client = FakeTradeClient(fake_orders, positions_after=[])

    universe_by_symbol = {"NVDA": FakeUniverseEntry("NVDA", "USD")}
    instructions = [OrderInstruction("NVDA", "SELL", 1, 510.0, "exit")]

    class FakeClientConfig:
        account = "12345"

    result = execute_instructions(
        trade_client, FakeClientConfig(), universe_by_symbol, instructions,
        sleeve_by_symbol={"NVDA": "satellite"}, capital=1000.0, ledger_path=ledger_path,
    )

    assert result.cash_delta == 510.0 - 3.0
    assert result.total_invested_after == 0.0
    assert result.new_capital == pytest.approx(500.0 + 507.0)


def test_execute_instructions_falls_back_to_sizing_estimate_when_fill_data_missing(tmp_path, monkeypatch):
    _stub_no_telegram(monkeypatch)
    _stub_no_github(monkeypatch)
    ledger_path = str(tmp_path / "ledger.json")

    from strategy_ledger import load_or_init_ledger
    load_or_init_ledger(ledger_path, 1000.0)

    # No matching order in get_orders() -- fill data not ready yet.
    trade_client = FakeTradeClient(orders=[], positions_after=[FakePosition(FakeContract("NVDA"), market_value=200.0)])

    universe_by_symbol = {"NVDA": FakeUniverseEntry("NVDA", "USD")}
    instructions = [OrderInstruction("NVDA", "BUY", 1, 196.57, "top satellite pick")]

    class FakeClientConfig:
        account = "12345"

    result = execute_instructions(
        trade_client, FakeClientConfig(), universe_by_symbol, instructions,
        sleeve_by_symbol={"NVDA": "satellite"}, capital=1000.0, ledger_path=ledger_path,
    )

    assert result.cash_delta == -196.57  # fell back to the sizing-time notional


def test_execute_instructions_sends_telegram_when_configured(tmp_path, monkeypatch):
    _stub_no_github(monkeypatch)
    sent = []

    class FakeTelegramConfig:
        bot_token = "tok"
        chat_id = "chat"

    monkeypatch.setattr(order_execution, "get_telegram_config", lambda: FakeTelegramConfig())
    monkeypatch.setattr(order_execution, "send_message", lambda text, token, chat_id: sent.append(text))

    ledger_path = str(tmp_path / "ledger.json")
    from strategy_ledger import load_or_init_ledger
    load_or_init_ledger(ledger_path, 1000.0)

    fake_orders = [FakeOrder(id=1, status="FILLED", filled_cash_amount=196.57, commission=2.98)]
    trade_client = FakeTradeClient(fake_orders, positions_after=[FakePosition(FakeContract("NVDA"), market_value=196.48)])

    class FakeClientConfig:
        account = "12345"

    result = execute_instructions(
        trade_client, FakeClientConfig(), {"NVDA": FakeUniverseEntry("NVDA", "USD")},
        [OrderInstruction("NVDA", "BUY", 1, 196.57, "top pick")],
        sleeve_by_symbol={"NVDA": "satellite"}, capital=1000.0, ledger_path=ledger_path,
    )

    assert result.telegram_sent is True
    assert len(sent) == 1
