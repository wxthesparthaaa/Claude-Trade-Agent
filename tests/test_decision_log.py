"""
Run with:
    pytest tests/test_decision_log.py -v
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from decision_log import DecisionRecord, format_decision_summary, write_decision_log


def test_format_decision_summary_groups_by_action():
    records = [
        DecisionRecord("2026-07-31", "buy", "NVDA", "satellite", "top satellite pick", score=0.42),
        DecisionRecord("2026-07-31", "reject", "META", "satellite", "ranked below sleeve cap of 3", score=0.31),
        DecisionRecord("2026-07-31", "sell", "AMD", "satellite", "stop_loss: down 16.2% from entry"),
        DecisionRecord("2026-07-31", "hold", "SCHD", "core", "continues as top core pick", score=0.05),
    ]
    text = format_decision_summary("2026-07-31", records)
    assert "BUY:" in text
    assert "NVDA [satellite] (score=0.420): top satellite pick" in text
    assert "REJECT:" in text
    assert "SELL:" in text
    assert "stop_loss: down 16.2% from entry" in text
    assert "HOLD:" in text


def test_format_decision_summary_includes_shortlist_group():
    records = [
        DecisionRecord("2026-07-31", "shortlist", "FLAT", "satellite",
                        "confidence 55.0% -- below the 70% execute threshold, shortlisted for re-scoring", score=0.01),
    ]
    text = format_decision_summary("2026-07-31", records)
    assert "SHORTLIST:" in text
    assert "FLAT [satellite]" in text


def test_format_decision_summary_omits_empty_action_groups():
    records = [DecisionRecord("2026-07-31", "buy", "NVDA", "satellite", "top pick", score=0.42)]
    text = format_decision_summary("2026-07-31", records)
    assert "BUY:" in text
    assert "SELL:" not in text
    assert "REJECT:" not in text


def test_write_decision_log_creates_and_appends(tmp_path):
    path = str(tmp_path / "decisions.json")
    write_decision_log(path, "2026-07-31", [DecisionRecord("2026-07-31", "buy", "NVDA", "satellite", "top pick", score=0.42)])
    write_decision_log(path, "2026-08-01", [DecisionRecord("2026-08-01", "hold", "NVDA", "satellite", "still top pick", score=0.40)])

    with open(path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    assert len(entries) == 2
    assert entries[0]["date"] == "2026-07-31"
    assert entries[0]["decisions"][0]["symbol"] == "NVDA"
    assert entries[1]["decisions"][0]["action"] == "hold"
