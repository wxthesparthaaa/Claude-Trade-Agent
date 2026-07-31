"""
Run with:
    pytest tests/test_tiger_order_adapter.py -v

Uses a fake TradeClient stub -- no real network calls, no real orders ever
placed by these tests.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from tiger_order_adapter import build_contract, place_market_order


class FakeTradeClient:
    def __init__(self):
        self.placed_orders = []

    def place_order(self, order):
        order.id = 12345
        self.placed_orders.append(order)


def test_build_contract_for_us_symbol():
    contract = build_contract("NVDA", currency="USD")
    assert contract.symbol == "NVDA"
    assert contract.currency == "USD"


def test_build_contract_for_hk_symbol_with_exchange():
    contract = build_contract("00700", currency="HKD", exchange="SEHK")
    assert contract.symbol == "00700"
    assert contract.currency == "HKD"


def test_place_market_order_calls_trade_client(monkeypatch):
    fake_client = FakeTradeClient()
    contract = build_contract("NVDA", currency="USD")

    order = place_market_order(fake_client, account="12345", contract=contract, action="BUY", quantity=10)

    assert len(fake_client.placed_orders) == 1
    assert order.id == 12345
    assert order is fake_client.placed_orders[0]


def test_place_market_order_rejects_nonpositive_quantity():
    fake_client = FakeTradeClient()
    contract = build_contract("NVDA", currency="USD")
    with pytest.raises(ValueError):
        place_market_order(fake_client, account="12345", contract=contract, action="BUY", quantity=0)
    assert fake_client.placed_orders == []


def test_place_market_order_rejects_invalid_action():
    fake_client = FakeTradeClient()
    contract = build_contract("NVDA", currency="USD")
    with pytest.raises(ValueError):
        place_market_order(fake_client, account="12345", contract=contract, action="HOLD", quantity=10)
    assert fake_client.placed_orders == []
