"""
Run with:
    pytest tests/test_github_state_sync.py -v
"""
import sys
import os
import json
import base64
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import github_state_sync as sync


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_get_github_config_none_when_unset(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    assert sync.get_github_config() is None


def test_get_github_config_present_with_default_branch(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setenv("GITHUB_REPO", "me/myrepo")
    monkeypatch.delenv("GITHUB_BRANCH", raising=False)
    config = sync.get_github_config()
    assert config == {"token": "tok123", "repo": "me/myrepo", "branch": "main"}


def test_pull_state_from_github_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    assert sync.pull_state_from_github() == 0


def test_pull_state_from_github_writes_existing_files_and_skips_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setenv("GITHUB_REPO", "me/myrepo")
    monkeypatch.setattr(sync, "STATE_DIR", str(tmp_path))

    fake_files = {
        "config/strategy_ledger.json": str(tmp_path / "strategy_ledger.json"),
        "config/decision_log.json": str(tmp_path / "decision_log.json"),
    }
    monkeypatch.setattr(sync, "STATE_FILES", fake_files)

    def fake_urlopen(request, timeout=15):
        if "strategy_ledger.json" in request.full_url:
            content = base64.b64encode(b'{"cash_reserve": 1000.0, "history": []}').decode("ascii")
            return FakeResponse(200, {"content": content, "sha": "abc123"})
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)

    pulled = sync.pull_state_from_github()
    assert pulled == 1
    with open(fake_files["config/strategy_ledger.json"]) as f:
        assert json.load(f) == {"cash_reserve": 1000.0, "history": []}
    assert not os.path.exists(fake_files["config/decision_log.json"])


def test_push_state_to_github_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    assert sync.push_state_to_github("/some/path.json") is False


def test_push_state_to_github_raises_on_unknown_path(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setenv("GITHUB_REPO", "me/myrepo")
    with pytest.raises(ValueError):
        sync.push_state_to_github("/not/a/known/state/file.json")


def test_push_state_to_github_returns_false_when_local_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setenv("GITHUB_REPO", "me/myrepo")
    missing_path = str(tmp_path / "strategy_ledger.json")
    monkeypatch.setattr(sync, "STATE_FILES", {"config/strategy_ledger.json": missing_path})
    assert sync.push_state_to_github(missing_path) is False


def test_push_state_to_github_creates_new_file_without_sha(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setenv("GITHUB_REPO", "me/myrepo")
    local_path = tmp_path / "strategy_ledger.json"
    local_path.write_text('{"cash_reserve": 1000.0, "history": []}', encoding="utf-8")
    monkeypatch.setattr(sync, "STATE_FILES", {"config/strategy_ledger.json": str(local_path)})

    calls = []

    def fake_urlopen(request, timeout=15):
        calls.append(request)
        if request.get_method() == "GET":
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        return FakeResponse(201, {"content": {}})

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)

    result = sync.push_state_to_github(str(local_path))
    assert result is True
    put_call = next(c for c in calls if c.get_method() == "PUT")
    body = json.loads(put_call.data.decode("utf-8"))
    assert "sha" not in body
    assert base64.b64decode(body["content"]).decode("utf-8") == '{"cash_reserve": 1000.0, "history": []}'


def test_push_state_to_github_updates_existing_file_with_sha(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setenv("GITHUB_REPO", "me/myrepo")
    local_path = tmp_path / "strategy_ledger.json"
    local_path.write_text('{"cash_reserve": 990.0, "history": []}', encoding="utf-8")
    monkeypatch.setattr(sync, "STATE_FILES", {"config/strategy_ledger.json": str(local_path)})

    calls = []

    def fake_urlopen(request, timeout=15):
        calls.append(request)
        if request.get_method() == "GET":
            return FakeResponse(200, {"content": base64.b64encode(b"{}").decode("ascii"), "sha": "existing-sha"})
        return FakeResponse(200, {"content": {}})

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)

    result = sync.push_state_to_github(str(local_path))
    assert result is True
    put_call = next(c for c in calls if c.get_method() == "PUT")
    body = json.loads(put_call.data.decode("utf-8"))
    assert body["sha"] == "existing-sha"
