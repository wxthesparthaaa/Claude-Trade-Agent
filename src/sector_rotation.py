"""
Sector rotation: "where is money flowing right now." US ranks the 11 SPDR
sector ETFs by relative strength vs SPY, reusing market_breadth.py's exact
ratio/MA-trend/ROC-zscore machinery (same fetch_stock_bars ->
compute_ratio_series -> compute_breadth_signal pipeline, just run once
per sector instead of once for RSP) -- the mechanical, primary signal.
See investment_clock.py for the qualitative macro-phase overlay this is
meant to be compared against, not derived from.

HK has no comparably liquid, clean sector-ETF set available through this
account, so its ranking is a coarser proxy instead: whatever HK stocks get
GICS-tagged (see tiger_industry_adapter.py) get bucketed by sector and
averaged by momentum_score. SG gets no ranking at all -- GICS
classification is confirmed unavailable there; callers get an explicit
"unavailable" signal rather than a fabricated number.
"""
import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from typing import Dict, List, Optional

from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df
from market_breadth import compute_ratio_series, compute_breadth_signal
from stock_signal import momentum_score
from tiger_industry_adapter import load_sector_tags, save_sector_tags, get_gics_sector_id_cached

SPY_SYMBOL = "SPY"

# SPDR sector ETF -> (display name, GICS top-level GSECTOR id) -- the
# standard 11-sector GICS/SPDR mapping used industry-wide.
US_SECTOR_ETFS = {
    "XLK": ("Technology", "45"),
    "XLF": ("Financials", "40"),
    "XLE": ("Energy", "10"),
    "XLV": ("Health Care", "35"),
    "XLY": ("Consumer Discretionary", "25"),
    "XLP": ("Consumer Staples", "30"),
    "XLI": ("Industrials", "20"),
    "XLB": ("Materials", "15"),
    "XLU": ("Utilities", "55"),
    "XLRE": ("Real Estate", "60"),
    "XLC": ("Communication Services", "50"),
}

# GICS sector id -> display name, derived from the table above -- GICS
# top-level sector names are the same across regions, so this doubles as
# the HK ranking's display-name lookup.
GICS_SECTOR_NAMES: Dict[str, str] = {gics_id: name for _etf, (name, gics_id) in US_SECTOR_ETFS.items()}


@dataclass
class SectorRankEntry:
    sector_name: str
    gics_sector_id: Optional[str]
    etf_symbol: Optional[str]   # None for the HK gics-aggregate method
    trend: str                   # "broadening" | "narrowing" | "flat" vs SPY -- US only, "" otherwise
    roc: float
    roc_zscore: float
    rank: int                    # 1 = strongest recent relative move


@dataclass
class SectorRotationSignal:
    as_of: str
    region: str      # "US" | "HK" | "SG"
    method: str       # "sector_etf" | "gics_aggregate" | "unavailable"
    entries: List[SectorRankEntry]
    note: str = ""


def fetch_us_sector_prices(quote_client, lookback_days: int = 252) -> Dict[str, list]:
    """The only function here that touches the network for the US
    ranking. Mirrors market_breadth.fetch_breadth_prices, just for 12
    symbols (11 sector ETFs + SPY) instead of 2. Skips (rather than
    raises on) any single symbol's fetch failure, same tolerance as
    scan_workflow.py's own bars-fetch loop."""
    symbols = list(US_SECTOR_ETFS.keys()) + [SPY_SYMBOL]
    prices = {}
    for symbol in symbols:
        try:
            df = fetch_stock_bars(quote_client, symbol, limit=lookback_days + 30)
            prices[symbol] = parse_stock_bars_df(df)
        except Exception as e:
            print(f"Sector ETF bars fetch failed for {symbol}: {type(e).__name__}: {e}")
    return prices


def rank_us_sectors(prices_by_symbol: Dict[str, list]) -> SectorRotationSignal:
    """Pure -- no network. Ranks every SPDR sector ETF with enough
    history by its 20-day rate-of-change relative to SPY (recent
    acceleration -- "where money is flowing right now"), descending.
    Sectors without enough history yet are silently skipped, same
    "not eligible yet" convention used throughout this codebase."""
    spy_prices = prices_by_symbol.get(SPY_SYMBOL, [])
    ranked = []
    for etf_symbol, (sector_name, gics_id) in US_SECTOR_ETFS.items():
        etf_prices = prices_by_symbol.get(etf_symbol, [])
        if not etf_prices or not spy_prices:
            continue
        ratio_series = compute_ratio_series(etf_prices, spy_prices)
        signal = compute_breadth_signal(ratio_series)
        if signal is None:
            continue
        ranked.append((sector_name, gics_id, etf_symbol, signal))

    ranked.sort(key=lambda t: t[3].roc, reverse=True)

    entries = [
        SectorRankEntry(
            sector_name=name, gics_sector_id=gics_id, etf_symbol=etf_symbol,
            trend=signal.trend, roc=signal.roc, roc_zscore=signal.roc_zscore, rank=i + 1,
        )
        for i, (name, gics_id, etf_symbol, signal) in enumerate(ranked)
    ]

    return SectorRotationSignal(
        as_of=date.today().isoformat(), region="US", method="sector_etf", entries=entries,
        note="" if entries else "Not enough price history yet for any sector ETF.",
    )


def rank_hk_sectors_by_gics(
    momentum_by_symbol: Dict[str, float], gics_sector_id_by_symbol: Dict[str, Optional[str]],
    sector_name_by_gics_id: Dict[str, str] = None,
) -> SectorRotationSignal:
    """Pure -- no network. Coarser proxy than the US ranking: averages
    already-computed momentum scores (see stock_signal.momentum_score)
    for whatever HK stocks have a known GICS sector, bucketed by sector.
    Symbols with gics_sector_id=None (untagged, or a lookup failure) are
    excluded entirely, not treated as 0% momentum."""
    sector_name_by_gics_id = sector_name_by_gics_id if sector_name_by_gics_id is not None else GICS_SECTOR_NAMES

    momentum_by_gics: Dict[str, List[float]] = {}
    for symbol, momentum in momentum_by_symbol.items():
        gics_id = gics_sector_id_by_symbol.get(symbol)
        if gics_id is None:
            continue
        momentum_by_gics.setdefault(gics_id, []).append(momentum)

    ranked = sorted(momentum_by_gics.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)

    entries = [
        SectorRankEntry(
            sector_name=sector_name_by_gics_id.get(gics_id, gics_id), gics_sector_id=gics_id,
            etf_symbol=None, trend="", roc=sum(momenta) / len(momenta), roc_zscore=0.0, rank=i + 1,
        )
        for i, (gics_id, momenta) in enumerate(ranked)
    ]

    return SectorRotationSignal(
        as_of=date.today().isoformat(), region="HK", method="gics_aggregate", entries=entries,
        note=(
            "Coarser proxy: averaged momentum of tagged HK stocks currently scanned, "
            "not a dedicated sector-ETF ranking."
        ) if entries else "No GICS-tagged HK stocks scored yet.",
    )


def sg_unavailable_signal() -> SectorRotationSignal:
    return SectorRotationSignal(
        as_of=date.today().isoformat(), region="SG", method="unavailable", entries=[],
        note="Sector classification isn't available for SG through Tiger's API (confirmed unsupported).",
    )


def refresh_sector_rotation(quote_client, hk_symbols: List[str], sector_tags_path: str) -> Dict[str, SectorRotationSignal]:
    """Orchestrates a full refresh across all three regions -- what the
    daily scheduled job calls. hk_symbols: whichever HK symbols are worth
    tagging (e.g. both profiles' universes combined). Persists sector-tag
    cache updates as a side effect (see tiger_industry_adapter.py)."""
    us_prices = fetch_us_sector_prices(quote_client)
    us_signal = rank_us_sectors(us_prices)

    tags = load_sector_tags(sector_tags_path)
    momentum_by_symbol = {}
    gics_by_symbol = {}
    for symbol in hk_symbols:
        try:
            df = fetch_stock_bars(quote_client, symbol, limit=200)
            prices = parse_stock_bars_df(df)
            momentum_by_symbol[symbol] = momentum_score(prices)
        except Exception as e:
            print(f"HK sector momentum failed for {symbol}: {type(e).__name__}: {e}")
            continue
        gics_by_symbol[symbol] = get_gics_sector_id_cached(quote_client, symbol, "HK", tags)
    save_sector_tags(sector_tags_path, tags)
    hk_signal = rank_hk_sectors_by_gics(momentum_by_symbol, gics_by_symbol)

    return {"US": us_signal, "HK": hk_signal, "SG": sg_unavailable_signal()}


def load_sector_rotation(path: str) -> Dict[str, SectorRotationSignal]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        region: SectorRotationSignal(
            as_of=entry["as_of"], region=entry["region"], method=entry["method"],
            entries=[SectorRankEntry(**e) for e in entry["entries"]], note=entry.get("note", ""),
        )
        for region, entry in data.items()
    }


def save_sector_rotation(path: str, signals: Dict[str, SectorRotationSignal]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({region: asdict(sig) for region, sig in signals.items()}, f, indent=2)


def get_sector_tilt(rotation_signal: Optional[SectorRotationSignal], gics_sector_id: Optional[str]) -> float:
    """Pure. Returns a bounded tilt in [-1, 1] for
    stock_signal.composite_score's sector_tilt term: +1.0 for the single
    top-ranked sector, linearly decaying to -1.0 for the lowest-ranked,
    0.0 if the symbol's sector is unknown, unranked, or the signal has no
    entries at all (e.g. SG's sg_unavailable_signal, or before the first
    daily refresh has ever run) -- same "absence is neutral, not a
    penalty" convention news_scanner.get_tilt already uses."""
    if rotation_signal is None or gics_sector_id is None or not rotation_signal.entries:
        return 0.0
    n = len(rotation_signal.entries)
    for entry in rotation_signal.entries:
        if entry.gics_sector_id == gics_sector_id:
            if n == 1:
                return 1.0
            return 1.0 - 2.0 * (entry.rank - 1) / (n - 1)
    return 0.0
