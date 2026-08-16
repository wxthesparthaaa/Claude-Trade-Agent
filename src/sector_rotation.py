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

Each region's signal also carries a finer breakdown one GICS level below
sector -- Industry Group (e.g. "Semiconductors & Semiconductor Equipment"
within Technology) -- via rank_industries_by_gics, same momentum-
aggregation proxy method as the HK sector ranking, applied to both US and
HK using whichever symbols get GICS-tagged during a refresh (today: both
profiles' effective universes). No SPDR-equivalent ETF set exists at this
granularity, so this is intentionally always a proxy, not a dedicated
ETF-based ranking, for either region.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, List, Optional

from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df
from market_breadth import compute_ratio_series, compute_breadth_signal
from stock_signal import momentum_score
from tiger_industry_adapter import SectorTag, load_sector_tags, save_sector_tags, get_gics_sector_id_cached

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
class IndustryRankEntry:
    industry_name: str          # GICS Industry Group (GGROUP) display name, e.g. "Semiconductors & Semiconductor Equipment"
    gics_group_id: str
    parent_sector_name: str     # the broad sector this group rolls up into, e.g. "Technology"
    roc: float
    rank: int


@dataclass
class SectorRotationSignal:
    as_of: str
    region: str      # "US" | "HK" | "SG"
    method: str       # "sector_etf" | "gics_aggregate" | "unavailable"
    entries: List[SectorRankEntry]
    note: str = ""
    industries: List[IndustryRankEntry] = field(default_factory=list)


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


def rank_industries_by_gics(
    momentum_by_symbol: Dict[str, float], tags_by_symbol: Dict[str, SectorTag],
) -> List[IndustryRankEntry]:
    """Pure -- no network. Finer-grained sibling of rank_hk_sectors_by_gics:
    averages momentum by GICS Industry Group (GGROUP) -- one level below
    the 11 broad sectors -- instead of by sector, using the group id/name
    already captured on each SectorTag (see
    tiger_industry_adapter.get_gics_classification). Symbols with no group
    classification are excluded, not treated as 0% momentum. Same
    proxy-not-ETF caveat as the HK sector ranking -- this is an average of
    whatever stocks happen to be tagged, not a dedicated industry-group ETF
    ranking."""
    momentum_by_group: Dict[str, List[float]] = {}
    name_by_group: Dict[str, str] = {}
    sector_name_by_group: Dict[str, str] = {}

    for symbol, momentum in momentum_by_symbol.items():
        tag = tags_by_symbol.get(symbol)
        if tag is None or tag.gics_group_id is None:
            continue
        group_id = tag.gics_group_id
        momentum_by_group.setdefault(group_id, []).append(momentum)
        name_by_group[group_id] = tag.gics_group_name or group_id
        sector_name_by_group[group_id] = GICS_SECTOR_NAMES.get(tag.gics_sector_id, tag.gics_sector_id or "")

    ranked = sorted(momentum_by_group.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)

    return [
        IndustryRankEntry(
            industry_name=name_by_group[group_id], gics_group_id=group_id,
            parent_sector_name=sector_name_by_group[group_id],
            roc=sum(momenta) / len(momenta), rank=i + 1,
        )
        for i, (group_id, momenta) in enumerate(ranked)
    ]


def distinct_industries(entries: List[IndustryRankEntry]) -> List[IndustryRankEntry]:
    """Pure, display-only filter -- NOT used for suggestion-sourcing
    (app.py's scheduled_sector_rotation_update reads the full,
    unfiltered rank_industries_by_gics output directly, since the
    single most specific classification is still the right thing to
    suggest from even when it happens to equal its sector's number).

    Drops an entry when it's the ONLY industry group representing its
    parent sector in this ranking -- with a thin tagged pool (e.g. one
    stock covering an entire sector), that entry's average is
    mathematically identical to the sector-level line already shown
    above it, so showing it again as an "industry" adds no information
    and just reads as a confusing duplicate. Re-ranks the survivors 1..N
    so the displayed list has no gaps."""
    sector_counts: Dict[str, int] = {}
    for e in entries:
        sector_counts[e.parent_sector_name] = sector_counts.get(e.parent_sector_name, 0) + 1

    survivors = [e for e in entries if sector_counts[e.parent_sector_name] > 1]
    return [
        IndustryRankEntry(
            industry_name=e.industry_name, gics_group_id=e.gics_group_id,
            parent_sector_name=e.parent_sector_name, roc=e.roc, rank=i + 1,
        )
        for i, e in enumerate(survivors)
    ]


def sg_unavailable_signal() -> SectorRotationSignal:
    return SectorRotationSignal(
        as_of=date.today().isoformat(), region="SG", method="unavailable", entries=[],
        note="Sector classification isn't available for SG through Tiger's API (confirmed unsupported).",
    )


def _tag_and_score(quote_client, symbols: List[str], market: str, tags: Dict[str, SectorTag]) -> Dict[str, float]:
    """Shared by both regions: GICS-tags (mutating `tags` in place, see
    get_gics_sector_id_cached) and momentum-scores a pool of symbols, for
    both the sector-level ranking (HK) and the industry-group-level
    ranking (US and HK, see rank_industries_by_gics). Tagging is skipped
    for a symbol whose momentum fetch itself failed, same tolerance as
    every other bars-fetch loop in this codebase."""
    momentum_by_symbol = {}
    for symbol in symbols:
        try:
            df = fetch_stock_bars(quote_client, symbol, limit=200)
            prices = parse_stock_bars_df(df)
            momentum_by_symbol[symbol] = momentum_score(prices)
        except Exception as e:
            print(f"Momentum fetch failed for {symbol} ({market}): {type(e).__name__}: {e}")
            continue
        get_gics_sector_id_cached(quote_client, symbol, market, tags)
    return momentum_by_symbol


def refresh_sector_rotation(
    quote_client, us_symbols: List[str], hk_symbols: List[str], sector_tags_path: str,
) -> Dict[str, SectorRotationSignal]:
    """Orchestrates a full refresh across all three regions -- what the
    daily scheduled job calls. us_symbols/hk_symbols: whichever symbols
    are worth GICS-tagging (e.g. both profiles' effective universes,
    combined per market) -- used for the industry-group breakdown on both
    regions, and for HK's sector-level ranking itself (US's sector-level
    ranking stays ETF-based, unaffected by this tagging pass). Persists
    sector-tag cache updates as a side effect (see
    tiger_industry_adapter.py)."""
    us_prices = fetch_us_sector_prices(quote_client)
    us_signal = rank_us_sectors(us_prices)

    tags = load_sector_tags(sector_tags_path)
    us_momentum = _tag_and_score(quote_client, us_symbols, "US", tags)
    hk_momentum = _tag_and_score(quote_client, hk_symbols, "HK", tags)
    save_sector_tags(sector_tags_path, tags)

    us_signal.industries = rank_industries_by_gics(us_momentum, tags)

    hk_gics_by_symbol = {symbol: tag.gics_sector_id for symbol, tag in tags.items()}
    hk_signal = rank_hk_sectors_by_gics(hk_momentum, hk_gics_by_symbol)
    hk_signal.industries = rank_industries_by_gics(hk_momentum, tags)

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
            industries=[IndustryRankEntry(**i) for i in entry.get("industries", [])],
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
