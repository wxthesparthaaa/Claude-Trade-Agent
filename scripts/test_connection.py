"""
Run this first, before anything else, to confirm your Tiger Open API
credentials actually work.

Usage:
    python scripts/test_connection.py

Expected output: your paper account's asset summary (cash, buying power,
positions). If you see a "public key error" or "1000" error code, your
tiger_id/account/private_key combination doesn't match what's on file with
Tiger — double check config/tiger_openapi_config.properties.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient


def main():
    client_config = get_client_config()
    print(f"Loaded config for tiger_id={client_config.tiger_id}, "
          f"account={client_config.account}")

    trade_client = TradeClient(client_config)
    assets = trade_client.get_assets()
    print("\n--- Account assets ---")
    for a in assets:
        print(a)

    quote_client = QuoteClient(client_config)
    # get_stock_delay_briefs does NOT require a paid market data
    # subscription -- it's free, 15-minute delayed, US stocks only.
    # Good enough to confirm the pipeline works without spending anything.
    briefs = quote_client.get_stock_delay_briefs(["AAPL"])
    print("\n--- Sample market data (AAPL, 15-min delayed, free tier) ---")
    print(briefs)

    print("\nConnection test passed.")


if __name__ == "__main__":
    main()
