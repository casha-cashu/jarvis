"""
Тесты для LLM модуля (jarvis/modules/llm.py) и ConfigLoader._expand.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from jarvis.config_loader import ConfigLoader


# ──────────────────────────────────────────────
# Глобальная изоляция от реального ~/.local/share/jarvis/history.json
# Все LLM-клиенты через персист читают/пишут во временный файл, чтобы
# тесты не засоряли user state и не зависели от мусора прошлых запусков.
# ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_history_file(tmp_path, monkeypatch):
    hist = tmp_path / "history.json"
    monkeypatch.setenv("JARVIS_HISTORY_FILE", str(hist))
    # Перезагружаем модуль jarvis.modules.llm, чтобы HISTORY_FILE
    # подхватил новое значение из env.
    import importlib
    import jarvis.modules.llm as llm_mod

    importlib.reload(llm_mod)
    yield
    # Восстанавливаем оригинальный путь — следующие import'ы сессии вернутся
    # к ~/.local/share/jarvis/history.json. Тесты в принципе обычно идут в
    # одном pytest процессе, но это делает фикстуру self-contained.
    monkeypatch.delenv("JARVIS_HISTORY_FILE", raising=False)
    importlib.reload(llm_mod)


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
        d = {
            "key": "hello_${_TEST_JARVIS_VAR_}",
            "nested": {"inner": "${_TEST_JARVIS_VAR_}_end"},
        }
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
        mock_response.json.return_value = {"message": {"content": "Hello from Ollama!"}}
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
        user_messages = [
            m for m in call_kwargs["json"]["messages"] if m.get("role") == "user"
        ]
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
        """При ошибке HTTP клиент бросает LLMError (для manager-fallback)."""
        import pytest

        from jarvis.modules.llm import LLMError, OllamaClient

        config = {"ollama": {}}
        client = OllamaClient(config)

        with patch("requests.post", side_effect=Exception("Connection refused")):
            with pytest.raises(LLMError):
                client.chat("test")


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


# ──────────────────────────────────────────────
# chat_with_tools — unit tests with mocked SDK
# (covers LLM ↔ tools loop logic without real API calls)
# ──────────────────────────────────────────────


class _FakeToolCall:
    """Mimics openai's ChatCompletionMessageToolCall."""

    def __init__(self, name, args_json="{}", id_="call_x"):
        self.id = id_
        self.type = "function"
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = args_json


class _FakeAssistantMsg:
    """Mimics openai's ChatCompletionMessage."""

    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChatCompletion:
    def __init__(self, msg):
        self.choices = [MagicMock(message=msg)]


class TestOpenAIChatWithTools:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from jarvis.modules.llm import OpenAIClient

        return OpenAIClient({"openai": {"model": "gpt-4o-mini"}})

    def test_requires_on_tool_call(self, client):
        with pytest.raises(RuntimeError, match="on_tool_call"):
            client.chat_with_tools("hi", tools=[], on_tool_call=None)

    def test_no_tool_call_returns_text(self, client):
        """When LLM returns no tool_calls → final text returned."""
        msg = _FakeAssistantMsg(content="answer", tool_calls=None)
        completion = _FakeChatCompletion(msg)
        client.client = MagicMock()
        client.client.chat.completions.create.return_value = completion

        result = client.chat_with_tools(
            "test",
            tools=[],
            on_tool_call=lambda name, args: "",
            max_iterations=2,
        )
        assert result == "answer"

    def test_tool_call_executed_and_fed_back(self, client):
        """LLM calls bash(echo) → we run callback → next iteration returns text."""
        first_msg = _FakeAssistantMsg(
            content=None,
            tool_calls=[_FakeToolCall("bash", '{"cmd": "echo hi"}')],
        )
        second_msg = _FakeAssistantMsg(content="hi", tool_calls=None)
        completions = [
            _FakeChatCompletion(first_msg),
            _FakeChatCompletion(second_msg),
        ]
        client.client = MagicMock()
        client.client.chat.completions.create.side_effect = completions

        seen = []

        def on_tool(name, args):
            seen.append((name, args))
            return "hi"

        result = client.chat_with_tools(
            "test",
            tools=[{"type": "function", "function": {"name": "bash"}}],
            on_tool_call=on_tool,
            max_iterations=3,
        )
        assert result == "hi"
        assert seen == [("bash", {"cmd": "echo hi"})]
        # Verify 2 iterations: first with tool_call, second without
        assert client.client.chat.completions.create.call_count == 2

    def test_max_iterations_cap(self, client):
        """When LLM keeps calling tools forever → stop after max_iterations."""
        looping_msg = _FakeAssistantMsg(
            content=None,
            tool_calls=[_FakeToolCall("bash", '{"cmd": "ls"}')],
        )
        client.client = MagicMock()
        client.client.chat.completions.create.return_value = _FakeChatCompletion(
            looping_msg
        )

        result = client.chat_with_tools(
            "test",
            tools=[],
            on_tool_call=lambda name, args: "x",
            max_iterations=4,
        )
        # After exhausting budget, returns empty content fallback message
        assert "слишком много шагов" in result
        assert client.client.chat.completions.create.call_count == 4


class _FakeAnthropicToolUseBlock:
    def __init__(self, name, args, id_="toolu_x"):
        self.type = "tool_use"
        self.name = name
        self.input = args
        self.id = id_


class _FakeAnthropicTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, content_blocks):
        self.content = content_blocks


class TestAnthropicChatWithTools:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        from jarvis.modules.llm import AnthropicClient

        return AnthropicClient({"anthropic": {"model": "claude-3-5-sonnet"}})

    def test_requires_on_tool_call(self, client):
        with pytest.raises(RuntimeError, match="on_tool_call"):
            client.chat_with_tools("hi", tools=[], on_tool_call=None)

    def test_text_only_response(self, client):
        """Pure text response (no tool_use blocks) → returns text."""
        resp = _FakeAnthropicResponse([_FakeAnthropicTextBlock("answer")])
        client.client = MagicMock()
        client.client.messages.create.return_value = resp

        result = client.chat_with_tools(
            "test",
            tools=[],
            on_tool_call=lambda n, a: "x",
            max_iterations=2,
        )
        assert result == "answer"

    def test_tool_use_executed_and_fed_back(self, client):
        """LLM invokes bash tool → we execute → second response is text-only."""
        first = _FakeAnthropicResponse(
            [_FakeAnthropicToolUseBlock("bash", {"cmd": "echo hi"})]
        )
        second = _FakeAnthropicResponse([_FakeAnthropicTextBlock("hi")])
        client.client = MagicMock()
        client.client.messages.create.side_effect = [first, second]

        seen = []

        def on_tool(name, args):
            seen.append((name, args))
            return "hi"

        result = client.chat_with_tools(
            "test",
            tools=[
                {"type": "function", "function": {"name": "bash", "parameters": {}}}
            ],
            on_tool_call=on_tool,
            max_iterations=3,
        )
        assert result == "hi"
        assert seen == [("bash", {"cmd": "echo hi"})]
        assert client.client.messages.create.call_count == 2

    def test_schema_conversion(self, client):
        """OpenAI-style tool schema is converted to Anthropic shape."""
        resp = _FakeAnthropicResponse([_FakeAnthropicTextBlock("done")])
        client.client = MagicMock()
        client.client.messages.create.return_value = resp

        openai_schema = [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute bash command",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        client.chat_with_tools(
            "test",
            tools=openai_schema,
            on_tool_call=lambda n, a: "x",
            max_iterations=1,
        )
        # Inspect what was passed to the SDK
        call_kwargs = client.client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs
        # Anthropic shape: {name, description, input_schema}
        tool = call_kwargs["tools"][0]
        assert tool["name"] == "bash"
        assert tool["description"] == "Execute bash command"
        assert "input_schema" in tool


class TestOpenAIClient:
    def test_init_missing_key(self):
        """Без OPENAI_API_KEY — ValueError."""
        from jarvis.modules.llm import OpenAIClient

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                OpenAIClient({"openai": {}})

    def test_init_ok(self):
        """С ключом —客户端 строится."""
        from jarvis.modules.llm import OpenAIClient

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True):
            client = OpenAIClient({"openai": {"model": "gpt-4o-mini"}})
            assert client.model == "gpt-4o-mini"
            assert client.max_tokens == 1024


# ──────────────────────────────────────────────
# Тесты persistence истории диалога (~/.local/share/jarvis/history.json)
# ──────────────────────────────────────────────


class TestHistoryPersistence:
    """История загружается/сохраняется на диск, обрезается по max_history,
    переживает рестарт клиента/провайдера."""

    def _config(self, **kw):
        return {"ollama": {}, "max_history": kw.get("max_history", 20)}

    def test_history_saved_and_reloaded(self):
        """add_to_history пишет файл; новый клиент читает его при init."""
        from jarvis.modules.llm import OllamaClient, _load_history

        c1 = OllamaClient(self._config())
        c1.add_to_history("user", "привет")
        c1.add_to_history("assistant", "здравствуйте")

        # Файл реально на диске (tmp_path через autouse фикстуру)
        loaded = _load_history()
        assert len(loaded) == 2
        assert loaded[0] == {"role": "user", "content": "привет"}
        assert loaded[1] == {"role": "assistant", "content": "здравствуйте"}

        # Новый клиент — тот же файл
        c2 = OllamaClient(self._config())
        assert len(c2.history) == 2
        assert c2.history == loaded

    def test_history_clamped_by_max_history(self):
        """История > max_history обрезается до последних N сообщений."""
        from jarvis.modules.llm import OllamaClient

        c = OllamaClient(self._config(max_history=4))
        c.add_to_history("user", "1")
        c.add_to_history("assistant", "1r")
        c.add_to_history("user", "2")
        c.add_to_history("assistant", "2r")
        c.add_to_history("user", "3")  # теперь 5, обрезаем до 4
        assert len(c.history) == 4
        assert c.history[0]["content"] == "1r"  # первое выкинуто
        assert c.history[-1]["content"] == "3"

    def test_clear_history_persists(self):
        """clear_history() пишет пустой список на диск."""
        from jarvis.modules.llm import OllamaClient, _load_history

        c = OllamaClient(self._config())
        c.add_to_history("user", "x")
        c.add_to_history("assistant", "y")
        assert len(_load_history()) == 2

        c.clear_history()
        assert c.history == []
        assert _load_history() == []

    def test_corrupt_history_file_returns_empty(self):
        """Грязный JSON → пустой список, без исключений."""
        from jarvis.modules.llm import _load_history, HISTORY_FILE

        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text("{not json at all:", encoding="utf-8")
        loaded = _load_history()
        assert loaded == []

    def test_history_records_validated(self):
        """Не-dict / без role+content отфильтровываются при load."""
        from jarvis.modules.llm import _load_history, HISTORY_FILE
        import json

        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps(
                [
                    {"role": "user", "content": "ок"},
                    "garbage string",
                    {"role": "user"},  # нет content
                    {"content": "no role"},  # нет role
                    42,
                    {"role": "assistant", "content": "да"},
                ]
            ),
            encoding="utf-8",
        )
        loaded = _load_history()
        assert loaded == [
            {"role": "user", "content": "ок"},
            {"role": "assistant", "content": "да"},
        ]

    def test_provider_switch_preserves_history(self):
        """Главный UX-кейс: сменили provider — диалог не теряется."""
        from jarvis.modules.llm import OllamaClient

        c1 = OllamaClient(self._config())
        c1.add_to_history("user", "расскажи шутку")
        c1.add_to_history("assistant", "почему программисты путают Halloween")

        # Новый клиент того же (или другого) провайдера читает общий файл.
        from jarvis.modules.llm import _load_history

        loaded = _load_history()
        assert len(loaded) == 2
        assert "шутку" in loaded[0]["content"]


class TestHistoryConcurrencyAndOrphans:
    """Межпроцессный лок истории и осиротевшие user-сообщения."""

    def _config(self):
        return {"ollama": {}}

    def test_concurrent_clients_no_lost_turns(self):
        """Пять клиентов пишут одновременно — ни один ход не теряется
        (старый код: каждый перезаписывал файл своей копией)."""
        import threading

        from jarvis.modules.llm import OllamaClient, _load_history

        clients = [OllamaClient(self._config()) for _ in range(5)]

        def add_on(i):
            clients[i].add_to_history("user", f"сообщение {i}")

        threads = [threading.Thread(target=add_on, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        hist = _load_history()
        contents = {m["content"] for m in hist}
        assert contents == {f"сообщение {i}" for i in range(5)}

    def test_empty_answer_discards_pending_user(self):
        """Пустой ответ не сохраняется assistant'ом и снимает осиротевший
        user — иначе Anthropic отвергает все последующие запросы."""
        from jarvis.modules.llm import OllamaClient, _load_history

        c = OllamaClient(self._config())
        with patch.object(c, "_post_chat", return_value={"message": {"content": ""}}):
            assert c.chat("привет") == ""
        assert _load_history() == []

    def test_max_iterations_discards_pending_user(self):
        """Выход tool-loop'а по лимиту итераций не оставляет осиротевший user."""
        from jarvis.modules.llm import OllamaClient, _load_history

        c = OllamaClient(self._config())
        always_tools = MagicMock(
            return_value={
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "bash", "arguments": "{}"}}],
                }
            }
        )
        with patch.object(c, "_post_chat", always_tools):
            result = c.chat_with_tools(
                "сделай",
                tools=[],
                on_tool_call=lambda n, a: "ок",
                max_iterations=2,
            )
        assert "слишком много шагов" in result
        assert _load_history() == []
