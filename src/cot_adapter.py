"""
Fetches and parses CFTC Commitment of Traders (COT) reports from the
free, public Socrata Open Data API -- weekly futures positioning data,
published Fridays 3:30pm ET. Individual stocks/ETFs don't have their own
futures contracts in COT, so this feeds the macro regime layer (broad
market crowding/positioning -- is the trade getting crowded, or is there
room to run), not per-symbol scoring.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

API_BASE = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"  # Legacy Futures-Only report

DEFAULT_CONTRACTS = {
    "sp500": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    "nasdaq100": "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
}


@dataclass
class CotWeek:
    report_date: str
    open_interest: float
    noncomm_long: float
    noncomm_short: float


@dataclass
class PositioningMetric:
    contract: str
    as_of: str
    net_position_pct_oi: float   # (long - short) / open_interest, current week
    z_score: float                 # current net_position_pct_oi vs its own trailing history
    weeks_of_history: int


def fetch_cot_report(contract_name: str, weeks: int = 52, timeout: float = 15.0) -> List[dict]:
    """The only function here that touches the network."""
    params = {
        "$limit": str(weeks),
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$where": f"market_and_exchange_names = '{contract_name}'",
    }
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "options-agent"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_cot_positioning(raw_rows: List[dict], contract_label: str) -> Optional[PositioningMetric]:
    """
    Pure logic -- no network. raw_rows is Socrata JSON rows (as
    fetch_cot_report returns), most-recent-first. Computes the current
    week's net non-commercial position as a fraction of open interest, and
    a z-score of that figure against the trailing window provided --
    extreme z (either direction) is what "crowded" or "room to run" means
    here, not the raw level.
    """
    weeks = []
    for row in raw_rows or []:
        try:
            oi = float(row["open_interest_all"])
            long_ = float(row["noncomm_positions_long_all"])
            short = float(row["noncomm_positions_short_all"])
        except (KeyError, ValueError, TypeError):
            continue
        if oi <= 0:
            continue
        weeks.append(CotWeek(row["report_date_as_yyyy_mm_dd"], oi, long_, short))

    if not weeks:
        return None

    net_pcts = [(w.noncomm_long - w.noncomm_short) / w.open_interest for w in weeks]
    current = net_pcts[0]

    if len(net_pcts) < 2:
        z = 0.0
    else:
        mean = sum(net_pcts) / len(net_pcts)
        variance = sum((x - mean) ** 2 for x in net_pcts) / max(1, len(net_pcts) - 1)
        std = variance ** 0.5
        z = (current - mean) / std if std > 0 else 0.0

    return PositioningMetric(
        contract=contract_label,
        as_of=weeks[0].report_date,
        net_position_pct_oi=round(current, 4),
        z_score=round(z, 3),
        weeks_of_history=len(weeks),
    )


def fetch_positioning_signals(contracts: Optional[Dict[str, str]] = None, weeks: int = 52) -> Dict[str, PositioningMetric]:
    """Convenience wrapper: fetch + parse for each label -> contract_name pair.
    Skips (rather than raises on) any single contract's fetch failure, so
    one bad symbol doesn't take down the whole weekly refresh."""
    contracts = contracts or DEFAULT_CONTRACTS
    results = {}
    for label, contract_name in contracts.items():
        try:
            raw = fetch_cot_report(contract_name, weeks=weeks)
            metric = parse_cot_positioning(raw, label)
            if metric is not None:
                results[label] = metric
        except Exception as e:
            print(f"COT fetch failed for {label} ({contract_name}): {type(e).__name__}: {e}")
    return results


def positioning_to_tilt(
    metrics: Dict[str, PositioningMetric], extreme_z: float = 2.0, tilt_magnitude: float = 0.1
) -> float:
    """
    Translates positioning z-scores into a single tilt multiplier centered
    on 1.0 (e.g. 0.9-1.1): crowded-long positioning (high positive z --
    "room to run" more exhausted, more forced-seller risk on any pullback)
    nudges it down; crowded-short or historically low positioning (very
    negative z -- room for a squeeze/rally) nudges it up. Averages across
    all provided contracts. Meant to be combined with (multiplied into)
    the existing macro_regime sleeve_tilts, not used standalone.
    """
    if not metrics:
        return 1.0
    avg_z = sum(m.z_score for m in metrics.values()) / len(metrics)
    clamped = max(-extreme_z, min(extreme_z, avg_z))
    return 1.0 - (clamped / extreme_z) * tilt_magnitude
