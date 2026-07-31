"""
Daily news-tilt signal, consumed by stock_signal.composite_score.

The actual web research -- searching for headlines on each watchlist/
portfolio symbol and judging whether they're bullish/bearish -- is done by
Claude in an agent turn using the WebSearch tool, NOT by this module: a
web search is an agent capability, not something a standalone Python script
can invoke on its own. This module only defines the data shape and handles
persisting/loading the result of that research, so the rest of the system
(and the scheduled daily job, once set up) has something concrete to read.
"""
import json
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class SymbolNewsSignal:
    symbol: str
    tilt: float                        # in [-1, 1], synthesized by Claude from that day's headlines
    as_of: str                          # "YYYY-MM-DD"
    headlines_considered: List[str]


def write_news_signal(path: str, signals: List[SymbolNewsSignal]):
    data = {
        s.symbol: {"tilt": s.tilt, "as_of": s.as_of, "headlines_considered": s.headlines_considered}
        for s in signals
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_news_signal(path: str) -> Dict[str, SymbolNewsSignal]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        symbol: SymbolNewsSignal(
            symbol=symbol,
            tilt=v["tilt"],
            as_of=v["as_of"],
            headlines_considered=v.get("headlines_considered", []),
        )
        for symbol, v in data.items()
    }


def get_tilt(signals: Dict[str, SymbolNewsSignal], symbol: str, default: float = 0.0) -> float:
    """Missing symbols default to 0.0 (neutral) rather than raising -- most
    symbols on most days won't have notable news, and that's not an error."""
    return signals[symbol].tilt if symbol in signals else default
