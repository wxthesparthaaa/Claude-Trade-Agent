"""
Run with:
    pytest tests/test_news_relevance.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from news_relevance import tag_headline, relevant_headlines, symbol_news_score


def test_tag_headline_positive_keyword():
    tag = tag_headline("NVDA beats earnings, raises guidance for next quarter")
    assert tag["polarity"] > 0


def test_tag_headline_negative_keyword():
    tag = tag_headline("Company misses estimates and cuts guidance")
    assert tag["polarity"] < 0


def test_tag_headline_no_keyword_is_neutral():
    tag = tag_headline("Company holds annual shareholder meeting")
    assert tag["polarity"] == 0.0


def test_tag_headline_mixed_keywords_partially_cancel():
    tag = tag_headline("Beats estimates but issues profit warning and disappoints on margins")
    assert -1.0 < tag["polarity"] < 1.0


def test_tag_headline_uses_word_boundaries_not_substrings():
    # "war" must not match inside "warranty" / "reward"-style substrings
    tag = tag_headline("Company extends product warranty program")
    assert tag["polarity"] == 0.0


def test_tag_headline_checks_summary_too():
    tag = tag_headline("Quarterly update", summary="Company beats earnings estimates")
    assert tag["polarity"] > 0


def test_relevant_headlines_sorted_most_recent_first():
    articles = [
        {"headline": "Old news", "datetime": 100},
        {"headline": "New news", "datetime": 300},
        {"headline": "Mid news", "datetime": 200},
    ]
    result = relevant_headlines(articles, limit=2)
    assert [a["headline"] for a in result] == ["New news", "Mid news"]


def test_symbol_news_score_averages_polarity():
    articles = [
        {"headline": "Beats earnings", "datetime": 1},
        {"headline": "Misses estimates", "datetime": 2},
    ]
    score = symbol_news_score(articles)
    assert score == 0.0  # one positive, one negative -> cancels out


def test_symbol_news_score_returns_none_for_no_articles():
    assert symbol_news_score([]) is None
