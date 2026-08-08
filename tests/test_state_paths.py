"""
Run with:
    pytest tests/test_state_paths.py -v
"""
import sys
import os
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_state_dir_defaults_to_local_config_dir(monkeypatch):
    monkeypatch.delenv("STATE_DIR", raising=False)
    import state_paths
    importlib.reload(state_paths)
    assert state_paths.STATE_DIR.replace("\\", "/").endswith("options-agent/config")


def test_state_dir_respects_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    import state_paths
    importlib.reload(state_paths)
    assert state_paths.STATE_DIR == str(tmp_path)
    assert state_paths.LEDGER_PATH == os.path.join(str(tmp_path), "strategy_ledger.json")
    monkeypatch.delenv("STATE_DIR", raising=False)
    importlib.reload(state_paths)


def test_state_files_map_matches_individual_constants():
    import state_paths
    importlib.reload(state_paths)
    assert state_paths.STATE_FILES["config/strategy_ledger.json"] == state_paths.LEDGER_PATH
    assert state_paths.STATE_FILES["config/decision_log.json"] == state_paths.DECISION_LOG_PATH
    assert state_paths.STATE_FILES["config/strategy_changelog.json"] == state_paths.CHANGELOG_PATH
    assert state_paths.STATE_FILES["config/news_signal.json"] == state_paths.NEWS_PATH
    assert state_paths.STATE_FILES["config/regime.json"] == state_paths.REGIME_PATH
    assert state_paths.STATE_FILES["config/portfolio_snapshot.json"] == state_paths.SNAPSHOT_PATH


def test_dividend_state_files_are_distinct_paths_from_growth():
    import state_paths
    importlib.reload(state_paths)
    assert state_paths.LEDGER_PATH_DIVIDEND != state_paths.LEDGER_PATH
    assert state_paths.DECISION_LOG_PATH_DIVIDEND != state_paths.DECISION_LOG_PATH
    assert state_paths.SNAPSHOT_PATH_DIVIDEND != state_paths.SNAPSHOT_PATH
    assert state_paths.PENDING_APPROVALS_PATH_DIVIDEND != state_paths.PENDING_APPROVALS_PATH


def test_state_files_map_includes_dividend_paths():
    import state_paths
    importlib.reload(state_paths)
    assert state_paths.STATE_FILES["config/strategy_ledger_dividend.json"] == state_paths.LEDGER_PATH_DIVIDEND
    assert state_paths.STATE_FILES["config/decision_log_dividend.json"] == state_paths.DECISION_LOG_PATH_DIVIDEND
    assert state_paths.STATE_FILES["config/portfolio_snapshot_dividend.json"] == state_paths.SNAPSHOT_PATH_DIVIDEND
    assert state_paths.STATE_FILES["config/pending_approvals_dividend.json"] == state_paths.PENDING_APPROVALS_PATH_DIVIDEND
