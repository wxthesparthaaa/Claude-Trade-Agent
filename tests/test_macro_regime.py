"""
Run with:
    pytest tests/test_macro_regime.py -v
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from macro_regime import (
    RegimeSignal, load_regime_signal, apply_regime_tilt,
    update_positioning_tilt, update_breadth_signal, effective_sleeve_tilts,
)


def test_load_regime_signal_parses_file(tmp_path):
    path = tmp_path / "regime.json"
    path.write_text(json.dumps({
        "as_of": "2026-07-31",
        "regime": "reflation",
        "sleeve_tilts": {"core": 0.9, "satellite": 1.1},
        "sources": ["https://example.com/outlook"],
        "notes": "test note",
    }), encoding="utf-8")

    signal = load_regime_signal(str(path))
    assert signal.as_of == "2026-07-31"
    assert signal.regime == "reflation"
    assert signal.sleeve_tilts == {"core": 0.9, "satellite": 1.1}
    assert signal.sources == ["https://example.com/outlook"]
    assert signal.notes == "test note"


def test_load_regime_signal_defaults_optional_fields(tmp_path):
    path = tmp_path / "regime.json"
    path.write_text(json.dumps({
        "as_of": "2026-07-31",
        "regime": "recovery",
        "sleeve_tilts": {},
    }), encoding="utf-8")

    signal = load_regime_signal(str(path))
    assert signal.sources == []
    assert signal.notes == ""


def test_apply_regime_tilt_preserves_total():
    base_weights = {"core": 400.0, "satellite": 600.0}
    tilted = apply_regime_tilt(base_weights, {"core": 0.9, "satellite": 1.1})
    assert sum(tilted.values()) == pytest.approx(sum(base_weights.values()))
    # satellite should end up with a larger share than before the tilt
    assert tilted["satellite"] / sum(tilted.values()) > 600.0 / 1000.0


def test_apply_regime_tilt_missing_key_defaults_to_no_tilt():
    base_weights = {"core": 400.0, "satellite": 600.0}
    tilted = apply_regime_tilt(base_weights, {"satellite": 1.2})
    # core has no tilt entry -> effectively 1.0, only renormalized
    assert tilted["core"] > 0


def test_apply_regime_tilt_empty_base_weights():
    assert apply_regime_tilt({}, {"core": 1.1}) == {}


def test_apply_regime_tilt_raises_on_zeroed_out_weights():
    with pytest.raises(ValueError):
        apply_regime_tilt({"core": 400.0}, {"core": 0.0})


def test_load_regime_signal_defaults_positioning_fields_when_absent(tmp_path):
    path = tmp_path / "regime.json"
    path.write_text(json.dumps({"as_of": "2026-07-31", "regime": "recovery", "sleeve_tilts": {}}), encoding="utf-8")
    signal = load_regime_signal(str(path))
    assert signal.positioning_tilt is None
    assert signal.positioning_as_of is None
    assert signal.positioning_notes == ""


def test_update_positioning_tilt_preserves_qualitative_fields(tmp_path):
    path = tmp_path / "regime.json"
    path.write_text(json.dumps({
        "as_of": "2026-07-31", "regime": "recovery", "sleeve_tilts": {"core": 0.95, "satellite": 1.05},
        "sources": ["https://example.com"], "notes": "curated research",
    }), encoding="utf-8")

    update_positioning_tilt(str(path), positioning_tilt=0.97, as_of="2026-08-07", notes="COT: crowded long S&P")

    signal = load_regime_signal(str(path))
    assert signal.regime == "recovery"  # untouched
    assert signal.sleeve_tilts == {"core": 0.95, "satellite": 1.05}  # untouched
    assert signal.notes == "curated research"  # untouched
    assert signal.positioning_tilt == 0.97
    assert signal.positioning_as_of == "2026-08-07"
    assert signal.positioning_notes == "COT: crowded long S&P"


def test_update_positioning_tilt_creates_file_if_missing(tmp_path):
    path = tmp_path / "regime.json"
    update_positioning_tilt(str(path), positioning_tilt=1.02, as_of="2026-08-07")
    signal = load_regime_signal(str(path))
    assert signal.positioning_tilt == 1.02
    assert signal.regime == "unknown"  # placeholder, real regime refresh still needed separately


def test_effective_sleeve_tilts_multiplies_satellite_by_positioning():
    regime = RegimeSignal(
        as_of="2026-08-07", regime="recovery", sleeve_tilts={"core": 0.95, "satellite": 1.05},
        sources=[], positioning_tilt=0.9,
    )
    tilts = effective_sleeve_tilts(regime)
    assert tilts["core"] == 0.95  # unaffected
    assert tilts["satellite"] == pytest.approx(1.05 * 0.9)


def test_effective_sleeve_tilts_no_positioning_data_leaves_tilts_unchanged():
    regime = RegimeSignal(as_of="2026-08-07", regime="recovery", sleeve_tilts={"core": 0.95, "satellite": 1.05}, sources=[])
    assert effective_sleeve_tilts(regime) == {"core": 0.95, "satellite": 1.05}


def test_load_regime_signal_defaults_breadth_fields_when_absent(tmp_path):
    path = tmp_path / "regime.json"
    path.write_text(json.dumps({"as_of": "2026-07-31", "regime": "recovery", "sleeve_tilts": {}}), encoding="utf-8")
    signal = load_regime_signal(str(path))
    assert signal.breadth_trend is None
    assert signal.breadth_as_of is None
    assert signal.breadth_notes == ""
    assert signal.breadth_tilt is None
    assert signal.breadth_at_edge is False


def test_update_breadth_signal_preserves_qualitative_and_positioning_fields(tmp_path):
    path = tmp_path / "regime.json"
    path.write_text(json.dumps({
        "as_of": "2026-07-31", "regime": "recovery", "sleeve_tilts": {"core": 0.95, "satellite": 1.05},
        "sources": ["https://example.com"], "notes": "curated research",
        "positioning_tilt": 0.97, "positioning_as_of": "2026-08-07", "positioning_notes": "COT note",
    }), encoding="utf-8")

    update_breadth_signal(str(path), breadth_tilt=1.05, trend="broadening", at_edge=False,
                           as_of="2026-08-08", notes="RSP/SPY broadening")

    signal = load_regime_signal(str(path))
    assert signal.regime == "recovery"  # untouched
    assert signal.sleeve_tilts == {"core": 0.95, "satellite": 1.05}  # untouched
    assert signal.positioning_tilt == 0.97  # untouched
    assert signal.breadth_tilt == 1.05
    assert signal.breadth_trend == "broadening"
    assert signal.breadth_at_edge is False
    assert signal.breadth_as_of == "2026-08-08"
    assert signal.breadth_notes == "RSP/SPY broadening"


def test_update_breadth_signal_creates_file_if_missing(tmp_path):
    path = tmp_path / "regime.json"
    update_breadth_signal(str(path), breadth_tilt=0.95, trend="narrowing", at_edge=True, as_of="2026-08-08")
    signal = load_regime_signal(str(path))
    assert signal.breadth_tilt == 0.95
    assert signal.regime == "unknown"  # placeholder, real regime refresh still needed separately


def test_effective_sleeve_tilts_multiplies_satellite_by_breadth():
    regime = RegimeSignal(
        as_of="2026-08-08", regime="recovery", sleeve_tilts={"core": 0.95, "satellite": 1.05},
        sources=[], breadth_tilt=1.1,
    )
    tilts = effective_sleeve_tilts(regime)
    assert tilts["core"] == 0.95  # unaffected
    assert tilts["satellite"] == pytest.approx(1.05 * 1.1)


def test_effective_sleeve_tilts_combines_positioning_and_breadth_multiplicatively():
    regime = RegimeSignal(
        as_of="2026-08-08", regime="recovery", sleeve_tilts={"core": 0.95, "satellite": 1.05},
        sources=[], positioning_tilt=0.9, breadth_tilt=1.1,
    )
    tilts = effective_sleeve_tilts(regime)
    assert tilts["satellite"] == pytest.approx(1.05 * 0.9 * 1.1)
