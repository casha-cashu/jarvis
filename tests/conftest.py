"""
Общие фикстуры для тестов JARVIS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch
import pytest

from jarvis._env import sanitized_env

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_CONFIG_PATH = PROJECT_ROOT / "config.test.yaml"


@pytest.fixture(autouse=True)
def isolate_jarvis_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Изолирует файловую систему и переменные окружения JARVIS для каждого теста:
    - JARVIS_DATA_DIR указывает в tmp_path / 'data'
    - JARVIS_HISTORY_FILE указывает в tmp_path / 'data' / 'history.json'
    - JARVIS_NLU_CACHE указывает в tmp_path / 'nlu_cache'
    - JARVIS_CONFIG_PATH указывает на тестовый конфиг
    """
    data_dir = tmp_path / "jarvis_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    history_file = data_dir / "history.json"
    nlu_cache = tmp_path / "jarvis_nlu"
    nlu_cache.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JARVIS_HISTORY_FILE", str(history_file))
    monkeypatch.setenv("JARVIS_NLU_CACHE", str(nlu_cache))
    if TEST_CONFIG_PATH.exists():
        monkeypatch.setenv("JARVIS_CONFIG_PATH", str(TEST_CONFIG_PATH))

    # Сбрасываем кэш модулей персистентности, если они уже были импортированы
    try:
        import jarvis.modules.llm as llm_mod

        monkeypatch.setattr(llm_mod, "HISTORY_FILE", history_file)
        with llm_mod._history_locks_guard:
            llm_mod._history_locks.clear()
    except (ImportError, AttributeError):
        pass

    try:
        import jarvis.modules.nlu as nlu_mod

        monkeypatch.setattr(nlu_mod, "CACHE_DIR", nlu_cache)
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def check_sanitized_env():
    """
    Помощник для проверки, что переданное окружение соответствует правилу sanitized_env().
    Убеждается, что секреты не просочились и присутствуют базовые переменные.
    """

    def _check(
        env: Optional[Dict[str, str]], extra_allowed: Optional[set[str]] = None
    ) -> bool:
        assert env is not None, "env parameter must be passed explicitly"
        reference = sanitized_env()
        # Проверяем отсутствие критических секретов
        for secret_key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "KIRO_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "GITHUB_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
        ):
            assert secret_key not in env, (
                f"Secret {secret_key} leaked into subprocess env!"
            )
        # Проверяем, что не добавлены случайные переменные не из allowlist
        allowed_keys = set(reference.keys())
        if extra_allowed:
            allowed_keys |= extra_allowed
        for key in env:
            assert key in allowed_keys, f"Key {key} not allowed in sanitized env"
        return True

    return _check


@pytest.fixture
def sample_config() -> dict[str, Any]:
    """Минимальная конфигурация для тестов (без реальных файлов/ключей)."""
    return {
        "stt": {
            "engine": "vosk",
            "sample_rate": 16000,
            "vosk": {"model_path": "/tmp/test-vosk", "model_size": "small-ru"},
            "whisper": {
                "model_size": "tiny",
                "model_path": None,
                "partial_interval_ms": 1000,
            },
            "wake_word": "джарвис",
            "wake_word_alternatives": [],
            "phrase_time_limit": 10,
            "multi_turn_timeout": 10,
            "wake_mode": "classic",
            "continuous": False,
        },
        "vad": {"enabled": False, "engine": "silero", "silero": {"threshold": 0.5}},
        "tts": {
            "engine": "piper",
            "piper": {
                "binary_path": "/usr/bin/false",
                "model_path": "/tmp/test-piper.onnx",
                "speaker_id": 0,
                "length_scale": 1.0,
            },
        },
        "llm": {
            "provider": "ollama",
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "test-model",
                "temperature": 0.7,
                "timeout": 120,
            },
            "max_history": 20,
            "system_prompt": "Test prompt",
            "agent_enabled": False,
            "agent_approval_mode": "auto",
        },
        "commands": {
            "dictionary_path": "data/commands.json",
            "apps_dictionary_path": "data/apps.json",
            "fuzzy_threshold": 0.8,
            "execution_timeout": 30,
            "nlu_enabled": True,
            "nlu_confidence_threshold": 0.65,
        },
        "logging": {
            "level": "DEBUG",
            "file": "/tmp/jarvis-test.log",
            "max_size": 10485760,
        },
        "misc": {"temp_dir": "/tmp/jarvis-test"},
    }


@pytest.fixture
def jarvis_instance(sample_config: dict[str, Any]):
    """
    Создаёт экземпляр Jarvis с замоканным _load_config,
    чтобы не читать реальный файл и не вызывать sys.exit().
    """
    from jarvis import Jarvis

    with patch.object(Jarvis, "_load_config", return_value=sample_config):
        j = Jarvis(config_path="/nonexistent/config.yaml", verbose=False)
        j.stt = None
        j.tts = None
        j.llm = None
        j.commands = None
    return j
