"""Тесты jarvis.doctor — диагностика не должна падать и обязана честно
ставить статусы. Всё hermetic: конфиг из tmp/репо, сеть не трогаем
(ollama указывает на закрытый порт)."""

from pathlib import Path

import yaml

from jarvis.doctor import FAIL, OK, WARN, exit_code, run_checks

REPO_CONFIG = Path(__file__).parent.parent / "config.test.yaml"


def _run_with_config_dict(tmp_path, config: dict):
    """doctor читает yaml-файл — пишем временный и прогоняем."""
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    return run_checks(str(p))


class TestRunChecks:
    def test_valid_config_no_crash(self, tmp_path):
        """Валидный конфиг: все проверки вернули статус, ничего не упало."""
        config = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
        # ollama на закрытом портe — детерминированно FAIL/WARN без сети
        config["llm"] = {
            "provider": "ollama",
            "ollama": {"base_url": "http://127.0.0.1:1", "model": "test"},
        }
        checks = _run_with_config_dict(tmp_path, config)
        assert len(checks) >= 8
        assert all(set(c) >= {"name", "status", "detail"} for c in checks)
        assert all(c["status"] in (OK, WARN, FAIL) for c in checks)

    def test_config_fail_is_fail_not_crash(self, tmp_path):
        """Невалидный yaml → статус FAIL, а не исключение из doctor."""
        p = tmp_path / "config.yaml"
        p.write_text("{broken yaml: [", encoding="utf-8")
        checks = run_checks(str(p))
        config_check = next(c for c in checks if c["name"] == "Конфиг")
        assert config_check["status"] == FAIL

    def test_missing_config_file(self, tmp_path):
        checks = run_checks(str(tmp_path / "nope.yaml"))
        config_check = next(c for c in checks if c["name"] == "Конфиг")
        assert config_check["status"] == FAIL
        assert exit_code(checks) == 1

    def test_typo_in_config_key_is_caught(self, tmp_path):
        """forbid-схема: опечатка silense_threshold → конфиг = FAIL.
        Это главный продающий кейс doctor'а."""
        config = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
        config["stt"]["silense_threshold"] = 2.0
        checks = _run_with_config_dict(tmp_path, config)
        config_check = next(c for c in checks if c["name"] == "Конфиг")
        assert config_check["status"] == FAIL
        assert exit_code(checks) == 1

    def test_missing_data_files_is_warn(self, tmp_path):
        config = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
        config["commands"] = {
            "dictionary_path": "data/does-not-exist.json",
            "apps_dictionary_path": "data/nope.json",
        }
        checks = _run_with_config_dict(tmp_path, config)
        data_check = next(c for c in checks if c["name"] == "Словари команд")
        assert data_check["status"] == WARN


class TestExitCode:
    def test_warn_is_zero(self):
        checks = [{"name": "x", "status": WARN, "detail": ""}]
        assert exit_code(checks) == 0

    def test_fail_is_one(self):
        checks = [
            {"name": "x", "status": OK, "detail": ""},
            {"name": "y", "status": FAIL, "detail": ""},
        ]
        assert exit_code(checks) == 1


def test_version_string():
    """jarvis --version отдаёт номер версии из метаданных пакета."""
    import re

    from jarvis.cli import _version

    assert re.match(r"JARVIS \d+\.\d+", _version())
