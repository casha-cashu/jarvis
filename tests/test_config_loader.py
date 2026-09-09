"""
Тесты для jarvis.config_loader.ConfigLoader.
Проверка загрузки yaml, подстановки переменных окружения, путей ~ и валидации.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
import yaml

from jarvis.config_loader import ConfigLoader


class TestConfigLoaderInit:
    def test_init_absolute_path(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        loader = ConfigLoader(str(p))
        assert loader.config_path == p

    def test_init_relative_path(self):
        loader = ConfigLoader("config.yaml")
        assert loader.config_path == Path.cwd() / "config.yaml"


class TestConfigLoaderExpansion:
    def test_expand_env_vars_present(self, monkeypatch):
        monkeypatch.setenv("TEST_JARVIS_MODEL", "qwen-test")
        monkeypatch.setenv("TEST_JARVIS_PORT", "8080")

        loader = ConfigLoader("dummy.yaml")
        data = {
            "model": "${TEST_JARVIS_MODEL}",
            "url": "http://localhost:${TEST_JARVIS_PORT}/v1",
        }
        res = loader._expand(data)
        assert res["model"] == "qwen-test"
        assert res["url"] == "http://localhost:8080/v1"

    def test_expand_env_vars_missing_logs_warning_and_substitutes_empty(
        self, monkeypatch, caplog
    ):
        monkeypatch.delenv("NON_EXISTENT_VAR_XYZ", raising=False)
        ConfigLoader._warned_vars.clear()

        loader = ConfigLoader("dummy.yaml")
        data = {"key": "${NON_EXISTENT_VAR_XYZ}"}

        res = loader._expand(data)
        assert res["key"] == ""
        assert "Environment variable NON_EXISTENT_VAR_XYZ is not set" in caplog.text

    def test_expand_home_and_tilde(self, monkeypatch):
        home_path = os.path.expanduser("~")
        loader = ConfigLoader("dummy.yaml")

        data = {
            "path_home": "$HOME/test_dir",
            "path_tilde": "~/test_dir/file.txt",
            "plain_text": "hello ~ world",
        }
        res = loader._expand(data)
        assert res["path_home"] == f"{home_path}/test_dir"
        assert res["path_tilde"] == f"{home_path}/test_dir/file.txt"
        assert res["plain_text"] == "hello ~ world"

    def test_expand_nested_structures(self, monkeypatch):
        monkeypatch.setenv("NESTED_VAR", "value123")
        loader = ConfigLoader("dummy.yaml")

        data = {
            "section": {
                "items": ["${NESTED_VAR}", 42, True, None],
                "sub": {"val": "prefix_${NESTED_VAR}"},
            }
        }
        res = loader._expand(data)
        assert res["section"]["items"][0] == "value123"
        assert res["section"]["items"][1] == 42
        assert res["section"]["sub"]["val"] == "prefix_value123"


class TestConfigLoaderLoad:
    def test_load_valid_config(self, tmp_path, sample_config):
        cfg_file = tmp_path / "valid_config.yaml"
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump(sample_config, f)

        loader = ConfigLoader(str(cfg_file))
        loaded = loader.load()

        assert isinstance(loaded, dict)
        assert loaded["stt"]["engine"] == "vosk"
        assert loaded["tts"]["engine"] == "piper"
        assert loaded["llm"]["provider"] == "ollama"

    def test_load_nonexistent_file_exits(self, tmp_path):
        loader = ConfigLoader(str(tmp_path / "nonexistent.yaml"))
        with pytest.raises(SystemExit) as exc_info:
            loader.load()
        assert exc_info.value.code == 1

    def test_load_invalid_yaml_exits(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{ unclosed bracket: [", encoding="utf-8")

        loader = ConfigLoader(str(bad_file))
        with pytest.raises(SystemExit) as exc_info:
            loader.load()
        assert exc_info.value.code == 1

    def test_load_invalid_schema_exits(self, tmp_path):
        bad_cfg = tmp_path / "invalid_schema.yaml"
        # STT engine "invalid_engine" не разрешён схемой
        bad_cfg.write_text("stt:\n  engine: invalid_engine\n", encoding="utf-8")

        loader = ConfigLoader(str(bad_cfg))
        with pytest.raises(SystemExit) as exc_info:
            loader.load()
        assert exc_info.value.code == 1
