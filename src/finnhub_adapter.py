"""
Finnhub free tier (60 calls/min) as the primary automated news source --
chosen over Alpha Vantage as primary because Alpha Vantage's free tier
(25 requests/day) is too tight for a source that's hit on every
scheduled scan plus every manual "Refresh News" click. Alpha Vantage
stays available (alpha_vantage_news_adapter.py) as a manual fallback if
FINNHUB_API_KEY isn't set or its quota is ever exhausted.

Company-news is fetched one symbol at a time (Finnhub's free endpoint
doesn't batch across tickers the way Alpha Vantage's NEWS_SENTIMENT
does), so at 60 calls/min this comfortably covers this project's
universe size in one scheduled run.

Deliberately thin: this module only fetches and returns raw structured
data plus the glue to shape it into SymbolNewsSignal. Polarity tagging
lives in news_relevance.py as pure, testable functions kept separate
from any network call -- same split the sibling Forex Agent project uses.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Dict, List, Optional

from news_scanner import SymbolNewsSignal
from news_relevance import symbol_news_score, relevant_headlines

API_BASE = "https://finnhub.io/api/v1"


def fetch_company_news(symbol: str, api_key: str, days_back: int = 3, timeout: float = 20.0) -> List[dict]:
    """The only function here that touches the network. days_back=3 --
    a short trailing window since this feeds a daily tilt, not a backtest."""
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)
    params = {
        "symbol": symbol,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "token": api_key,
    }
    url = API_BASE + "/company-news?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "options-agent"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def build_news_signal(symbol: str, articles: List[dict], as_of: str, max_headlines: int = 3) -> Optional[SymbolNewsSignal]:
    """Pure logic -- no network. Returns None if there's no usable
    coverage for this symbol (news_scanner.get_tilt already defaults
    missing symbols to neutral, so an absent signal is not an error)."""
    score = symbol_news_score(articles)
    if score is None:
        return None
    headlines = [a["headline"] for a in relevant_headlines(articles, limit=max_headlines) if a.get("headline")]
    return SymbolNewsSignal(symbol=symbol, tilt=round(score, 4), as_of=as_of, headlines_considered=headlines)


def fetch_news_for_universe(symbols: List[str], api_key: str, as_of: str) -> Dict[str, SymbolNewsSignal]:
    """Loops fetch_company_news + build_news_signal across a whole
    universe -- the shape app.py's scheduled job needs. A single
    symbol's fetch failure doesn't abort the rest of the universe."""
    signals: Dict[str, SymbolNewsSignal] = {}
    for symbol in symbols:
        try:
            articles = fetch_company_news(symbol, api_key)
        except (urllib.error.URLError, TimeoutError):
            continue
        signal = build_news_signal(symbol, articles, as_of)
        if signal is not None:
            signals[symbol] = signal
    return signals
