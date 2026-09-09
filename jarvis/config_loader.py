"""Загрузка и валидация JARVIS-конфигурации.

Отделено от `Jarvis.__init__` чтобы:
  - не поднимать STT/TTS/LLM модули только ради чтения yaml-файла
  - подставлять переменные окружения с явными warning'ами
    (P5: silent empty-string substitution был источником запутанных багов)
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


class ConfigLoader:
    """Читает yaml, подставляет ${VAR}, расширяет ~, валидирует через pydantic."""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        if not self.config_path.is_absolute():
            self.config_path = Path.cwd() / config_path

    def load(self) -> dict:
        target_path = self.config_path
        if not target_path.exists() and self.config_path.name in (
            "config.yaml",
            "config.yml",
        ):
            env_path = os.environ.get("JARVIS_CONFIG_PATH")
            user_config = Path.home() / ".config" / "jarvis" / "config.yaml"
            if env_path and Path(env_path).is_file():
                target_path = Path(env_path)
            elif user_config.is_file():
                target_path = user_config
            else:
                try:
                    from jarvis.resources import resource_path

                    example = Path(resource_path("config.example.yaml"))
                    if example.is_file():
                        target_path = example
                except Exception:
                    pass

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            config = self._expand(config)
            try:
                from jarvis.config_schema import validate_config

                config = validate_config(config)
            except ImportError:
                logger.debug("config_schema не найден, пропускаю валидацию")
            return config
        except Exception as e:
            # Логгер ещё не инициализирован настройками из config.yaml,
            # но root logger через logging всё равно пишет в stderr.
            logger.error("❌ Ошибка загрузки конфига %s: %s", target_path, e)
            sys.exit(1)

    def _expand(self, obj: Any) -> Any:
        """Подставляет ${VAR} и ~. Если переменной нет — пишет WARNING и
        подставляет пустую строку (P5).
        """
        if isinstance(obj, dict):
            return {k: self._expand(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._expand(item) for item in obj]
        if isinstance(obj, str):
            obj = _ENV_VAR_PATTERN.sub(self._sub_var, obj)
            if "$HOME" in obj:
                obj = obj.replace("$HOME", os.path.expanduser("~"))
            if obj.startswith("~/"):
                obj = os.path.expanduser(obj)
            return obj
        return obj

    _warned_vars: set[str] = set()

    @classmethod
    def _sub_var(cls, match: re.Match) -> str:
        expr = match.group(1)
        if ":-" in expr:
            var, default_val = expr.split(":-", 1)
        else:
            var, default_val = expr, None

        val = os.environ.get(var)
        if val is None:
            if default_val is not None:
                return default_val
            if var not in cls._warned_vars:
                cls._warned_vars.add(var)
                logger.warning(
                    "Environment variable %s is not set — substituting with empty string",
                    var,
                )
            return ""
        return val
