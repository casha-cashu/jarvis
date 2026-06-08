"""
Тесты для LLM модуля (jarvis/modules/llm.py) и ConfigLoader._expand.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from jarvis.config_loader import ConfigLoader


# ──────────────────────────────────────────────
# Тесты ConfigLoader._expand (переехали из Jarvis._expand_env_vars)
# ──────────────────────────────────────────────

class TestExpandEnvVars:
    """Тестирует ConfigLoader._expand (экс-Jarvis._expand_env_vars)."""

    @pytest.fixture
    def loader(self):
        return ConfigLoader("/nonexistent/config.yaml")

    def test_simple_string(self, loader):
        """${VAR} подставляется из окружения."""
        os.environ["_TEST_JARVIS_VAR_"] = "hello"
        result = loader._expand("prefix_${_TEST_JARVIS_VAR_}_suffix")
        assert result == "prefix_hello_suffix"
        del os.environ["_TEST_JARVIS_VAR_"]

    def test_dict_recursive(self, loader):
        """Рекурсивная подстановка в dict."""
        os.environ["_TEST_JARVIS_VAR_"] = "world"
        d = {"key": "hello_${_TEST_JARVIS_VAR_}", "nested": {"inner": "${_TEST_JARVIS_VAR_}_end"}}
        result = loader._expand(d)
        assert result["key"] == "hello_world"
        assert result["nested"]["inner"] == "world_end"
        del os.environ["_TEST_JARVIS_VAR_"]

    def test_list_recursive(self, loader):
        """Рекурсивная подстановка в list."""
        os.environ["_TEST_JARVIS_VAR_"] = "42"
        lst = ["item_${_TEST_JARVIS_VAR_}", ["deep_${_TEST_JARVIS_VAR_}"]]
        result = loader._expand(lst)
        assert result[0] == "item_42"
        assert result[1][0] == "deep_42"
        del os.environ["_TEST_JARVIS_VAR_"]

    def test_home_variable(self, loader):
        """$HOME заменяется на домашнюю директорию."""
        result = loader._expand("$HOME/models")
        assert result.startswith("/")
        assert result.endswith("/models")

    def test_tilde_expansion(self, loader):
        """~ в начале пути раскрывается."""
        result = loader._expand("~/test/path")
        assert result.startswith("/")
        assert result.endswith("/test/path")

    def test_no_variable(self, loader):
        """Строка без переменных остаётся без изменений."""
        result = loader._expand("plain string")
        assert result == "plain string"

    def test_non_string(self, loader):
        """Не-строки возвращаются как есть."""
        assert loader._expand(42) == 42
        assert loader._expand(3.14) == 3.14
        assert loader._expand(None) is None
        assert loader._expand(True) is True

    def test_empty_var(self, loader):
        """Неустановленная переменная заменяется на пустую строку."""
        result = loader._expand("prefix_${_NONEXISTENT_VAR_}_suffix")
        assert result == "prefix__suffix"


# ──────────────────────────────────────────────
# Тесты OllamaClient
# ──────────────────────────────────────────────

class TestOllamaClient:
    """Тестирует OllamaClient."""

    def test_init_default_url(self):
        """По умолчанию base_url = http://localhost:11434."""
        from jarvis.modules.llm import OllamaClient
        config = {"ollama": {}}
        client = OllamaClient(config)
        assert client.base_url == "http://localhost:11434"
        assert client.model == "qwen2.5:3b"
        assert client.temperature == 0.7

    def test_init_custom_url(self):
        """Можно задать кастомный URL."""
        from jarvis.modules.llm import OllamaClient
        config = {
            "ollama": {
                "base_url": "http://192.168.1.100:11434",
                "model": "llama3:8b",
                "temperature": 0.5,
            }
        }
        client = OllamaClient(config)
        assert client.base_url == "http://192.168.1.100:11434"
        assert client.model == "llama3:8b"
        assert client.temperature == 0.5

    def test_chat_success(self):
        """chat() отправляет POST и возвращает ответ."""
        from jarvis.modules.llm import OllamaClient
        config = {"ollama": {}}
        client = OllamaClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello from Ollama!"}
        }
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response) as mock_post:
            answer = client.chat("Привет")

        assert answer == "Hello from Ollama!"
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "localhost:11434" in call_url
        assert "/api/chat" in call_url
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["model"] == "qwen2.5:3b"
        # Проверяем, что сообщение пользователя есть в messages
        user_messages = [m for m in call_kwargs["json"]["messages"] if m.get("role") == "user"]
        assert any("Привет" in m.get("content", "") for m in user_messages)

    def test_chat_with_history(self):
        """chat() добавляет сообщения в историю."""
        from jarvis.modules.llm import OllamaClient
        config = {"ollama": {}}
        client = OllamaClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Hi"}}
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response):
            client.chat("First")
            client.chat("Second")

        assert len(client.history) == 4
        assert client.history[0] == {"role": "user", "content": "First"}
        assert client.history[2] == {"role": "user", "content": "Second"}

    def test_chat_error(self):
        """При ошибке HTTP возвращается сообщение об ошибке."""
        from jarvis.modules.llm import OllamaClient
        config = {"ollama": {}}
        client = OllamaClient(config)

        with patch("requests.post", side_effect=Exception("Connection refused")):
            answer = client.chat("test")

        assert "недоступна" in answer


# ──────────────────────────────────────────────
# Тесты LLMManager
# ──────────────────────────────────────────────

class TestLLMManager:
    """Тестирует LLMManager."""

    def test_init_ollama_provider(self):
        """LLMManager с провайдером ollama."""
        from jarvis.modules.llm import LLMManager
        config = {
            "provider": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "test"},
        }
        mgr = LLMManager(config)
        assert mgr.provider == "ollama"
        assert "ollama" in mgr.clients

    def test_init_unknown_provider_fallback(self):
        """Если указан неизвестный провайдер — берётся первый доступный."""
        from jarvis.modules.llm import LLMManager
        config = {
            "provider": "nonexistent",
            "ollama": {"base_url": "http://localhost:11434", "model": "test"},
        }
        mgr = LLMManager(config)
        assert mgr.primary is not None

    def test_init_with_ollama_always_works(self):
        """OllamaClient всегда создаётся, нет внешних зависимостей."""
        from jarvis.modules.llm import LLMManager
        config = {
            "provider": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "test"},
        }
        mgr = LLMManager(config)
        assert mgr.provider == "ollama"
        assert mgr.primary is not None

    def test_chat_ollama(self):
        """LLMManager.chat() делегирует вызов primary клиенту."""
        from jarvis.modules.llm import LLMManager
        config = {
            "provider": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "test"},
        }
        mgr = LLMManager(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "OK"}}
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response):
            answer = mgr.chat("hello")

        assert answer == "OK"

    def test_clear_history(self):
        """clear_history() очищает историю всех клиентов."""
        from jarvis.modules.llm import LLMManager
        config = {
            "provider": "ollama",
            "ollama": {"base_url": "http://localhost:11434", "model": "test"},
        }
        mgr = LLMManager(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "OK"}}
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response):
            mgr.chat("hello")

        assert len(mgr.clients["ollama"].history) == 2
        mgr.clear_history()
        assert len(mgr.clients["ollama"].history) == 0


# ──────────────────────────────────────────────
# Тесты других LLM-клиентов
# ──────────────────────────────────────────────

class TestAnthropicClient:
    def test_init_missing_key(self):
        """Без ANTHROPIC_API_KEY — ValueError."""
        from jarvis.modules.llm import AnthropicClient
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                AnthropicClient({"anthropic": {}})


class TestOpenRouterClient:
    def test_init_missing_key(self):
        """Без OPENROUTER_API_KEY — ValueError."""
        from jarvis.modules.llm import OpenRouterClient
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                OpenRouterClient({"openrouter": {}})


class TestKiroAIClient:
    def test_init_missing_key(self):
        """Без KIRO_API_KEY — ValueError."""
        from jarvis.modules.llm import KiroAIClient
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="KIRO_API_KEY"):
                KiroAIClient({"kiro": {}})
