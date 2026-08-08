"""
Short-candidate signal: tactical, gated shorting "if the opportunity
arises" -- not a standing sleeve. Two independent pieces, both pure logic:

  - score_short_candidate: is this specific symbol in a real breakdown
    (deeply negative momentum), reusing the exact same momentum_score
    used for the long side.
  - market_favors_shorting: is the macro backdrop actually favorable for
    shorting right now, gated on signals already computed elsewhere
    (COT positioning crowding, market-breadth trend) rather than firing
    on any breakdown regardless of context. A single crowded-long or
    narrowing-breadth reading is "the tide may be turning," which is
    exactly the phrase this project's positioning-signal work was built
    around.

Neither function decides position sizing or places anything -- see
scan_workflow.py for how these gate and feed into the same allocate/
reconcile/risk-gate pipeline the long side already uses.
"""
from typing import List, Optional, Tuple
from datetime import date

from stock_signal import momentum_score

DEFAULT_BREAKDOWN_THRESHOLD = -0.15
DEFAULT_CROWDED_LONG_TILT_THRESHOLD = 0.92


def score_short_candidate(
    prices: List[Tuple[date, float]],
    lookback_days: int = 126,
    skip_recent_days: int = 21,
    breakdown_threshold: float = DEFAULT_BREAKDOWN_THRESHOLD,
) -> Optional[float]:
    """
    Returns the momentum value (a negative fraction, e.g. -0.18) only if
    it's at or below breakdown_threshold -- a real downtrend, not just
    "not doing great." Returns None otherwise (including when there isn't
    enough price history yet), same "not eligible" convention as
    stock_signal.score_symbol.
    """
    try:
        momentum = momentum_score(prices, lookback_days=lookback_days, skip_recent_days=skip_recent_days)
    except ValueError:
        return None
    return momentum if momentum <= breakdown_threshold else None


def market_favors_shorting(
    regime,
    crowded_threshold: float = DEFAULT_CROWDED_LONG_TILT_THRESHOLD,
) -> bool:
    """
    Gates the whole short-candidate pass on an actual macro signal rather
    than letting any single breakdown fire a short. regime is a
    macro_regime.RegimeSignal (or None if no regime file exists yet).

    True if EITHER:
      - COT positioning shows crowded-long conditions (regime.positioning_tilt
        at or below crowded_threshold -- reuses the already-persisted COT
        signal, no new data needed), OR
      - the market-breadth trend (RSP/SPY) is narrowing AND at an edge
        (regime.breadth_trend == "narrowing" and regime.breadth_at_edge) --
        the average stock underperforming mega-caps, stretched enough that
        the move may be near exhaustion.

    Both are "the tide may be turning" reads from independent data, not
    one signal counted twice.
    """
    if regime is None:
        return False

    cot_crowded = regime.positioning_tilt is not None and regime.positioning_tilt <= crowded_threshold
    breadth_narrowing_at_edge = regime.breadth_trend == "narrowing" and regime.breadth_at_edge
    return cot_crowded or breadth_narrowing_at_edge
