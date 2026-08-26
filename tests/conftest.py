"""
Общие фикстуры для тестов JARVIS.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_CONFIG_PATH = PROJECT_ROOT / "config.test.yaml"


@pytest.fixture
def test_config_path() -> Path:
    """Путь к тестовому config.yaml"""
    return TEST_CONFIG_PATH


@pytest.fixture
def sample_config() -> dict:
    """Минимальная конфигурация для тестов (без реальных файлов/ключей)."""
    return {
        "stt": {
            "engine": "vosk",
            "sample_rate": 16000,
            "vosk": {"model_path": "/tmp/test-vosk"},
            "wake_word": "джарвис",
            "wake_word_alternatives": [],
            "phrase_time_limit": 10,
            "multi_turn_timeout": 10,
        },
        "vad": {"enabled": False},
        "tts": {
            "engine": "piper",
            "piper": {
                "binary_path": "/usr/bin/false",
                "model_path": "/tmp/test-piper.onnx",
            },
        },
        "llm": {
            "provider": "ollama",
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "test-model",
                "temperature": 0.7,
            },
            "max_history": 20,
            "system_prompt": "Test prompt",
        },
        "commands": {
            "dictionary_path": "data/commands.json",
            "apps_dictionary_path": "data/apps.json",
            "fuzzy_threshold": 0.8,
        },
        "logging": {"level": "DEBUG", "file": "/tmp/jarvis-test.log"},
        "misc": {"temp_dir": "/tmp/jarvis-test"},
    }


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Устанавливает тестовые переменные окружения и чистит после теста."""
    monkeypatch.setenv("TEST_VAR", "test_value")
    monkeypatch.setenv("HOME", "/home/testuser")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    yield


@pytest.fixture
def jarvis_instance(sample_config):
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
