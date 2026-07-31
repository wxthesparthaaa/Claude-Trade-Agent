"""
Thin wrapper around Tiger's order-placement API. This is the ONLY module in
the whole project that calls TradeClient.place_order() -- every order it
places must already have come from execution.reconcile_positions() and
passed risk_engine.validate_trade(); this module never decides whether an
order should happen, only how to submit one that's already been approved.
"""
from tigeropen.common.util.contract_utils import stock_contract
from tigeropen.common.util.order_utils import market_order


def build_contract(symbol: str, currency: str, exchange: str = ""):
    """exchange="" lets Tiger infer it (fine for US); HK/SG need it explicit (e.g. 'SEHK', 'SGX')."""
    return stock_contract(symbol, currency=currency, exchange=exchange or None)


def place_market_order(trade_client, account: str, contract, action: str, quantity: int):
    """
    action: "BUY" | "SELL". Returns the order object (with .id populated)
    after Tiger accepts it. Raises whatever TradeClient.place_order raises
    on rejection -- callers must not swallow that silently.
    """
    if quantity <= 0:
        raise ValueError(f"quantity must be positive, got {quantity}")
    if action not in ("BUY", "SELL"):
        raise ValueError(f"action must be 'BUY' or 'SELL', got '{action}'")

    order = market_order(account, contract, action, quantity)
    trade_client.place_order(order)
    return order
