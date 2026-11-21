"""
Growth's index-core switch (shipped 2026-11-21 by the weekly research
routine, research/shipped_changes.md): the core sleeve holds ONE index
ETF (QQQ) while it is in an uptrend and sits in cash otherwise, instead
of trend-ranking the core ETFs.

"Uptrend" is the 200-day SMA with hysteresis, so a close that hovers
around the average doesn't flip the core in and out (the whipsaw that
cost the plain 200d switch ~8 points of extra drawdown in 2022):
  - risk-on once a close is above SMA * (1 + band_pct),
  - risk-off once a close is below SMA * (1 - band_pct),
  - anything in between keeps the previous state.
The state is replayed from the price history on every scan, so no state
file is needed and a restart/redeploy resumes on its own.

Only COMPLETED daily closes count (bars dated before `today`): live scans
run during the session and their last bar is today's partial one. This is
the research harness's `Params(core_switch=('QQQ', 'CASH', 200),
csw_band=0.02, core_hold=True)`.

Pure logic, no network.
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class CoreSwitchConfig:
    symbol: str = "QQQ"
    sma_days: int = 200
    band_pct: float = 0.02
    # Daily bars fetched for `symbol` (vs ~156 for everything else): the
    # SMA needs sma_days of them, the rest is hysteresis replay history.
    history_bars: int = 500


def core_switch_risk_on(
    prices: List[Tuple[date, float]], sma_days: int, band_pct: float, today: date,
) -> Optional[bool]:
    """True = hold the index core, False = core in cash, None = not enough
    completed history to tell (the caller then allows no NEW core entry)."""
    closes = [c for d, c in prices if d < today]
    if len(closes) < sma_days or sma_days <= 0:
        return None
    state = False
    window_sum = sum(closes[:sma_days])
    for k in range(sma_days - 1, len(closes)):
        if k >= sma_days:
            window_sum += closes[k] - closes[k - sma_days]
        sma = window_sum / sma_days
        if closes[k] > sma * (1 + band_pct):
            state = True
        elif closes[k] < sma * (1 - band_pct):
            state = False
    return state
