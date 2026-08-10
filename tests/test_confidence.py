"""
Run with:
    pytest tests/test_confidence.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from confidence import score_to_confidence


def test_zero_score_is_exactly_fifty_percent():
    assert score_to_confidence(0.0, scale=0.15) == 50.0


def test_positive_score_above_fifty_percent():
    assert score_to_confidence(0.15, scale=0.15) > 50.0


def test_negative_score_below_fifty_percent():
    assert score_to_confidence(-0.15, scale=0.15) < 50.0


def test_solid_growth_candidate_crosses_execute_threshold():
    # score=0.15 -- a decent momentum-driven candidate under growth's
    # default weights -- should land comfortably above the 70% default
    # execute threshold, per the plan's chosen scale=0.15.
    assert score_to_confidence(0.15, scale=0.15) == pytest.approx(73.1, abs=0.1)


def test_weak_candidate_lands_below_shortlist_threshold():
    assert score_to_confidence(-0.15, scale=0.15) == pytest.approx(26.9, abs=0.1)


def test_monotonic_increasing_in_score():
    scores = [-0.3, -0.1, 0.0, 0.05, 0.2, 0.4]
    confidences = [score_to_confidence(s, scale=0.15) for s in scores]
    assert confidences == sorted(confidences)


def test_within_realistic_range_stays_inside_open_interval():
    # This project's composite scores realistically stay within roughly
    # [-0.5, 0.5] (momentum/div_yield/news_tilt weighted blend) -- at
    # scale=0.15 that's still comfortably short of the rounding-to-0/100
    # extremes, unlike a synthetic +-10 score would be.
    for score in (-0.5, -0.01, 0.0, 0.01, 0.5):
        c = score_to_confidence(score, scale=0.15)
        assert 0.0 < c < 100.0


def test_smaller_scale_makes_confidence_more_sensitive_to_score():
    wide = score_to_confidence(0.05, scale=0.15)
    narrow = score_to_confidence(0.05, scale=0.05)
    assert narrow > wide  # same score, smaller scale -> further from 50%
