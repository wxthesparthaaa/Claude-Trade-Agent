"""
Squashes the existing unbounded composite `score` (stock_signal.
composite_score -- a signed real number, larger/more positive is more
attractive, but with no fixed range) into a clean 0-100% "confidence"
figure the settings panel's thresholds can compare against.

Approximate by construction -- a monotonic proxy for how strong a
candidate is, not a probability -- same "not dressed up as more precise
than it is" convention as news_relevance.py's keyword polarity score.
Never inverts relative ranking (the sigmoid is strictly increasing), so
anything that was already true about `score`-based ranking stays true.
"""
import math


def score_to_confidence(score: float, scale: float) -> float:
    """scale controls how quickly confidence moves away from 50% as
    score moves away from 0 -- see PortfolioProfile.confidence_scale
    for the reasoning behind the growth profile's chosen value."""
    return round(100 / (1 + math.exp(-score / scale)), 1)
