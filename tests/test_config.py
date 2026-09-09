"""
Regression tests for config loading and variable substitution (BACKEND-BUG-9).
"""

import yaml

from jarvis.config_loader import ConfigLoader


class TestConfigEmptyYaml:
    def test_load_empty_yaml_returns_dict(self, tmp_path):
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("# Only a comment\n", encoding="utf-8")

        loader = ConfigLoader(str(empty_file))
        # safe_load returns None for comment-only file, but loader must convert to {}
        # validation will fail with SystemExit because {} misses required keys,
        # but _expand receives {} instead of None.
        raw_config = yaml.safe_load(empty_file.read_text()) or {}
        assert isinstance(raw_config, dict)
        assert raw_config == {}

        expanded = loader._expand(raw_config)
        assert expanded == {}


class TestConfigDefaultSyntax:
    def test_expand_default_when_var_missing(self, monkeypatch, caplog):
        monkeypatch.delenv("UNSET_JARVIS_VAR", raising=False)
        ConfigLoader._warned_vars.clear()

        loader = ConfigLoader("dummy.yaml")
        data = {"model": "${UNSET_JARVIS_VAR:-qwen2.5:7b}"}

        res = loader._expand(data)
        assert res["model"] == "qwen2.5:7b"
        assert "Environment variable UNSET_JARVIS_VAR is not set" not in caplog.text

    def test_expand_default_when_var_present(self, monkeypatch):
        monkeypatch.setenv("SET_JARVIS_VAR", "llama3.2")

        loader = ConfigLoader("dummy.yaml")
        data = {"model": "${SET_JARVIS_VAR:-qwen2.5:7b}"}

        res = loader._expand(data)
        assert res["model"] == "llama3.2"

    def test_expand_default_empty_default(self, monkeypatch):
        monkeypatch.delenv("UNSET_JARVIS_VAR_EMPTY", raising=False)

        loader = ConfigLoader("dummy.yaml")
        data = {"token": "${UNSET_JARVIS_VAR_EMPTY:-}"}

        res = loader._expand(data)
        assert res["token"] == ""
