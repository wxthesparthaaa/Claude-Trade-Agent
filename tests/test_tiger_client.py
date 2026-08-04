"""
Run with:
    pytest tests/test_tiger_client.py -v

Mocks TigerOpenClientConfig itself -- these tests are about OUR
credential-source-selection logic, not the third-party SDK's own parsing.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import tiger_client


class FakeTigerOpenClientConfig:
    def __init__(self, props_path, sandbox_debug):
        self.props_path = props_path
        self.sandbox_debug = sandbox_debug


def test_uses_local_file_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(tiger_client, "CONFIG_DIR", str(tmp_path))
    (tmp_path / "tiger_openapi_config.properties").write_text("tiger_id=123\n", encoding="utf-8")
    monkeypatch.setattr(tiger_client, "TigerOpenClientConfig", FakeTigerOpenClientConfig)
    monkeypatch.delenv("TIGER_ID", raising=False)

    config = tiger_client.get_client_config()
    assert config.props_path == str(tmp_path)


def test_synthesizes_from_env_vars_when_no_local_file(tmp_path, monkeypatch):
    empty_config_dir = tmp_path / "no_config_here"
    empty_config_dir.mkdir()
    monkeypatch.setattr(tiger_client, "CONFIG_DIR", str(empty_config_dir))
    state_dir = tmp_path / "state"
    monkeypatch.setattr(tiger_client, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(tiger_client, "TigerOpenClientConfig", FakeTigerOpenClientConfig)

    monkeypatch.setenv("TIGER_ID", "20160815")
    monkeypatch.setenv("TIGER_ACCOUNT", "21164032225544222")
    monkeypatch.setenv("TIGER_PRIVATE_KEY_PK1", "fake-pk1")
    monkeypatch.setenv("TIGER_PRIVATE_KEY_PK8", "fake-pk8")
    monkeypatch.setenv("TIGER_LICENSE", "TBSG")
    monkeypatch.setenv("TIGER_ENV", "PROD")

    config = tiger_client.get_client_config()
    assert config.props_path == str(state_dir)

    written = (state_dir / "tiger_openapi_config.properties").read_text(encoding="utf-8")
    assert "tiger_id=20160815" in written
    assert "account=21164032225544222" in written
    assert "private_key_pk1=fake-pk1" in written
    assert "license=TBSG" in written
    assert "env=PROD" in written


def test_raises_when_neither_file_nor_env_vars_present(tmp_path, monkeypatch):
    empty_config_dir = tmp_path / "no_config_here"
    empty_config_dir.mkdir()
    monkeypatch.setattr(tiger_client, "CONFIG_DIR", str(empty_config_dir))
    monkeypatch.delenv("TIGER_ID", raising=False)

    with pytest.raises(FileNotFoundError):
        tiger_client.get_client_config()


def test_sandbox_flag_passed_through(tmp_path, monkeypatch):
    monkeypatch.setattr(tiger_client, "CONFIG_DIR", str(tmp_path))
    (tmp_path / "tiger_openapi_config.properties").write_text("tiger_id=123\n", encoding="utf-8")
    monkeypatch.setattr(tiger_client, "TigerOpenClientConfig", FakeTigerOpenClientConfig)

    config = tiger_client.get_client_config(sandbox=True)
    assert config.sandbox_debug is True
