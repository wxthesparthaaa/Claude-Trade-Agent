"""
Run with:
    pytest tests/test_market_hours.py -v

Reference dates used throughout: 2026-08-10 is a Monday, 2026-08-11 a
Tuesday, 2026-08-14 a Friday, 2026-08-15 a Saturday, 2026-08-17 the
following Monday -- verified directly rather than assumed.
"""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_hours import (
    MARKETS, compute_market_status, all_market_statuses, format_market_status,
    is_any_market_open, any_market_trades_today,
)

US = next(m for m in MARKETS if m.code == "US")
HK = next(m for m in MARKETS if m.code == "HK")
SG = next(m for m in MARKETS if m.code == "SG")


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# ---- US (America/New_York, EDT = UTC-4 in August) --------------------------

def test_us_open_during_session():
    # Mon 2026-08-10, 11:00 ET = 15:00 UTC
    status = compute_market_status(US, utc(2026, 8, 10, 15, 0))
    assert status.is_open is True
    assert status.next_change_label == "closes"


def test_us_closed_before_open_same_day():
    # Mon 2026-08-10, 08:00 ET = 12:00 UTC -- opens same day at 9:30 ET
    status = compute_market_status(US, utc(2026, 8, 10, 12, 0))
    assert status.is_open is False
    assert status.next_change_label == "opens"
    assert status.next_change_sgt.astimezone(US.tz).time().isoformat() == "09:30:00"
    assert status.next_change_sgt.astimezone(US.tz).date().isoformat() == "2026-08-10"


def test_us_closed_after_close_rolls_to_next_weekday():
    # Mon 2026-08-10, 17:00 ET = 21:00 UTC -- opens Tue 2026-08-11
    status = compute_market_status(US, utc(2026, 8, 10, 21, 0))
    assert status.is_open is False
    assert status.next_change_sgt.astimezone(US.tz).date().isoformat() == "2026-08-11"


def test_us_friday_close_rolls_over_weekend_to_monday():
    # Fri 2026-08-14, 17:00 ET = 21:00 UTC -- opens Mon 2026-08-17, not Sat/Sun
    status = compute_market_status(US, utc(2026, 8, 14, 21, 0))
    assert status.is_open is False
    next_local = status.next_change_sgt.astimezone(US.tz)
    assert next_local.date().isoformat() == "2026-08-17"
    assert next_local.strftime("%A") == "Monday"


def test_us_closed_all_weekend():
    # Sat 2026-08-15, noon ET = 16:00 UTC -- opens Mon 2026-08-17
    status = compute_market_status(US, utc(2026, 8, 15, 16, 0))
    assert status.is_open is False
    assert status.next_change_sgt.astimezone(US.tz).date().isoformat() == "2026-08-17"


# ---- HK (Asia/Hong_Kong, UTC+8, no DST) -------------------------------------

def test_hk_open_morning_session():
    # Mon 2026-08-10, 10:00 HKT = 02:00 UTC
    status = compute_market_status(HK, utc(2026, 8, 10, 2, 0))
    assert status.is_open is True


def test_hk_closed_during_lunch_break():
    # Mon 2026-08-10, 12:30 HKT = 04:30 UTC -- opens 13:00 HKT same day
    status = compute_market_status(HK, utc(2026, 8, 10, 4, 30))
    assert status.is_open is False
    next_local = status.next_change_sgt.astimezone(HK.tz)
    assert next_local.time().isoformat() == "13:00:00"
    assert next_local.date().isoformat() == "2026-08-10"


def test_hk_open_afternoon_session():
    # Mon 2026-08-10, 14:00 HKT = 06:00 UTC
    status = compute_market_status(HK, utc(2026, 8, 10, 6, 0))
    assert status.is_open is True


def test_hk_closed_after_close_rolls_to_next_day():
    # Mon 2026-08-10, 17:00 HKT = 09:00 UTC -- opens Tue 09:30 HKT
    status = compute_market_status(HK, utc(2026, 8, 10, 9, 0))
    assert status.is_open is False
    next_local = status.next_change_sgt.astimezone(HK.tz)
    assert next_local.date().isoformat() == "2026-08-11"
    assert next_local.time().isoformat() == "09:30:00"


# ---- SG (Asia/Singapore, UTC+8, no DST) -------------------------------------

def test_sg_open_during_session():
    # Mon 2026-08-10, 10:00 SGT = 02:00 UTC
    status = compute_market_status(SG, utc(2026, 8, 10, 2, 0))
    assert status.is_open is True
    assert status.next_change_label == "closes"


def test_sg_closed_before_open():
    # Mon 2026-08-10, 08:00 SGT = 00:00 UTC -- opens 09:00 same day
    status = compute_market_status(SG, utc(2026, 8, 10, 0, 0))
    assert status.is_open is False
    next_local = status.next_change_sgt.astimezone(SG.tz)
    assert next_local.time().isoformat() == "09:00:00"


# ---- shared helpers ----------------------------------------------------------

def test_all_market_statuses_returns_one_per_market():
    statuses = all_market_statuses(utc(2026, 8, 10, 15, 0))
    assert {s.code for s in statuses} == {"US", "HK", "SG"}


def test_format_market_status_open():
    status = compute_market_status(US, utc(2026, 8, 10, 15, 0))
    text = format_market_status(status, utc(2026, 8, 10, 15, 0))
    assert "United States" in text
    assert "OPEN" in text
    assert "closes in" in text


def test_format_market_status_closed():
    status = compute_market_status(HK, utc(2026, 8, 10, 4, 30))
    text = format_market_status(status, utc(2026, 8, 10, 4, 30))
    assert "Hong Kong" in text
    assert "CLOSED" in text
    assert "opens in" in text


# ---- is_any_market_open -------------------------------------------------------

def test_is_any_market_open_true_when_one_of_several_codes_is_open():
    # Mon 2026-08-10, 11:00 ET = 15:00 UTC -- US open, HK/SG both closed by then
    assert is_any_market_open({"US", "HK", "SG"}, utc(2026, 8, 10, 15, 0)) is True


def test_is_any_market_open_false_when_all_given_codes_are_closed():
    # Sat 2026-08-15, noon ET = 16:00 UTC -- every market closed for the weekend
    assert is_any_market_open({"US", "HK", "SG"}, utc(2026, 8, 15, 16, 0)) is False


def test_is_any_market_open_only_considers_the_given_codes():
    # US is open at this instant, but a dividend-only universe of just SG/HK
    # symbols must not be reported open because of a market it doesn't trade.
    assert is_any_market_open({"SG"}, utc(2026, 8, 10, 15, 0)) is False


def test_is_any_market_open_ignores_unknown_codes():
    assert is_any_market_open({"XX"}, utc(2026, 8, 10, 15, 0)) is False


# ---- any_market_trades_today ---------------------------------------------------

def test_any_market_trades_today_true_on_a_weekday_between_sessions():
    # Mon 2026-08-10, 18:00 SGT = 10:00 UTC -- SG/HK already closed for the
    # day, US not open yet, but it's still a real Monday trading day.
    assert any_market_trades_today({"US", "HK", "SG"}, utc(2026, 8, 10, 10, 0)) is True


def test_any_market_trades_today_false_on_saturday_for_every_relevant_market():
    # Sat 2026-08-15, 21:15 SGT = 13:15 UTC -- the real bug this guards
    # against: an external scheduler fired a report at this exact moment.
    assert any_market_trades_today({"US", "HK", "SG"}, utc(2026, 8, 15, 13, 15)) is False


def test_any_market_trades_today_only_considers_the_given_codes():
    assert any_market_trades_today({"XX"}, utc(2026, 8, 10, 10, 0)) is False
