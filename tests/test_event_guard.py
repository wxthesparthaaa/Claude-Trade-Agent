"""
Run with:
    pytest tests/test_event_guard.py -v
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import event_guard
from event_guard import EightK, parse_recent_8ks, blocked_symbols, scan_universe, save_event_flags, load_event_flags


def submissions(rows):
    """rows: (form, filingDate, items, accession) -> EDGAR's parallel-array 'recent' block."""
    return {"filings": {"recent": {
        "form": [r[0] for r in rows], "filingDate": [r[1] for r in rows],
        "items": [r[2] for r in rows], "accessionNumber": [r[3] for r in rows],
    }}}


def test_parse_keeps_only_watched_items_since_the_cutoff():
    raw = submissions([
        ("8-K", "2026-11-24", "4.02,9.01", "A1"),     # non-reliance: blocking
        ("8-K", "2026-11-23", "2.02,9.01", "A2"),     # earnings release: not watched
        ("10-Q", "2026-11-22", "", "A3"),             # not an 8-K
        ("8-K", "2026-11-10", "1.03", "A4"),          # too old for the window
        ("8-K/A", "2026-11-25", "5.02", "A5"),        # officer change: informational, amendments count
    ])
    found = parse_recent_8ks(raw, since=date(2026, 11, 18))
    assert [f.accession for f in found] == ["A5", "A1"]            # newest first
    assert found[1].items == ["4.02", "9.01"]


def test_parse_tolerates_empty_or_malformed_payloads():
    assert parse_recent_8ks(None, date(2026, 1, 1)) == []
    assert parse_recent_8ks({}, date(2026, 1, 1)) == []
    assert parse_recent_8ks({"filings": {"recent": {"form": ["8-K"], "filingDate": ["not-a-date"]}}}, date(2026, 1, 1)) == []


def test_blocked_symbols_only_blocking_items_inside_the_window():
    flags = {
        "BAD": [EightK("2026-11-24", ["4.02"], "x1")],
        "CEO": [EightK("2026-11-24", ["5.02"], "x2")],            # informational: never blocks
        "OLD": [EightK("2026-11-10", ["1.03"], "x3")],            # outside the 5-day window
        "MIX": [EightK("2026-11-25", ["3.01", "9.01"], "x4")],
    }
    blocked = blocked_symbols(flags, today=date(2026, 11, 26))
    assert set(blocked) == {"BAD", "MIX"}
    assert "Item 4.02" in blocked["BAD"] and "no new entry for 5 days" in blocked["BAD"]
    assert "Item 3.01" in blocked["MIX"]


def test_scan_universe_skips_unknown_symbols_and_survives_a_failed_lookup():
    cik_map = {"AAA": "0000000001", "BBB": "0000000002", "CCC": "0000000003"}

    def fake_fetch(cik):
        if cik == "0000000002":
            raise RuntimeError("SEC hiccup")
        return submissions([("8-K", "2026-11-25", "1.03", "ACC-" + cik)])

    out = scan_universe(["AAA", "BBB", "CCC", "QQQ"], date(2026, 11, 26), ticker_cik_map=cik_map, fetch=fake_fetch, pause=0)
    assert set(out) == {"AAA", "CCC"}      # BBB failed, QQQ has no CIK (an ETF)
    assert out["AAA"][0].items == ["1.03"]


def test_flags_roundtrip(tmp_path):
    path = str(tmp_path / "event_flags.json")
    flags = {"AAA": [EightK("2026-11-25", ["4.02", "9.01"], "ACC1")]}
    save_event_flags(path, flags, "2026-11-26")
    assert load_event_flags(path) == flags


def test_describe_items_names_only_known_items():
    text = event_guard.describe_items(["4.02", "9.01"])
    assert text == "Item 4.02 (non-reliance on prior financial statements)"
