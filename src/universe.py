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
    UniverseEntry("IWM", "US", "USD", "", "core"),   # Russell 2000 -- small-cap, diversifies beyond mega-cap
    UniverseEntry("XLK", "US", "USD", "", "core"),   # Technology Select Sector SPDR
    UniverseEntry("DIA", "US", "USD", "", "core"),   # Dow Jones Industrial Average

    # US satellite: momentum-candidate large caps
    UniverseEntry("NVDA", "US", "USD", "", "satellite"),
    UniverseEntry("AMD", "US", "USD", "", "satellite"),
    UniverseEntry("META", "US", "USD", "", "satellite"),
    UniverseEntry("AVGO", "US", "USD", "", "satellite"),
    UniverseEntry("MSFT", "US", "USD", "", "satellite"),
    UniverseEntry("AAPL", "US", "USD", "", "satellite"),
    UniverseEntry("GOOGL", "US", "USD", "", "satellite"),
    UniverseEntry("AMZN", "US", "USD", "", "satellite"),
    UniverseEntry("TSLA", "US", "USD", "", "satellite"),
    UniverseEntry("CRM", "US", "USD", "", "satellite"),

    # US satellite: commodity ETFs -- these trade as plain equities from
    # Tiger's perspective (stock_contract, same order-placement path as
    # everything else here), unlike real futures contracts, which need
    # margin/expiry handling this project doesn't have yet. Momentum-
    # scored the same as any other satellite candidate, exited via the
    # same stop-loss/momentum-reversal rules -- not a buy-and-hold
    # allocation, which matters for UNG specifically: natural-gas ETFs
    # are known to structurally decay over time from futures-roll costs,
    # a real risk for holding one long-term but less relevant to a
    # system that already exits on momentum reversal.
    UniverseEntry("GLD", "US", "USD", "", "satellite"),   # SPDR Gold Shares
    UniverseEntry("SLV", "US", "USD", "", "satellite"),   # iShares Silver Trust
    UniverseEntry("USO", "US", "USD", "", "satellite"),   # United States Oil Fund
    UniverseEntry("DBC", "US", "USD", "", "satellite"),   # Invesco DB Commodity Index Tracking Fund
    UniverseEntry("CPER", "US", "USD", "", "satellite"),  # United States Copper Index Fund
    UniverseEntry("UNG", "US", "USD", "", "satellite"),   # United States Natural Gas Fund

    # HK satellite: liquid names, but board-lot affordability at $1,000 is
    # NOT assumed here -- filter_affordable_by_lot checks this against real
    # lot_size/price data before these ever reach the risk engine.
    UniverseEntry("00700", "HK", "HKD", "SEHK", "satellite"),  # Tencent
    UniverseEntry("00005", "HK", "HKD", "SEHK", "satellite"),  # HSBC
    UniverseEntry("09988", "HK", "HKD", "SEHK", "satellite"),  # Alibaba (HK listing)
    UniverseEntry("03690", "HK", "HKD", "SEHK", "satellite"),  # Meituan

    # SG core: dividend-heavy local blue chips. Tiger's historical-bars
    # endpoint needs the ".SI" suffix on the symbol itself (confirmed by
    # testing "D05" vs "D05.SI" -- the bare code returns zero bars); the
    # order-placement `symbol` field, once that's built, may differ from
    # this and will need its own check rather than assuming this matches.
    UniverseEntry("D05.SI", "SG", "SGD", "SGX", "core"),   # DBS
    UniverseEntry("O39.SI", "SG", "SGD", "SGX", "core"),   # OCBC
    UniverseEntry("Z74.SI", "SG", "SGD", "SGX", "core"),   # Singtel
    UniverseEntry("U11.SI", "SG", "SGD", "SGX", "core"),   # UOB
]


DIVIDEND_UNIVERSE: List[UniverseEntry] = [
    # US high-yield/dividend names -- deliberately DISJOINT from
    # DEFAULT_UNIVERSE above (see portfolio_profiles.py: since both
    # portfolios share one Tiger account, a symbol can only ever belong
    # to one portfolio's universe, or their ledgers would mis-attribute
    # each other's fills). Every entry uses sleeve="core" -- the dividend
    # portfolio is a single income-focused sleeve, no momentum/satellite
    # picks, no shorting (see portfolio_profiles.DIVIDEND_PROFILE).
    UniverseEntry("JEPI", "US", "USD", "", "core"),   # JPMorgan Equity Premium Income ETF
    UniverseEntry("SPYD", "US", "USD", "", "core"),   # SPDR Portfolio S&P 500 High Dividend ETF
    UniverseEntry("O", "US", "USD", "", "core"),      # Realty Income -- monthly-dividend REIT
    UniverseEntry("KO", "US", "USD", "", "core"),     # Coca-Cola -- dividend aristocrat
    UniverseEntry("JNJ", "US", "USD", "", "core"),    # Johnson & Johnson -- dividend aristocrat
    UniverseEntry("PG", "US", "USD", "", "core"),     # Procter & Gamble -- dividend aristocrat
    UniverseEntry("VZ", "US", "USD", "", "core"),     # Verizon -- high-yield telecom
    UniverseEntry("XOM", "US", "USD", "", "core"),    # ExxonMobil -- dividend aristocrat, energy
    UniverseEntry("CVX", "US", "USD", "", "core"),    # Chevron -- dividend aristocrat, energy
    UniverseEntry("ABBV", "US", "USD", "", "core"),   # AbbVie -- dividend grower, pharma
    UniverseEntry("MO", "US", "USD", "", "core"),     # Altria -- very high yield
    UniverseEntry("VNQ", "US", "USD", "", "core"),    # Vanguard Real Estate ETF -- REIT basket
    UniverseEntry("HDV", "US", "USD", "", "core"),    # iShares Core High Dividend ETF

    # HK/SG dividend payers not already claimed by DEFAULT_UNIVERSE.
    UniverseEntry("00002", "HK", "HKD", "SEHK", "core"),  # CLP Holdings -- utility, stable dividend
    UniverseEntry("00006", "HK", "HKD", "SEHK", "core"),  # Power Assets Holdings -- utility, stable dividend
    UniverseEntry("C38U.SI", "SG", "SGD", "SGX", "core"), # CapitaLand Integrated Commercial Trust -- REIT
]


def entries_for_sleeve(sleeve: str, universe: List[UniverseEntry] = None) -> List[UniverseEntry]:
    universe = universe if universe is not None else DEFAULT_UNIVERSE
    return [e for e in universe if e.sleeve == sleeve]


def entries_for_market(market: str, universe: List[UniverseEntry] = None) -> List[UniverseEntry]:
    universe = universe if universe is not None else DEFAULT_UNIVERSE
    return [e for e in universe if e.market == market]
