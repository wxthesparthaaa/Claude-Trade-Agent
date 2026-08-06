"""
Static FOMC meeting calendar -- known, scheduled months in advance, so
flagging an upcoming meeting in the daily digest needs no news search at
all for this specific piece (unlike headline sentiment, which genuinely
needs a live fetch).
"""
from datetime import date
from typing import List, Optional, Tuple

# (meeting_start, meeting_end) -- the announcement/rate decision comes on
# meeting_end, typically the more market-moving of the two days.
FOMC_MEETINGS_2026: List[Tuple[date, date]] = [
    (date(2026, 1, 27), date(2026, 1, 28)),
    (date(2026, 3, 17), date(2026, 3, 18)),
    (date(2026, 4, 28), date(2026, 4, 29)),
    (date(2026, 6, 16), date(2026, 6, 17)),
    (date(2026, 7, 28), date(2026, 7, 29)),
    (date(2026, 9, 15), date(2026, 9, 16)),
    (date(2026, 10, 27), date(2026, 10, 28)),
    (date(2026, 12, 8), date(2026, 12, 9)),
]


def is_fomc_announcement_day(check_date: date, meetings: List[Tuple[date, date]] = FOMC_MEETINGS_2026) -> bool:
    return any(check_date == end for _, end in meetings)


def next_fomc_meeting(
    as_of: date, meetings: List[Tuple[date, date]] = FOMC_MEETINGS_2026
) -> Optional[Tuple[date, date]]:
    upcoming = [m for m in meetings if m[1] >= as_of]
    return min(upcoming, key=lambda m: m[0]) if upcoming else None


def days_until_next_fomc(as_of: date, meetings: List[Tuple[date, date]] = FOMC_MEETINGS_2026) -> Optional[int]:
    meeting = next_fomc_meeting(as_of, meetings)
    return (meeting[1] - as_of).days if meeting else None


def fomc_flag_text(as_of: date, warn_within_days: int = 3, meetings: List[Tuple[date, date]] = FOMC_MEETINGS_2026) -> str:
    """
    Returns a short flag string for the daily digest, or "" if no FOMC
    meeting is imminent -- callers should treat "" as "nothing to add".
    """
    if is_fomc_announcement_day(as_of, meetings):
        return "FOMC rate decision announced today."
    days = days_until_next_fomc(as_of, meetings)
    if days is not None and 0 <= days <= warn_within_days:
        return f"FOMC meeting in {days} day{'s' if days != 1 else ''} -- expect volatility around the announcement."
    return ""
