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

_ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')


class ConfigLoader:
    """Читает yaml, подставляет ${VAR}, расширяет ~, валидирует через pydantic."""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        if not self.config_path.is_absolute():
            self.config_path = Path.cwd() / config_path

    def load(self) -> dict:
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            config = self._expand(config)
            try:
                from jarvis.config_schema import validate_config
                config = validate_config(config)
            except ImportError:
                logger.debug("config_schema не найден, пропускаю валидацию")
            return config
        except Exception as e:
            print(f"❌ Ошибка загрузки конфига {self.config_path}: {e}")
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
            if '$HOME' in obj:
                obj = obj.replace('$HOME', os.path.expanduser('~'))
            if obj.startswith('~/'):
                obj = os.path.expanduser(obj)
            return obj
        return obj

    @staticmethod
    def _sub_var(match: re.Match) -> str:
        var = match.group(1)
        val = os.environ.get(var)
        if val is None:
            logger.warning(
                "Environment variable %s is not set — substituting with empty string",
                var,
            )
            return ""
        return val
