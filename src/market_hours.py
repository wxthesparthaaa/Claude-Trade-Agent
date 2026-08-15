"""
Trading-hours status for the markets this project trades (US/HK/SG).
all_market_statuses/format_market_status stay purely informational (the
base.html footer) and are never consulted by scoring/scanning itself,
which still works off whatever price bars Tiger returns regardless of
session status. is_any_market_open is the one exception: an explicit,
opt-in gate app.py's manual "Scan Now" button uses to refuse to run
while every market a portfolio actually trades is closed -- see that
function's docstring. Deliberately no holiday calendar -- flagging that
limitation explicitly (every status line says "regular hours, holidays
not accounted for") rather than silently getting a market holiday wrong.

Regular hours only, standard sessions:
  US   (NYSE/NASDAQ): 9:30am-4:00pm America/New_York
  HK   (HKEX):         9:30am-12:00pm and 1:00pm-4:00pm Asia/Hong_Kong
  SG   (SGX):           9:00am-5:00pm Asia/Singapore
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Tuple
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")


@dataclass
class MarketDefinition:
    code: str
    label: str
    tz: ZoneInfo
    sessions: List[Tuple[time, time]]  # local (open, close) pairs, sorted ascending


MARKETS: List[MarketDefinition] = [
    MarketDefinition("US", "United States (NYSE / NASDAQ)", ZoneInfo("America/New_York"),
                      [(time(9, 30), time(16, 0))]),
    MarketDefinition("HK", "Hong Kong (HKEX)", ZoneInfo("Asia/Hong_Kong"),
                      [(time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))]),
    MarketDefinition("SG", "Singapore (SGX)", ZoneInfo("Asia/Singapore"),
                      [(time(9, 0), time(17, 0))]),
]


@dataclass
class MarketStatus:
    code: str
    label: str
    is_open: bool
    next_change_sgt: datetime   # when it next opens (if closed) or closes (if open), in SGT
    next_change_label: str       # "opens" | "closes"


def _next_session_start(market: MarketDefinition, local_now: datetime) -> datetime:
    """
    First session-open datetime (in the market's own tz) at or after
    local_now, skipping weekends. Looks up to 8 days ahead, which is
    always enough to clear a weekend regardless of what day local_now is.
    """
    for day_offset in range(8):
        candidate_date = (local_now + timedelta(days=day_offset)).date()
        if candidate_date.weekday() >= 5:  # Sat/Sun
            continue
        for open_t, _close_t in market.sessions:
            candidate_open = datetime.combine(candidate_date, open_t, tzinfo=market.tz)
            if candidate_open >= local_now:
                return candidate_open
    raise RuntimeError(f"could not find a next session for {market.code} within 8 days")  # pragma: no cover


def compute_market_status(market: MarketDefinition, now_utc: datetime) -> MarketStatus:
    """Pure logic -- now_utc must be timezone-aware (e.g. datetime.now(timezone.utc))."""
    local_now = now_utc.astimezone(market.tz)

    is_open = False
    session_end = None
    if local_now.weekday() < 5:
        for open_t, close_t in market.sessions:
            open_dt = local_now.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
            close_dt = local_now.replace(hour=close_t.hour, minute=close_t.minute, second=0, microsecond=0)
            if open_dt <= local_now < close_dt:
                is_open = True
                session_end = close_dt
                break

    if is_open:
        next_change, next_change_label = session_end, "closes"
    else:
        next_change, next_change_label = _next_session_start(market, local_now), "opens"

    return MarketStatus(
        code=market.code,
        label=market.label,
        is_open=is_open,
        next_change_sgt=next_change.astimezone(SGT),
        next_change_label=next_change_label,
    )


def all_market_statuses(now_utc: datetime) -> List[MarketStatus]:
    return [compute_market_status(m, now_utc) for m in MARKETS]


def is_any_market_open(market_codes, now_utc: datetime) -> bool:
    """True if at least one of market_codes (e.g. a profile's own
    universe -- {e.market for e in profile.universe}) is in its regular
    session right now. Unknown codes are ignored rather than raising, so
    this stays safe to call with whatever a universe happens to contain."""
    codes = set(market_codes)
    return any(
        compute_market_status(m, now_utc).is_open
        for m in MARKETS if m.code in codes
    )


def _format_countdown(delta_seconds: float) -> str:
    total_minutes = max(0, int(delta_seconds // 60))
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_market_status(status: MarketStatus, now_utc: datetime) -> str:
    now_sgt = now_utc.astimezone(SGT)
    countdown = _format_countdown((status.next_change_sgt - now_sgt).total_seconds())
    state = "OPEN" if status.is_open else "CLOSED"
    when = status.next_change_sgt.strftime("%a %I:%M%p").replace(" 0", " ")
    return f"{status.label}: {state} -- {status.next_change_label} in {countdown} ({when} SGT)"
