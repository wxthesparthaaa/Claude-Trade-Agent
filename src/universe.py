"""
Multi-market tradable universe for the stock/ETF strategy: US, HK, and SG,
split into a "core" sleeve (broad index/dividend/bond ETFs -- stability) and
a "satellite" sleeve (individual stocks with real momentum/dividend
potential, sized more aggressively per the user's "chase the target harder"
choice). Each entry carries the currency/exchange metadata Tiger's
`stock_contract()` will eventually need to place an order, even though order
placement itself is out of scope for now.

This is a STARTING list, not a guarantee any name is tradable or affordable
today -- board-lot affordability (HK/SG especially) is checked separately in
portfolio_construction.filter_affordable_by_lot using real trade-meta data,
not assumed here.
"""
from dataclasses import dataclass
from typing import List


@dataclass
class UniverseEntry:
    symbol: str        # Tiger's symbol format for this market
    market: str         # "US" | "HK" | "SG" -- matches tigeropen.common.consts.Market values
    currency: str        # "USD" | "HKD" | "SGD" -- matches tigeropen.common.consts.Currency values
    exchange: str         # e.g. "SEHK", "SGX"; None/"" is fine for US (Tiger infers it)
    sleeve: str            # "core" | "satellite"


DEFAULT_UNIVERSE: List[UniverseEntry] = [
    # US core: broad index, dividend, and bond ETFs
    UniverseEntry("VOO", "US", "USD", "", "core"),
    UniverseEntry("QQQ", "US", "USD", "", "core"),
    UniverseEntry("SCHD", "US", "USD", "", "core"),
    UniverseEntry("VYM", "US", "USD", "", "core"),
    UniverseEntry("AGG", "US", "USD", "", "core"),
    UniverseEntry("TLT", "US", "USD", "", "core"),

    # US satellite: momentum-candidate large caps
    UniverseEntry("NVDA", "US", "USD", "", "satellite"),
    UniverseEntry("AMD", "US", "USD", "", "satellite"),
    UniverseEntry("META", "US", "USD", "", "satellite"),
    UniverseEntry("AVGO", "US", "USD", "", "satellite"),

    # HK satellite: liquid names, but board-lot affordability at $1,000 is
    # NOT assumed here -- filter_affordable_by_lot checks this against real
    # lot_size/price data before these ever reach the risk engine.
    UniverseEntry("00700", "HK", "HKD", "SEHK", "satellite"),  # Tencent
    UniverseEntry("00005", "HK", "HKD", "SEHK", "satellite"),  # HSBC

    # SG core: dividend-heavy local blue chips. Tiger's historical-bars
    # endpoint needs the ".SI" suffix on the symbol itself (confirmed by
    # testing "D05" vs "D05.SI" -- the bare code returns zero bars); the
    # order-placement `symbol` field, once that's built, may differ from
    # this and will need its own check rather than assuming this matches.
    UniverseEntry("D05.SI", "SG", "SGD", "SGX", "core"),   # DBS
    UniverseEntry("O39.SI", "SG", "SGD", "SGX", "core"),   # OCBC
    UniverseEntry("Z74.SI", "SG", "SGD", "SGX", "core"),   # Singtel
]


def entries_for_sleeve(sleeve: str, universe: List[UniverseEntry] = None) -> List[UniverseEntry]:
    universe = universe if universe is not None else DEFAULT_UNIVERSE
    return [e for e in universe if e.sleeve == sleeve]


def entries_for_market(market: str, universe: List[UniverseEntry] = None) -> List[UniverseEntry]:
    universe = universe if universe is not None else DEFAULT_UNIVERSE
    return [e for e in universe if e.market == market]
