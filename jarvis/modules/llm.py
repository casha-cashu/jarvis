#!/usr/bin/env python3
"""
LLM module for dialogue.

Supported providers:
  - Ollama (local, with native tool calling)
  - OpenAI (with Responses / chat.completions tool calling)
  - Anthropic Claude (with native tool calling)
  - OpenRouter (OpenAI-compatible aggregator, plain chat only)

Kiro was removed — it requires Omniroute which isn't publicly available.
"""

import json
import os
import logging
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import List, Dict
import anthropic
import requests

try:
    # `openai` is an optional dep — the client init raises only when the
    # user actually picks provider="openai".
    import openai as _openai_mod
except ImportError:
    _openai_mod = None

logger = logging.getLogger(__name__)


# ── Persistence ────────────────────────────────────────────────────────────
# История диалога живёт в ~/.local/share/jarvis/history.json. Переключение
# провайдера (ollama → openai → …) сохраняет общий контекст — каждый новый
# LLMClient читает тот же файл при старте. Файл атомарно перезаписывается
# через temp+rename, чтобы конкурентные записи не разорвали его.

HISTORY_FILE = Path(
    os.environ.get("JARVIS_HISTORY_FILE")
    or os.path.expanduser("~/.local/share/jarvis/history.json")
)


def _load_history() -> List[Dict[str, str]]:
    """Загружает историю диалога с диска. Пустой список при отсутствии/ошибке."""
    try:
        if not HISTORY_FILE.exists():
            return []
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # Грубая sanity-проверка структуры (role+content).
            return [
                m
                for m in data
                if isinstance(m, dict) and "role" in m and "content" in m
            ]
        return []
    except Exception as e:
        logger.warning(f"⚠️ Не удалось загрузить историю диалога: {e}")
        return []


def _save_history(history: List[Dict[str, str]]) -> None:
    """Атомарно сохраняет историю на диск."""
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp, HISTORY_FILE)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сохранить историю диалога: {e}")


class LLMClient(ABC):
    """Базовый класс для LLM клиентов"""

    def __init__(self, config: dict):
        self.config = config
        self.history = _load_history()
        self.max_history = config.get("max_history", 20)
        self.system_prompt = config.get("system_prompt", "")

    def add_to_history(self, role: str, content: str):
        """Добавляет сообщение в историю и персистит на диск."""
        self.history.append({"role": role, "content": content})

        # Обрезаем историю если слишком длинная
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

        _save_history(self.history)

    def clear_history(self):
        """Очищает историю (в памяти и на диске)"""
        self.history = []
        _save_history(self.history)

    @abstractmethod
    def chat(self, message: str) -> str:
        """Отправляет сообщение и получает ответ"""


class AnthropicClient(LLMClient):
    """Клиент для Anthropic API (прямой) с поддержкой tool calling."""

    def __init__(self, config: dict):
        super().__init__(config)

        anthropic_config = config.get("anthropic", {}) or {}
        api_key = os.getenv("ANTHROPIC_API_KEY") or anthropic_config.get("api_key")

        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY не установлен")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = anthropic_config.get("model", "claude-3-5-sonnet-20241022")
        self.temperature = anthropic_config.get("temperature", 0.7)
        self.max_tokens = anthropic_config.get("max_tokens", 1024)
        self.timeout = anthropic_config.get("timeout", 30)

        logger.info(f"✅ Anthropic клиент: {self.model}")

    def chat(self, message: str) -> str:
        """Отправляет сообщение в Anthropic API"""
        try:
            self.add_to_history("user", message)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self.system_prompt,
                messages=self.history,
                timeout=self.timeout,
            )

            answer = response.content[0].text.strip()
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка Anthropic: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."

    def chat_with_tools(
        self,
        message: str,
        tools: list,
        on_tool_call=None,
        max_iterations: int = 5,
    ) -> str:
        """LLM ↔ tools loop via Anthropic's native tools API.

        Anthropic schema differs from OpenAI: ``tools`` is a list of
        ``{name, description, input_schema}`` (NOT ``{type, function}``).
        We perform the conversion on the fly from the OpenAI-style schemas
        produced by bash_agent.get_tool_schemas().
        """
        if on_tool_call is None:
            raise RuntimeError("chat_with_tools requires on_tool_call callback")
        try:
            self.add_to_history("user", message)

            # Convert OpenAI tool schema → Anthropic schema
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", t)
                anthropic_tools.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object"}),
                    }
                )

            base_messages = list(self.history)

            for iteration in range(max_iterations):
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=self.system_prompt,
                    messages=base_messages,
                    tools=anthropic_tools,
                    timeout=self.timeout,
                )

                # Anthropic returns content as a list of blocks
                # (TextBlock | ToolUseBlock)
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                text_blocks = [b for b in response.content if b.type == "text"]
                final_text = "".join(b.text for b in text_blocks).strip()

                if not tool_use_blocks:
                    if final_text:
                        self.add_to_history("assistant", final_text)
                        return final_text
                    return ""

                # Append the assistant message verbatim (content blocks as-is)
                base_messages.append({"role": "assistant", "content": response.content})

                # Execute each tool call and feed back via user-role tool_result
                tool_results = []
                for block in tool_use_blocks:
                    name = block.name
                    args = block.input or {}
                    try:
                        result = str(on_tool_call(name, args))
                    except Exception as e:
                        result = f"[tool error: {e}]"
                    logger.debug(
                        "anthropic tool_call iter=%d name=%s args=%s -> %s",
                        iteration,
                        name,
                        args,
                        result[:120],
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
                base_messages.append({"role": "user", "content": tool_results})

            logger.warning(
                "Anthropic tool loop exceeded max_iterations=%d", max_iterations
            )
            return (
                final_text
                if final_text
                else "Извините, сэр, задача потребовала слишком много шагов."
            )

        except Exception as e:
            logger.error(f"❌ Ошибка Anthropic chat_with_tools: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."


class OpenRouterClient(LLMClient):
    """Клиент для OpenRouter"""

    def __init__(self, config: dict):
        super().__init__(config)

        openrouter_config = config.get("openrouter", {})
        self.api_key = os.getenv("OPENROUTER_API_KEY") or openrouter_config.get(
            "api_key"
        )
        self.model = openrouter_config.get("model", "anthropic/claude-3.5-sonnet")
        self.temperature = openrouter_config.get("temperature", 0.7)

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY не установлен")

        logger.info(f"✅ OpenRouter клиент: {self.model}")

    def chat(self, message: str) -> str:
        """Отправляет сообщение в OpenRouter"""
        try:
            self.add_to_history("user", message)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
            }

            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})

            messages.extend(self.history)

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            }

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()
            data = response.json()

            answer = data["choices"][0]["message"]["content"].strip()
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка OpenRouter: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."


class OpenAIClient(LLMClient):
    """Native OpenAI client with tool calling support.

    Uses the OpenAI Python SDK (`openai>=1.40`). Supports ``chat_with_tools``
    via the standard ``tools`` parameter of ``chat.completions.create`` —
    the same wire format as bash_agent.get_tool_schemas() returns, so we
    pass them through verbatim.
    """

    def __init__(self, config: dict):
        super().__init__(config)

        if _openai_mod is None:
            raise RuntimeError(
                "openai package not installed — run `pip install openai>=1.40`"
            )

        openai_cfg = config.get("openai", {}) or {}
        api_key = os.getenv("OPENAI_API_KEY") or openai_cfg.get("api_key")
        if not api_key:
            raise ValueError("OPENAI_API_KEY не установлен")

        self.client = _openai_mod.OpenAI(
            api_key=api_key,
            base_url=openai_cfg.get("base_url"),
            timeout=openai_cfg.get("timeout", 30),
        )
        self.model = openai_cfg.get("model", "gpt-4o-mini")
        self.temperature = openai_cfg.get("temperature", 0.7)
        self.max_tokens = openai_cfg.get("max_tokens", 1024)

        logger.info(f"✅ OpenAI клиент: {self.model}")

    def _build_messages(self) -> list:
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.history)
        return msgs

    def chat(self, message: str) -> str:
        try:
            self.add_to_history("user", message)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            answer = (response.choices[0].message.content or "").strip()
            self.add_to_history("assistant", answer)
            return answer
        except Exception as e:
            logger.error(f"❌ Ошибка OpenAI: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."

    def chat_with_tools(
        self,
        message: str,
        tools: list,
        on_tool_call=None,
        max_iterations: int = 5,
    ) -> str:
        """LLM ↔ tools loop via OpenAI chat.completions with ``tools``.

        ``tools`` schemas are OpenAI-shaped already — passed verbatim.
        The ``tool_call`` response is a list of ``response.choices[0].message.tool_calls``,
        each with ``id``, ``function.name``, ``function.arguments`` (JSON string).
        We feed back results as ``role: "tool"`` messages with ``tool_call_id``.
        """
        if on_tool_call is None:
            raise RuntimeError("chat_with_tools requires on_tool_call callback")
        try:
            self.add_to_history("user", message)
            base_messages = self._build_messages()

            for iteration in range(max_iterations):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=base_messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                msg = response.choices[0].message
                content = (msg.content or "").strip()

                tool_calls = getattr(msg, "tool_calls", None) or []
                if not tool_calls:
                    if content:
                        self.add_to_history("assistant", content)
                        return content
                    return ""

                # Append the assistant message with tool_calls to the running
                # transcript. OpenAI needs both content and tool_calls fields.
                base_messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )

                for tc in tool_calls:
                    name = tc.function.name
                    raw_args = tc.function.arguments or "{}"
                    try:
                        args = (
                            json.loads(raw_args)
                            if isinstance(raw_args, str)
                            else raw_args
                        )
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = str(on_tool_call(name, args))
                    except Exception as e:
                        result = f"[tool error: {e}]"
                    logger.debug(
                        "openai tool_call iter=%d name=%s args=%s -> %s",
                        iteration,
                        name,
                        args,
                        result[:120],
                    )
                    base_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )

            logger.warning(
                "OpenAI tool loop exceeded max_iterations=%d", max_iterations
            )
            return (
                content
                if content
                else "Извините, сэр, задача потребовала слишком много шагов."
            )

        except Exception as e:
            logger.error(f"❌ Ошибка OpenAI chat_with_tools: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."


class OllamaClient(LLMClient):
    """Клиент для локального Ollama"""

    def __init__(self, config: dict):
        super().__init__(config)

        ollama_config = config.get("ollama", {})
        self.base_url = ollama_config.get("base_url", "http://localhost:11434")
        self.model = ollama_config.get("model", "qwen2.5:3b")
        self.temperature = ollama_config.get("temperature", 0.7)
        self.timeout = ollama_config.get("timeout", 30)

        logger.info(f"✅ Ollama клиент: {self.model}")

    def _post_chat(self, payload: dict) -> dict:
        """Low-level POST to /api/chat. Raises requests.HTTPError on bad status."""
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def chat(self, message: str) -> str:
        """Отправляет сообщение в Ollama"""
        try:
            self.add_to_history("user", message)

            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})

            messages.extend(self.history)

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.temperature},
            }

            data = self._post_chat(payload)

            answer = data["message"]["content"].strip()
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка Ollama: {e}")
            return "Извините, сэр, локальная модель недоступна."

    def chat_with_tools(
        self,
        message: str,
        tools: list,
        on_tool_call=None,
        max_iterations: int = 5,
    ) -> str:
        """LLM ↔ tools conversation loop.

        Args:
            message: User query.
            tools: OpenAI-style tool schemas (list of {type:function,
                function:{...}}). See jarvis.modules.bash_agent.get_tool_schemas().
            on_tool_call: Callable(name, arguments_dict) -> str result. Required.
            max_iterations: Safety cap to prevent infinite tool-call loops.

        Returns:
            Final assistant text response AFTER all tool calls have been
            executed and their results fed back to the LLM.
        """
        if on_tool_call is None:
            raise RuntimeError("chat_with_tools requires on_tool_call callback")
        try:
            self.add_to_history("user", message)

            base_messages = []
            if self.system_prompt:
                base_messages.append({"role": "system", "content": self.system_prompt})
            base_messages.extend(self.history)

            for iteration in range(max_iterations):
                payload = {
                    "model": self.model,
                    "messages": base_messages,
                    "tools": tools,
                    "stream": False,
                    "options": {"temperature": self.temperature},
                }
                data = self._post_chat(payload)
                msg = data.get("message", {})

                tool_calls = msg.get("tool_calls") or []
                content = (msg.get("content") or "").strip()

                if not tool_calls:
                    if content:
                        self.add_to_history("assistant", content)
                        return content
                    return ""

                # Append the assistant's tool-call message to the running
                # transcript so Ollama sees its own prior call.
                base_messages.append(
                    {"role": "assistant", "content": content, "tool_calls": tool_calls}
                )

                # Execute each tool call and feed back results
                for call in tool_calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args = {}
                    else:
                        args = raw_args or {}

                    try:
                        result = str(on_tool_call(name, args))
                    except Exception as e:
                        result = f"[tool error: {e}]"

                    logger.debug(
                        "ollama tool_call iter=%d name=%s args=%s -> %s",
                        iteration,
                        name,
                        args,
                        result[:120],
                    )
                    base_messages.append({"role": "tool", "content": result})

            logger.warning(
                "Ollama tool loop exceeded max_iterations=%d", max_iterations
            )
            return (
                content
                if content
                else "Извините, сэр, задача потребовала слишком много шагов."
            )

        except Exception as e:
            logger.error(f"❌ Ошибка Ollama chat_with_tools: {e}")
            return "Извините, сэр, локальная модель недоступна."


class LLMManager:
    """Менеджер LLM с автоматическим fallback и LRU-кэшем повторных запросов."""

    # P9: для streaming запросов кэш бессмыслен (callback увидит частичные
    # токены ОДИН раз), поэтому ключ — только текст. История разговора
    # на ответ влияет, но для часто повторяющихся «как тебя зовут» / «какой
    # сейчас час» кэш экономит API-вызовы. Если важна точность контекста,
    # вызывающий код может игнорировать кэш через ``cached=False``.
    _CACHE_MAXSIZE = 128

    def __init__(self, config: dict):
        """
        Args:
            config: Словарь с настройками из config.yaml['llm']
        """
        self.config = config
        self.provider = config.get("provider", "ollama")
        self.clients = {}
        self._cache: "OrderedDict[str, str]" = OrderedDict()

        # Инициализируем клиенты
        self._init_clients()

        # Выбираем основной
        self.primary = self.clients.get(self.provider)
        if not self.primary:
            logger.error(f"❌ Провайдер '{self.provider}' недоступен")
            # Берём первый доступный
            if self.clients:
                self.primary = list(self.clients.values())[0]
                logger.info(f"✅ Используется fallback: {list(self.clients.keys())[0]}")

    def _init_clients(self):
        """Инициализирует доступные клиенты"""
        # Ollama — всегда доступен по умолчанию (локально)
        try:
            self.clients["ollama"] = OllamaClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ Ollama недоступен: {e}")

        # OpenAI (нативный)
        try:
            if self.config.get("openai", {}).get("api_key") or os.getenv(
                "OPENAI_API_KEY"
            ):
                self.clients["openai"] = OpenAIClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ OpenAI недоступен: {e}")

        # Anthropic
        try:
            if self.config.get("anthropic", {}).get("api_key") or os.getenv(
                "ANTHROPIC_API_KEY"
            ):
                self.clients["anthropic"] = AnthropicClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ Anthropic недоступен: {e}")

        # OpenRouter (OpenAI-compatible aggregator)
        try:
            if self.config.get("openrouter", {}).get("api_key") or os.getenv(
                "OPENROUTER_API_KEY"
            ):
                self.clients["openrouter"] = OpenRouterClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ OpenRouter недоступен: {e}")

        if not self.clients:
            raise RuntimeError("❌ Ни один LLM провайдер не доступен")

    def chat(self, message: str, stream_callback=None, cached: bool = True) -> str:
        """
        Отправляет сообщение в LLM

        Args:
            message: Сообщение пользователя
            stream_callback: Функция для streaming (опционально)
            cached: использовать ли LRU-кэш для повторных вопросов (по умолч. да).
                Авто-выключается при streaming — там кэш сломал бы UX.

        Returns:
            Ответ LLM
        """
        if not self.primary:
            return "Извините, сэр, ИИ недоступен."

        # Streaming кэшу не подлежит — callback должен видеть токены.
        use_cache = cached and stream_callback is None
        cache_key = message.strip().lower() if use_cache else None

        if use_cache and cache_key in self._cache:
            # LRU touch
            self._cache.move_to_end(cache_key)
            logger.debug(f"💾 LLM cache hit: {cache_key[:40]}")
            return self._cache[cache_key]

        try:
            kwargs = {}
            if stream_callback is not None:
                kwargs["stream_callback"] = stream_callback
            response = self.primary.chat(message, **kwargs)
        except Exception as e:
            logger.error(f"❌ Ошибка LLM: {e}")
            response = None
            # Пробуем fallback (без streaming)
            for name, client in self.clients.items():
                if client is self.primary:
                    continue
                try:
                    logger.info(f"🔄 Пробую fallback: {name}")
                    response = client.chat(message)
                    break
                except Exception:
                    continue
            if response is None:
                return "Извините, сэр, все ИИ системы недоступны."

        if use_cache and response:
            self._cache[cache_key] = response
            while len(self._cache) > self._CACHE_MAXSIZE:
                self._cache.popitem(last=False)
        return response

    def clear_history(self):
        """Очищает историю всех клиентов"""
        for client in self.clients.values():
            client.clear_history()
