"""
Run with:
    pytest tests/test_scan_settings.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from scan_settings import ScanSettings, load_scan_settings, save_scan_settings, validate_scan_settings


def test_load_returns_defaults_when_file_missing(tmp_path):
    settings = load_scan_settings(str(tmp_path / "does_not_exist.json"))
    assert settings == ScanSettings()
    assert settings.autopilot is False
    assert settings.execute_threshold_pct == 70.0
    assert settings.shortlist_threshold_pct == 50.0
    assert settings.max_concurrent_trades == 10
    assert settings.capital == 1000.0


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "scan_settings.json")
    original = ScanSettings(autopilot=True, execute_threshold_pct=80.0,
                             shortlist_threshold_pct=55.0, max_concurrent_trades=6, capital=2500.0)
    save_scan_settings(path, original)
    loaded = load_scan_settings(path)
    assert loaded == original


def test_load_fills_missing_keys_with_defaults(tmp_path):
    import json
    path = str(tmp_path / "scan_settings.json")
    with open(path, "w") as f:
        json.dump({"autopilot": True}, f)  # partial/legacy file
    loaded = load_scan_settings(path)
    assert loaded.autopilot is True
    assert loaded.capital == 1000.0  # falls back to default


def test_validate_passes_for_defaults():
    validate_scan_settings(ScanSettings())  # must not raise


def test_validate_rejects_execute_below_shortlist():
    with pytest.raises(ValueError, match="Shortlist threshold"):
        validate_scan_settings(ScanSettings(execute_threshold_pct=40.0, shortlist_threshold_pct=50.0))


def test_validate_rejects_equal_thresholds():
    with pytest.raises(ValueError, match="Shortlist threshold"):
        validate_scan_settings(ScanSettings(execute_threshold_pct=50.0, shortlist_threshold_pct=50.0))


def test_validate_rejects_non_positive_capital():
    with pytest.raises(ValueError, match="Capital"):
        validate_scan_settings(ScanSettings(capital=0.0))


def test_validate_rejects_non_positive_max_concurrent_trades():
    with pytest.raises(ValueError, match="Max concurrent trades"):
        validate_scan_settings(ScanSettings(max_concurrent_trades=0))
