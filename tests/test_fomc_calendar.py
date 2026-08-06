"""
Run with:
    pytest tests/test_fomc_calendar.py -v
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fomc_calendar import (
    FOMC_MEETINGS_2026, is_fomc_announcement_day, next_fomc_meeting, days_until_next_fomc, fomc_flag_text,
)


def test_is_fomc_announcement_day_true_on_second_day():
    assert is_fomc_announcement_day(date(2026, 9, 16)) is True


def test_is_fomc_announcement_day_false_on_first_day():
    assert is_fomc_announcement_day(date(2026, 9, 15)) is False


def test_is_fomc_announcement_day_false_on_unrelated_day():
    assert is_fomc_announcement_day(date(2026, 8, 6)) is False


def test_next_fomc_meeting_finds_upcoming():
    meeting = next_fomc_meeting(date(2026, 8, 6))
    assert meeting == (date(2026, 9, 15), date(2026, 9, 16))


def test_next_fomc_meeting_none_after_last_meeting():
    assert next_fomc_meeting(date(2026, 12, 10)) is None


def test_days_until_next_fomc():
    assert days_until_next_fomc(date(2026, 9, 13)) == 3


def test_fomc_flag_text_empty_when_far_away():
    assert fomc_flag_text(date(2026, 8, 6)) == ""


def test_fomc_flag_text_warns_within_window():
    text = fomc_flag_text(date(2026, 9, 14), warn_within_days=3)
    assert "FOMC meeting in 2 days" in text


def test_fomc_flag_text_announcement_day():
    text = fomc_flag_text(date(2026, 9, 16))
    assert "announced today" in text
