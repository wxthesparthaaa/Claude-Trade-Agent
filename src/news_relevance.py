"""
Deterministic keyword-based polarity tagging for company news, ported
from the sibling Forex Agent project's news_relevance.py -- same
reasoning: an unattended daily scan feeding a live-trading signal is a
real prompt-injection surface if it runs through an LLM/web-search
agent, so a fixed keyword list is used instead. No LLM in this path.

Finnhub's company-news endpoint is already scoped to one symbol per
request, so (unlike the Forex sibling's cross-currency keyword
matching) there's no relevance-tagging step here -- every article
returned for a symbol is already "about" that symbol. This module only
scores polarity.

Approximate by construction (a keyword scorer is not real sentiment
analysis) -- flagged honestly, not dressed up as more precise than it is.
"""
import re
from typing import List, Optional

POSITIVE_KEYWORDS = [
    "beats earnings", "earnings beat", "beats estimates", "tops estimates",
    "beats expectations", "beats forecast", "exceeds expectations",
    "raises guidance", "raised guidance", "guidance raised", "upgraded",
    "upgrades to buy", "price target raised", "record revenue",
    "record profit", "strong quarter", "better than expected", "surges",
    "rallies", "outperform", "share buyback", "raises dividend",
    "dividend increase",
]
NEGATIVE_KEYWORDS = [
    "misses earnings", "earnings miss", "misses estimates", "misses forecast",
    "cuts guidance", "guidance cut", "lowered guidance", "downgraded",
    "downgrades to sell", "price target cut", "price target lowered",
    "weak quarter", "worse than expected", "disappoints", "plunges",
    "tumbles", "underperform", "layoffs", "job cuts", "recall",
    "investigation", "lawsuit", "sec probe", "bankruptcy", "dividend cut",
    "suspends dividend",
]


# Headlines that warrant a pre-open heads-up on a HELD name, whatever the overall tilt (a CEO resignation or a fraud
# probe is rarely offset by a stray 'upgraded'). Alert-only: nothing is sold automatically.
SEVERE_KEYWORDS = [
    "bankruptcy", "fraud", "subpoena", "sec probe", "investigation", "delisting", "delisted", "restatement",
    "resigns", "resigned", "steps down", "stepping down", "fired", "recall", "halted", "trading halt",
    "plunges", "tumbles", "cuts guidance", "guidance cut", "lowered guidance", "misses earnings",
    "earnings miss", "downgraded", "lawsuit", "short seller", "export ban", "antitrust",
]


def _contains_keyword(text: str, keyword: str) -> bool:
    """Word-boundary match, not plain substring -- a naive `in` check
    would match "war" inside "award", the same false-positive class the
    Forex sibling module already found and fixed live."""
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None


def tag_headline(headline: str, summary: str = "") -> dict:
    """Returns {"polarity": float in [-1, 1]}."""
    text = f"{headline} {summary}".lower()
    positive_hits = sum(1 for k in POSITIVE_KEYWORDS if _contains_keyword(text, k))
    negative_hits = sum(1 for k in NEGATIVE_KEYWORDS if _contains_keyword(text, k))
    total_hits = positive_hits + negative_hits
    polarity = 0.0 if total_hits == 0 else (positive_hits - negative_hits) / total_hits
    return {"polarity": polarity}


def severe_headlines(articles: List[dict], since_ts: float = 0.0, limit: int = 3) -> List[dict]:
    """Articles (Finnhub company-news items) published at or after since_ts (unix seconds) whose headline or summary
    hits a SEVERE_KEYWORDS term and that are not net-positive overall; newest first. Approximate by construction, like
    the rest of this module -- a keyword match, not understanding."""
    hits = []
    for a in articles:
        if a.get("datetime", 0) < since_ts:
            continue
        text = f"{a.get('headline', '')} {a.get('summary', '')}".lower()
        if any(_contains_keyword(text, k) for k in SEVERE_KEYWORDS) and tag_headline(a.get("headline", ""), a.get("summary", ""))["polarity"] <= 0:
            hits.append(a)
    hits.sort(key=lambda a: a.get("datetime", 0), reverse=True)
    return hits[:limit]


def relevant_headlines(articles: List[dict], limit: int = 3) -> List[dict]:
    """articles: Finnhub company-news items ('headline'/'summary'/
    'datetime'). Tags each and returns the most recent ones, for the
    dashboard/Telegram rationale line."""
    tagged = [{**a, **tag_headline(a.get("headline", ""), a.get("summary", ""))} for a in articles]
    tagged.sort(key=lambda a: a.get("datetime", 0), reverse=True)
    return tagged[:limit]


def symbol_news_score(articles: List[dict], limit: int = 10) -> Optional[float]:
    """Average polarity across the most recent articles for one symbol.
    Returns None (neutral/unknown) if there's no coverage at all, rather
    than fabricating a 0.0 that would look like "checked, neutral"."""
    if not articles:
        return None
    relevant = relevant_headlines(articles, limit=limit)
    return sum(a["polarity"] for a in relevant) / len(relevant)
