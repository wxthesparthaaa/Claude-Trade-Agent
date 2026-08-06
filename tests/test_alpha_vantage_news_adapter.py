"""
Run with:
    pytest tests/test_alpha_vantage_news_adapter.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from alpha_vantage_news_adapter import parse_news_sentiment


def make_article(title, ticker_sentiments):
    return {
        "title": title,
        "ticker_sentiment": [
            {"ticker": t, "relevance_score": str(rel), "ticker_sentiment_score": str(score)}
            for t, rel, score in ticker_sentiments
        ],
    }


def test_parse_news_sentiment_computes_relevance_weighted_average():
    raw = {"feed": [
        make_article("NVDA rallies on strong earnings", [("NVDA", 0.9, 0.3)]),
        make_article("Tech sector broadly higher", [("NVDA", 0.3, 0.1)]),
    ]}
    signals = parse_news_sentiment(raw, symbols=["NVDA"], as_of="2026-08-06")
    expected = (0.9 * 0.3 + 0.3 * 0.1) / (0.9 + 0.3)
    assert signals["NVDA"].tilt == pytest.approx(round(expected, 4))


def test_parse_news_sentiment_ignores_zero_relevance():
    raw = {"feed": [make_article("Unrelated market news", [("NVDA", 0.0, 0.9)])]}
    signals = parse_news_sentiment(raw, symbols=["NVDA"], as_of="2026-08-06")
    assert "NVDA" not in signals  # no relevant coverage -> absent, not a fabricated score


def test_parse_news_sentiment_absent_symbol_not_in_result():
    raw = {"feed": [make_article("NVDA news", [("NVDA", 0.9, 0.2)])]}
    signals = parse_news_sentiment(raw, symbols=["NVDA", "AMD"], as_of="2026-08-06")
    assert "AMD" not in signals
    assert "NVDA" in signals


def test_parse_news_sentiment_clamps_to_valid_range():
    raw = {"feed": [make_article("Extreme headline", [("NVDA", 1.0, 5.0)])]}
    signals = parse_news_sentiment(raw, symbols=["NVDA"], as_of="2026-08-06")
    assert signals["NVDA"].tilt == 1.0  # clamped, not 5.0


def test_parse_news_sentiment_collects_headlines_up_to_limit():
    raw = {"feed": [
        make_article(f"Headline {i}", [("NVDA", 0.5, 0.1)]) for i in range(5)
    ]}
    signals = parse_news_sentiment(raw, symbols=["NVDA"], as_of="2026-08-06", max_headlines_per_symbol=2)
    assert len(signals["NVDA"].headlines_considered) == 2


def test_parse_news_sentiment_skips_malformed_ticker_sentiment_entries():
    raw = {"feed": [{
        "title": "Weird data",
        "ticker_sentiment": [{"ticker": "NVDA", "relevance_score": "not-a-number", "ticker_sentiment_score": "0.2"}],
    }]}
    signals = parse_news_sentiment(raw, symbols=["NVDA"], as_of="2026-08-06")
    assert "NVDA" not in signals


def test_parse_news_sentiment_empty_feed():
    assert parse_news_sentiment({"feed": []}, symbols=["NVDA"], as_of="2026-08-06") == {}


def test_parse_news_sentiment_missing_feed_key():
    assert parse_news_sentiment({}, symbols=["NVDA"], as_of="2026-08-06") == {}
