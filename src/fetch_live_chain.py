"""
Run with:
    python scripts/fetch_live_chain.py

Fetches a REAL option chain (via your paper account credentials), converts
it through the adapter, and ranks it through the strategy layer -- the
first time real data flows through the whole pipeline.

Today is Sunday: markets are closed. Expect one of two outcomes:
  1. Tiger returns last Friday's close as a snapshot -- pipeline works,
     but don't treat the prices as tradeable right now.
  2. You get a permission error on the option chain call specifically.
     This is expected if the real-time US options data add-on isn't
     purchased yet (separate from the free historical options quota) --
     it does NOT mean the code is broken. get_option_expirations may
     still work even if get_option_chain doesn't, since it's metadata
     rather than live pricing.
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import Market

from tiger_option_adapter import fetch_expirations, get_option_contracts_for_expiry
from strategy import StrategyConfig, generate_candidates

SYMBOL = "AAPL"


def main():
    client_config = get_client_config()
    quote_client = QuoteClient(client_config)

    print(f"Fetching expirations for {SYMBOL}...")
    expirations = fetch_expirations(quote_client, SYMBOL, market=Market.US)
    print(expirations.head(10))

    if expirations.empty:
        print("No expirations returned. Stopping here.")
        return

    nearest_expiry = expirations.iloc[0]["date"]
    print(f"\nUsing nearest expiry: {nearest_expiry}")

    config = StrategyConfig()
    print(f"\nFetching option chain (this is the call that needs the "
          f"real-time options data permission)...")
    contracts = get_option_contracts_for_expiry(
        quote_client,
        symbol=SYMBOL,
        expiry=nearest_expiry,
        put_call="PUT",
        delta_min=config.target_delta_min,
        delta_max=config.target_delta_max,
        open_interest_min=config.min_open_interest,
        market=Market.US,
    )
    print(f"Fetched {len(contracts)} PUT contracts matching delta/OI filters.")

    candidates = generate_candidates(
        contracts, "cash_secured_put", config, as_of=date.today()
    )
    print(f"\n--- Top candidates ({len(candidates)}) ---")
    for c in candidates[:5]:
        print(f"{c.symbol} ${c.strike} strike, exp {c.expiry}, delta {c.delta:.2f}, "
              f"premium ${c.premium_per_share:.2f}, weekly yield {c.weekly_yield_estimate:.2%}")

    print("\nPipeline ran end to end (fetch -> parse -> rank).")


if __name__ == "__main__":
    main()
