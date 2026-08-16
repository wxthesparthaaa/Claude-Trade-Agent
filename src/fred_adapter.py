"""
Free, unauthenticated FRED (Federal Reserve Economic Data) series fetcher
-- same "free public API, no auth" posture as cot_adapter.py, just a
different source. Uses FRED's plain CSV export endpoint rather than the
key-gated JSON API, so no signup/API key is needed at all.

Live-verified format (fetched T10YIE directly from this endpoint):
header row "observation_date,{SERIES_ID}", then "YYYY-MM-DD,value" rows
oldest-first, with not-yet-published/missing observations as an EMPTY
value (not "."), e.g. "2003-01-20,". parse_fred_csv below treats any row
whose value doesn't parse as a float as missing and skips it, rather
than raising -- this also tolerates a "." placeholder if FRED ever uses
one for a different series, without special-casing it.

A browser-like User-Agent is required: this endpoint intermittently
resets the connection or times out when called with Python's default
urllib User-Agent string.
"""
import csv
import io
import urllib.request
from datetime import date, datetime
from typing import List, Tuple

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_fred_series(series_id: str, timeout: float = 20.0) -> str:
    """The only function here that touches the network. Returns the raw
    CSV text."""
    url = f"{FRED_CSV_URL}?id={series_id}"
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def parse_fred_csv(csv_text: str) -> List[Tuple[date, float]]:
    """Pure -- no network. Returns chronologically sorted (date, value)
    tuples, skipping any row with a missing/unparseable value."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return []

    series = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        raw_date, raw_value = row[0], row[1]
        try:
            value = float(raw_value)
        except (ValueError, TypeError):
            continue
        try:
            d = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        series.append((d, value))

    series.sort(key=lambda t: t[0])
    return series


def fetch_and_parse_series(series_id: str, timeout: float = 20.0) -> List[Tuple[date, float]]:
    """Convenience wrapper: fetch + parse for one series."""
    return parse_fred_csv(fetch_fred_series(series_id, timeout=timeout))
