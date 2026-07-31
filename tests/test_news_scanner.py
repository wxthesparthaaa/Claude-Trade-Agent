"""
Run with:
    pytest tests/test_news_scanner.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from news_scanner import SymbolNewsSignal, write_news_signal, load_news_signal, get_tilt


def test_write_then_load_round_trips(tmp_path):
    path = str(tmp_path / "news_signal.json")
    signals = [
        SymbolNewsSignal(symbol="NVDA", tilt=0.4, as_of="2026-07-31", headlines_considered=["NVDA beats earnings"]),
        SymbolNewsSignal(symbol="AMD", tilt=-0.2, as_of="2026-07-31", headlines_considered=[]),
    ]
    write_news_signal(path, signals)
    loaded = load_news_signal(path)

    assert loaded["NVDA"].tilt == 0.4
    assert loaded["NVDA"].headlines_considered == ["NVDA beats earnings"]
    assert loaded["AMD"].tilt == -0.2


def test_get_tilt_returns_default_for_missing_symbol():
    signals = {"NVDA": SymbolNewsSignal(symbol="NVDA", tilt=0.4, as_of="2026-07-31", headlines_considered=[])}
    assert get_tilt(signals, "AMD") == 0.0
    assert get_tilt(signals, "AMD", default=0.1) == 0.1


def test_get_tilt_returns_actual_value_when_present():
    signals = {"NVDA": SymbolNewsSignal(symbol="NVDA", tilt=0.4, as_of="2026-07-31", headlines_considered=[])}
    assert get_tilt(signals, "NVDA") == 0.4
