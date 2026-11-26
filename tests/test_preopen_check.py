"""
Run with:
    pytest tests/test_preopen_check.py -v
"""
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import preopen_check
from event_guard import EightK
from preopen_check import previous_close, build_held_alerts, run_preopen_check, NEW_YORK
from telegram_notifier import format_preopen_alert


def test_previous_close_skips_the_weekend():
    assert previous_close(date(2026, 11, 23)).date() == date(2026, 11, 20)     # Monday -> Friday
    assert previous_close(date(2026, 11, 26)).date() == date(2026, 11, 25)     # Thursday -> Wednesday
    assert previous_close(date(2026, 11, 26)).hour == 16


def ts(year, month, day, hour):
    return datetime(year, month, day, hour, 0, tzinfo=NEW_YORK).timestamp()


def test_held_alert_combines_a_fresh_filing_and_a_severe_headline():
    since = previous_close(date(2026, 11, 26))
    events = {"NVDA": [EightK("2026-11-25", ["5.02"], "ACC1")], "AMD": [EightK("2026-11-10", ["4.02"], "OLD")]}
    headlines = {"NVDA": [
        {"headline": "Nvidia CEO resigns, board names interim chief", "datetime": ts(2026, 11, 26, 7)},
        {"headline": "Nvidia CEO resigns (yesterday's story)", "datetime": ts(2026, 11, 24, 9)},       # before the cut-off
        {"headline": "Nvidia unveils a new chip", "datetime": ts(2026, 11, 26, 8)},                    # not severe
    ]}
    alerts = build_held_alerts(["NVDA", "AMD"], events, headlines, since, already_reported=set())
    assert [a.symbol for a in alerts] == ["NVDA"]                  # AMD's filing is stale
    reasons = alerts[0].reasons
    assert any("Item 5.02" in r for r in reasons)
    assert sum(r.startswith("Headline:") for r in reasons) == 1 and "interim chief" in reasons[-1]
    assert alerts[0].accessions == ["ACC1"]


def test_an_already_reported_filing_is_not_repeated():
    since = previous_close(date(2026, 11, 26))
    events = {"NVDA": [EightK("2026-11-25", ["4.02"], "ACC1")]}
    assert build_held_alerts(["NVDA"], events, {}, since, already_reported={"ACC1"}) == []


def run(tmp_path, held, universe, cik_map, events, headlines=None, key="k", sent=None):
    flags_path = str(tmp_path / "event_flags.json")
    sent = [] if sent is None else sent

    def scan(symbols, today, ticker_cik_map=None):
        return {s: events[s] for s in symbols if s in events}

    result = run_preopen_check(
        today=date(2026, 11, 26), flags_path=flags_path, universe_symbols=universe, held_symbols=held,
        finnhub_key=key, send=lambda text: sent.append(text) or True,
        format_message=lambda alerts, blocks: format_preopen_alert(alerts, blocks, "Growth Portfolio"),
        fetch_cik_map=lambda: cik_map, scan_events=scan,
        fetch_news=lambda symbol, k: (headlines or {}).get(symbol, []),
    )
    return result, flags_path, sent


def test_a_clean_check_is_silent_and_still_writes_the_flags(tmp_path):
    result, flags_path, sent = run(tmp_path, ["NVDA"], ["NVDA", "AMD"], {"NVDA": "1"}, events={})
    assert sent == [] and not result.sent
    assert json.load(open(flags_path))["events"] == {}


def test_held_alert_and_new_block_are_sent_once_then_not_repeated(tmp_path):
    events = {"NVDA": [EightK("2026-11-25", ["5.02"], "N1")], "BAD": [EightK("2026-11-25", ["1.03"], "B1")]}
    result, flags_path, sent = run(tmp_path, ["NVDA"], ["NVDA", "BAD"], {"NVDA": "1", "BAD": "2"}, events)
    assert result.sent and len(sent) == 1
    text = sent[0]
    assert "[Growth Portfolio] Pre-open heads-up" in text
    assert "NVDA -- you hold this" in text and "Item 5.02" in text
    assert "No new buys in these names today" in text and "BAD:" in text and "Item 1.03" in text
    assert "Nothing is sold automatically" in text
    data = json.load(open(flags_path))
    assert set(data["reported"]) == {"N1", "B1"} and set(data["events"]) == {"NVDA", "BAD"}

    # the next morning: same filings, already announced -> silent, but the block still stands in the file
    result2, _, sent2 = run(tmp_path, ["NVDA"], ["NVDA", "BAD"], {"NVDA": "1", "BAD": "2"}, events, sent=[])
    assert sent2 == [] and not result2.sent


def test_without_the_sec_directory_the_previous_flags_are_kept(tmp_path):
    flags_path = str(tmp_path / "event_flags.json")
    with open(flags_path, "w") as f:
        json.dump({"as_of": "2026-11-25", "events": {"BAD": [{"filed": "2026-11-25", "items": ["1.03"], "accession": "B1"}]},
                   "reported": ["B1"]}, f)
    result, _, sent = run(tmp_path, [], ["BAD"], {}, events={})
    assert "BAD" in json.load(open(flags_path))["events"]           # not wiped by the outage
    assert any("SEC ticker directory unavailable" in n for n in result.notes)


def test_without_a_finnhub_key_only_filings_are_checked(tmp_path):
    result, _, sent = run(tmp_path, ["NVDA"], ["NVDA"], {"NVDA": "1"}, events={}, key=None,
                          headlines={"NVDA": [{"headline": "CEO resigns", "datetime": ts(2026, 11, 26, 7)}]})
    assert sent == []
    assert any("FINNHUB_API_KEY not set" in n for n in result.notes)


def test_a_failing_news_fetch_skips_just_that_symbol(tmp_path):
    flags_path = str(tmp_path / "event_flags.json")
    sent = []

    def boom(symbol, key):
        if symbol == "AMD":
            raise RuntimeError("429")
        return [{"headline": "Fraud probe opened", "datetime": ts(2026, 11, 26, 7)}]

    result = run_preopen_check(
        today=date(2026, 11, 26), flags_path=flags_path, universe_symbols=["NVDA", "AMD"], held_symbols=["NVDA", "AMD"],
        finnhub_key="k", send=lambda t: sent.append(t) or True,
        format_message=lambda a, b: format_preopen_alert(a, b), fetch_cik_map=lambda: {"NVDA": "1"},
        scan_events=lambda symbols, today, ticker_cik_map=None: {}, fetch_news=boom)
    assert [a.symbol for a in result.held_alerts] == ["NVDA"]
    assert any("AMD" in n for n in result.notes)
