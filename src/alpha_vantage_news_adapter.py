"""
Fetches and parses Alpha Vantage's free NEWS_SENTIMENT endpoint --
financial news aggregated from many outlets, each article pre-scored for
sentiment per ticker by Alpha Vantage itself. No LLM/agent in this path
at all: a structured data fetch plus a relevance-weighted average, so
there's no prompt-injection surface in the automated daily scan (unlike
an unattended agent reading arbitrary open-web content). Free tier is 25
requests/day; one batched request covers the whole universe.

Including broad policy/economy topics (fiscal policy, monetary policy,
financial markets) means market-moving coverage of presidential
statements (tariffs, etc.) surfaces here too, as reported by whichever
outlets Alpha Vantage aggregates -- inherently multi-source, not reliant
on any single outlet.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from news_scanner import SymbolNewsSignal

API_BASE = "https://www.alphavantage.co/query"
DEFAULT_TOPICS = "economy_fiscal,economy_monetary,financial_markets"


def fetch_news_sentiment(
    symbols: List[str], api_key: str, topics: str = DEFAULT_TOPICS, limit: int = 200, timeout: float = 20.0
) -> dict:
    """The only function here that touches the network."""
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ",".join(symbols),
        "topics": topics,
        "limit": str(limit),
        "apikey": api_key,
    }
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "options-agent"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_news_sentiment(
    raw: dict, symbols: List[str], as_of: str, max_headlines_per_symbol: int = 3
) -> Dict[str, SymbolNewsSignal]:
    """
    Pure logic -- no network. raw is Alpha Vantage's NEWS_SENTIMENT JSON
    response (a "feed" list of articles, each with a "ticker_sentiment"
    list of per-ticker scores). Computes a relevance-weighted average
    sentiment per requested symbol, clamped to [-1, 1] to match
    SymbolNewsSignal's expected range regardless of Alpha Vantage's own
    scale. Symbols with no matching coverage are simply absent from the
    result (news_scanner.get_tilt already defaults missing symbols to
    neutral).
    """
    symbol_set = set(symbols)
    weighted_sums: Dict[str, float] = {s: 0.0 for s in symbol_set}
    weight_totals: Dict[str, float] = {s: 0.0 for s in symbol_set}
    headlines: Dict[str, List[str]] = {s: [] for s in symbol_set}

    for article in raw.get("feed", []) or []:
        title = article.get("title", "")
        for ts in article.get("ticker_sentiment", []) or []:
            symbol = ts.get("ticker")
            if symbol not in symbol_set:
                continue
            try:
                relevance = float(ts.get("relevance_score", 0.0))
                score = float(ts.get("ticker_sentiment_score", 0.0))
            except (TypeError, ValueError):
                continue
            if relevance <= 0:
                continue
            weighted_sums[symbol] += relevance * score
            weight_totals[symbol] += relevance
            if title and len(headlines[symbol]) < max_headlines_per_symbol:
                headlines[symbol].append(title)

    signals: Dict[str, SymbolNewsSignal] = {}
    for symbol in symbol_set:
        if weight_totals[symbol] <= 0:
            continue
        avg = weighted_sums[symbol] / weight_totals[symbol]
        tilt = max(-1.0, min(1.0, avg))
        signals[symbol] = SymbolNewsSignal(
            symbol=symbol, tilt=round(tilt, 4), as_of=as_of, headlines_considered=headlines[symbol],
        )
    return signals
