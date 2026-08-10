"""
Run with:
    pytest tests/test_finnhub_adapter.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from finnhub_adapter import build_news_signal, fetch_news_for_universe
import finnhub_adapter as finnhub_adapter_module


def test_build_news_signal_computes_tilt_and_headlines():
    articles = [
        {"headline": "NVDA beats earnings", "summary": "", "datetime": 2},
        {"headline": "NVDA raises guidance", "summary": "", "datetime": 1},
    ]
    signal = build_news_signal("NVDA", articles, as_of="2026-08-10")
    assert signal is not None
    assert signal.symbol == "NVDA"
    assert signal.tilt > 0
    assert signal.as_of == "2026-08-10"
    assert "NVDA beats earnings" in signal.headlines_considered


def test_build_news_signal_returns_none_for_no_articles():
    assert build_news_signal("NVDA", [], as_of="2026-08-10") is None


def test_fetch_news_for_universe_builds_signal_per_symbol(monkeypatch):
    def fake_fetch(symbol, api_key, days_back=3, timeout=20.0):
        if symbol == "NVDA":
            return [{"headline": "NVDA beats earnings", "summary": "", "datetime": 1}]
        return []  # AMD has no coverage today
    monkeypatch.setattr(finnhub_adapter_module, "fetch_company_news", fake_fetch)

    signals = fetch_news_for_universe(["NVDA", "AMD"], api_key="fake-key", as_of="2026-08-10")

    assert "NVDA" in signals
    assert signals["NVDA"].tilt > 0
    assert "AMD" not in signals  # no coverage -> absent, not a fabricated neutral score


def test_fetch_news_for_universe_skips_symbol_on_fetch_error(monkeypatch):
    import urllib.error

    def fake_fetch(symbol, api_key, days_back=3, timeout=20.0):
        if symbol == "NVDA":
            raise urllib.error.URLError("boom")
        return [{"headline": "AMD beats earnings", "summary": "", "datetime": 1}]
    monkeypatch.setattr(finnhub_adapter_module, "fetch_company_news", fake_fetch)

    signals = fetch_news_for_universe(["NVDA", "AMD"], api_key="fake-key", as_of="2026-08-10")

    assert "NVDA" not in signals
    assert "AMD" in signals
