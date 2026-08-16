"""
Sector/industry classification and a liquidity screener via Tiger's own
market data API (`tigeropen`), previously unused in this codebase. Same
fetch_*/parse_* split as every other adapter here -- fetch_* is the only
code touching the network, parse_* is pure and unit-testable offline.

GICS sector classification (get_stock_industry/get_industry_stocks) is
confirmed working for US and HK, but NOT SG -- a real Tiger API call
against every SG symbol tried (including live-pulled ones) fails with
"biz param error(failed to parse parameters in 'biz_content')" regardless
of symbol format. get_gics_sector_id below surfaces that as None for SG
rather than raising, so callers degrade gracefully instead of crashing.

Tiger's own screener (market_scanner) uses a SEPARATE, proprietary
"BK####" tag taxonomy for its own sector filter (MultiTagField.Industry)
-- NOT the numeric GICS ids this module otherwise deals in (confirmed
live: feeding a GICS id into that filter returns zero results). To avoid
mixing the two taxonomies, fetch_liquid_movers below only ever uses
market_scanner's liquidity filter (StockField.Volume), never its own
sector filter; sector matching is done afterward as a plain symbol-set
intersection against fetch_industry_stocks' GICS-based result -- see
sector_rotation.py / sector_suggestions.py.
"""
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from tigeropen.common.consts import Market
from tigeropen.common.consts.filter_fields import StockField
from tigeropen.quote.domain.filter import StockFilter

GICS_CACHE_MAX_AGE_DAYS = 30  # sector membership rarely changes; avoid re-querying Tiger every scan

_MARKET_ENUM = {"US": Market.US, "HK": Market.HK, "SG": Market.SG}


@dataclass
class SectorTag:
    symbol: str
    gics_sector_id: Optional[str]  # top-level GICS "GSECTOR" id, e.g. "45" -- None if unclassifiable
    looked_up_at: str              # "YYYY-MM-DD"


def fetch_stock_industry(quote_client, symbol: str, market) -> list:
    """The only function here that calls get_stock_industry. `market` is a
    tigeropen Market enum member (see _market_enum)."""
    return quote_client.get_stock_industry(symbol, market=market)


def parse_gics_sector_id(raw: list) -> Optional[str]:
    """Pure -- raw is get_stock_industry's return: a list of
    {'industry_level', 'id', 'name_cn', 'name_en'} dicts across GICS
    levels (GSECTOR/GGROUP/GIND/GSUBIND). Returns the top-level GSECTOR
    id, or None if the symbol has no classification at all."""
    for entry in raw or []:
        if entry.get("industry_level") == "GSECTOR":
            return entry.get("id")
    return None


def fetch_industry_stocks(quote_client, gics_sector_id: str, market) -> list:
    """The only function here that calls get_industry_stocks."""
    return quote_client.get_industry_stocks(gics_sector_id, market=market)


def parse_industry_stocks(raw: list) -> List[str]:
    """Pure -- raw is get_industry_stocks' return: a list of
    {'symbol', 'company_name', 'market', 'industry_list'} dicts."""
    return [entry["symbol"] for entry in raw or [] if entry.get("symbol")]


def fetch_liquid_movers(quote_client, market, min_volume: float = 1_000_000, page_size: int = 100):
    """The only function here that calls market_scanner. Liquidity filter
    ONLY (see module docstring) -- deliberately never combined with
    market_scanner's own sector-tag filter, which uses a taxonomy
    disjoint from GICS."""
    result = quote_client.market_scanner(
        market=market,
        filters=[StockFilter(field=StockField.Volume, filter_min=min_volume)],
        page_size=page_size,
    )
    return result.items if result else []


def parse_liquid_movers(items) -> List[str]:
    """Pure -- items is fetch_liquid_movers' return: a list of
    ScannerResultItem objects, each with a `.symbol` attribute."""
    return [item.symbol for item in items or [] if getattr(item, "symbol", None)]


def get_gics_sector_id(quote_client, symbol: str, market: str) -> Optional[str]:
    """Convenience wrapper: fetch + parse for one symbol, `market` as a
    plain "US"/"HK"/"SG" string (matching UniverseEntry.market). Swallows
    any error -- including the confirmed SG failure, handled explicitly
    below rather than paying for a network round-trip that's known to
    fail -- and returns None rather than raising, so one bad symbol never
    breaks a batch tagging job."""
    if market == "SG":
        return None
    try:
        raw = fetch_stock_industry(quote_client, symbol, _MARKET_ENUM.get(market, Market.US))
        return parse_gics_sector_id(raw)
    except Exception as e:
        print(f"GICS lookup failed for {symbol} ({market}): {type(e).__name__}: {e}")
        return None


def load_sector_tags(path: str) -> Dict[str, SectorTag]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {symbol: SectorTag(**entry) for symbol, entry in data.items()}


def save_sector_tags(path: str, tags: Dict[str, SectorTag]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({symbol: asdict(tag) for symbol, tag in tags.items()}, f, indent=2)


def get_gics_sector_id_cached(
    quote_client, symbol: str, market: str, cache: Dict[str, SectorTag],
    as_of: Optional[str] = None, max_age_days: int = GICS_CACHE_MAX_AGE_DAYS,
) -> Optional[str]:
    """Looks up symbol's GICS sector, consulting/updating `cache` (mutated
    in place, same dict-in-place-update style as shortlist.py's by_symbol)
    to avoid re-querying Tiger for a classification that rarely changes.
    Refreshes only if missing or older than max_age_days."""
    as_of = as_of or date.today().isoformat()
    existing = cache.get(symbol)
    if existing is not None:
        looked_up = date.fromisoformat(existing.looked_up_at)
        if date.fromisoformat(as_of) - looked_up <= timedelta(days=max_age_days):
            return existing.gics_sector_id

    gics_id = get_gics_sector_id(quote_client, symbol, market)
    cache[symbol] = SectorTag(symbol=symbol, gics_sector_id=gics_id, looked_up_at=as_of)
    return gics_id
