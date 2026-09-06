"""
PE-ratio valuation for screener-sourced candidates (see
sector_suggestions.py) -- price from Tiger's own get_bars (works fine
under this account's permissions, see tiger_stock_bars_adapter.py),
trailing-annual diluted EPS from SEC EDGAR (see sec_edgar_adapter.py,
since this account's Tiger permissions don't cover US/HK real-time
quotes/fundamentals -- confirmed live via get_quote_permission()).

Classifies each candidate RELATIVE TO ITS OWN SUGGESTION BATCH's median
PE, not against a fixed "fair PE" number -- a batch is already a same-
sector/same-scan set of candidates (see app.py's
scheduled_sector_rotation_update), so a peer-relative comparison is
more meaningful than an arbitrary absolute threshold, and needs no
separately-maintained "fair value" table that would drift out of date.
A symbol with no PE data (HK/SG, or a company with no 10-K diluted-EPS
fact on file) gets "unknown", never a guessed verdict.
"""
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

from sec_edgar_adapter import fetch_ticker_cik_map, parse_ticker_cik_map, get_annual_eps
from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df

UNDERVALUED_THRESHOLD = 0.85   # PE at or below 85% of the batch's median
OVERVALUED_THRESHOLD = 1.25    # PE at or above 125% of the batch's median


@dataclass
class PEAssessment:
    symbol: str
    price: Optional[float]
    eps: Optional[float]
    pe_ratio: Optional[float]
    verdict: str  # "undervalued" | "fair" | "overvalued" | "unknown"


def compute_pe_ratio(price: Optional[float], eps: Optional[float]) -> Optional[float]:
    """None if price/EPS is missing, or EPS isn't positive -- a
    negative or zero trailing EPS makes a PE ratio meaningless, not
    merely a large number."""
    if price is None or eps is None or eps <= 0:
        return None
    return price / eps


def classify_batch(pe_by_symbol: Dict[str, Optional[float]]) -> Dict[str, str]:
    """Pure. Compares each symbol's PE to the MEDIAN of whichever
    symbols in this same batch actually have a PE (an "unknown" doesn't
    drag the median up or down). Fewer than 2 priced symbols can't
    support a relative comparison -- everything is "unknown" rather
    than an arbitrary call."""
    known = {s: pe for s, pe in pe_by_symbol.items() if pe is not None}
    if len(known) < 2:
        return {s: "unknown" for s in pe_by_symbol}

    median_pe = statistics.median(known.values())
    verdicts = {}
    for symbol, pe in pe_by_symbol.items():
        if pe is None:
            verdicts[symbol] = "unknown"
        elif pe <= median_pe * UNDERVALUED_THRESHOLD:
            verdicts[symbol] = "undervalued"
        elif pe >= median_pe * OVERVALUED_THRESHOLD:
            verdicts[symbol] = "overvalued"
        else:
            verdicts[symbol] = "fair"
    return verdicts


def fetch_pe_assessments(quote_client, symbols: List[str]) -> Dict[str, PEAssessment]:
    """Orchestrates one batch's PE lookup. US symbols only -- callers
    should filter out HK/SG before calling this, since SEC has no
    filings for them and every result would just come back "unknown"
    anyway. One bad symbol (price fetch failure, no SEC filing) never
    kills the batch -- it just gets price/eps/pe_ratio=None."""
    ticker_cik_map = parse_ticker_cik_map(fetch_ticker_cik_map())

    price_by_symbol, eps_by_symbol, pe_by_symbol = {}, {}, {}
    for symbol in symbols:
        try:
            bars = parse_stock_bars_df(fetch_stock_bars(quote_client, symbol, limit=5))
            price = bars[-1][1] if bars else None
        except Exception as e:
            print(f"PE valuation: price fetch failed for {symbol}: {type(e).__name__}: {e}")
            price = None
        eps = get_annual_eps(symbol, ticker_cik_map)
        price_by_symbol[symbol] = price
        eps_by_symbol[symbol] = eps
        pe_by_symbol[symbol] = compute_pe_ratio(price, eps)

    verdicts = classify_batch(pe_by_symbol)
    return {
        symbol: PEAssessment(
            symbol=symbol, price=price_by_symbol[symbol], eps=eps_by_symbol[symbol],
            pe_ratio=pe_by_symbol[symbol], verdict=verdicts[symbol],
        )
        for symbol in symbols
    }
