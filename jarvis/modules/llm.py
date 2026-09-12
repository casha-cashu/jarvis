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

import email.utils
import json
import os
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, cast

from filelock import FileLock

import anthropic
import requests
from requests.adapters import HTTPAdapter

try:
    # `openai` is an optional dep — the client init raises only when the
    # user actually picks provider="openai".
    import openai as _openai_mod
except ImportError:
    _openai_mod = None  # type: ignore[assignment]

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

# Межпроцессный лок: jarvis run и ui-bridge пишут один history.json.
# FileLock реентерабелен на инстанс — кэшируем по пути (путь зависит от
# JARVIS_HISTORY_FILE, который тесты патчат с перезагрузкой модуля).
_history_locks: dict = {}
_history_locks_guard = threading.Lock()


def _history_lock() -> FileLock:
    path = str(HISTORY_FILE) + ".lock"
    with _history_locks_guard:
        lock = _history_locks.get(path)
        if lock is None:
            lock = FileLock(path, timeout=10.0)
            _history_locks[path] = lock
        return lock


def _load_history_raw() -> List[Dict[str, str]]:
    """Читает файл истории. Без лока — вызывать под _history_lock()."""
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


def _save_history_raw(history: List[Dict[str, str]]) -> None:
    """Атомарная запись (tmp уникален для процесса + os.replace).
    Без лока — вызывать под _history_lock()."""
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_name(f"{HISTORY_FILE.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        tmp.replace(HISTORY_FILE)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сохранить историю диалога: {e}")

    try:
        from jarvis.modules import history_db

        history_db.save_history(history, session_id="default")
    except Exception:
        pass


def _load_history() -> List[Dict[str, str]]:
    """Загружает историю диалога с диска. Пустой список при отсутствии/ошибке."""
    with _history_lock():
        return _load_history_raw()


def _save_history(history: List[Dict[str, str]]) -> None:
    """Атомарно сохраняет историю на диск и синхронизирует с SQLite."""
    with _history_lock():
        _save_history_raw(history)


_shared_session: Optional[requests.Session] = None
_session_lock = threading.Lock()


def _get_shared_session() -> requests.Session:
    global _shared_session
    if _shared_session is None:
        with _session_lock:
            if _shared_session is None:
                s = requests.Session()
                adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
                s.mount("http://", adapter)
                s.mount("https://", adapter)
                _shared_session = s
    return _shared_session


def _http_post(session: requests.Session, *args, **kwargs):
    """Делает POST через session; если requests.post замокан в тестах — вызывает мок."""
    if hasattr(requests.post, "assert_called") or hasattr(requests.post, "mock_calls"):
        return requests.post(*args, **kwargs)
    return session.post(*args, **kwargs)


_T = TypeVar("_T")


def parse_retry_after(header_val: Optional[str], default_delay: float = 1.0) -> float:
    """Parse HTTP Retry-After header value (seconds or RFC 1123 HTTP-date)."""
    if not header_val:
        return default_delay
    val = str(header_val).strip()
    try:
        sec = float(val)
        return max(0.0, sec)
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(val)
        if dt is not None:
            now = datetime.now(dt.tzinfo)
            diff = (dt - now).total_seconds()
            return max(0.0, diff)
    except Exception:
        pass
    return default_delay


def is_rate_limit_error(exc: Exception) -> tuple[bool, Optional[float]]:
    """Determine if exception represents an HTTP 429 / Rate Limit error.

    Returns (is_rate_limit, retry_after_seconds_or_none).
    """
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if headers is None:
        headers = getattr(exc, "headers", None)

    # 1. requests.HTTPError
    if isinstance(exc, requests.HTTPError):
        if resp is not None and getattr(resp, "status_code", None) == 429:
            hdr = (
                (headers.get("Retry-After") or headers.get("retry-after"))
                if headers
                else None
            )
            return True, parse_retry_after(hdr) if hdr else None
        return False, None

    # 2. openai.RateLimitError
    if _openai_mod is not None:
        try:
            if isinstance(exc, _openai_mod.RateLimitError):
                hdr = (
                    (headers.get("retry-after") or headers.get("Retry-After"))
                    if headers
                    else None
                )
                return True, parse_retry_after(hdr) if hdr else None
        except Exception:
            pass

    # 3. anthropic.RateLimitError
    try:
        if isinstance(exc, anthropic.RateLimitError):
            hdr = (
                (headers.get("retry-after") or headers.get("Retry-After"))
                if headers
                else None
            )
            return True, parse_retry_after(hdr) if hdr else None
    except Exception:
        pass

    # 4. Status code check or type name check (covers mocked or httpx errors)
    status_code = getattr(exc, "status_code", None)
    if status_code is None and resp is not None:
        status_code = getattr(resp, "status_code", None)

    if status_code == 429 or exc.__class__.__name__ == "RateLimitError":
        hdr = (
            (headers.get("retry-after") or headers.get("Retry-After"))
            if headers
            else None
        )
        return True, parse_retry_after(hdr) if hdr else None

    return False, None


def with_rate_limit_retry(
    func: Callable[[], _T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    sleeper: Optional[Callable[[float], None]] = None,
    jitter: bool = True,
) -> _T:
    """Execute func, retrying with backoff if an HTTP 429 RateLimit error occurs."""
    actual_sleeper = sleeper if sleeper is not None else time.sleep
    attempt = 0
    while True:
        try:
            return func()
        except Exception as e:
            is_rl, retry_after = is_rate_limit_error(e)
            if not is_rl or attempt >= max_retries:
                raise

            if retry_after is not None:
                sleep_duration = min(max_delay, max(0.0, retry_after))
            else:
                backoff = min(max_delay, base_delay * (2**attempt))
                if jitter:
                    backoff = backoff * random.uniform(0.5, 1.0)
                sleep_duration = max(0.0, backoff)

            logger.warning(
                "⚠️ Rate limit (429) encountered. Retrying in %.2fs (attempt %d/%d)...",
                sleep_duration,
                attempt + 1,
                max_retries,
            )
            actual_sleeper(sleep_duration)
            attempt += 1


def _safe_truncate_history(history: list[dict], max_len: int) -> list[dict]:
    """Усекает историю до max_len, гарантируя что она начинается с user-сообщения
    без tool_result (чтобы не разорвать пары tool-call/tool-result и угодить API)."""
    if len(history) <= max_len:
        return history
    sliced = history[-max_len:]
    while sliced:
        first = sliced[0]
        role = first.get("role")
        is_tool_result = False
        if role == "user" and isinstance(first.get("content"), list):
            for block in first["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    is_tool_result = True
                    break
        if role != "user" or is_tool_result:
            sliced.pop(0)
        else:
            break
    return sliced


class LLMError(RuntimeError):
    """Raised when a provider call fails; enables manager-level fallback."""


class LLMClient(ABC):
    """Базовый класс для LLM клиентов"""

    def __init__(self, config: dict):
        self.config = config
        self.session = _get_shared_session()
        self.history = _load_history()
        self.max_history = config.get("max_history", 20)
        self.system_prompt = config.get("system_prompt", "")
        self.max_retries = int(config.get("max_retries", 3))
        self.base_delay = float(config.get("retry_base_delay", 1.0))
        self.max_delay = float(config.get("retry_max_delay", 30.0))

    def _render_system_prompt(self) -> str:
        """System prompt with live placeholders resolved per-request.

        ``{datetime}`` must stay fresh — baking it in at startup goes stale
        in long sessions, so it is substituted here on every call.
        """
        sp = self.system_prompt
        if "{datetime}" in sp:
            now = datetime.now()
            weekdays = (
                "понедельник",
                "вторник",
                "среда",
                "четверг",
                "пятница",
                "суббота",
                "воскресенье",
            )
            dt_str = f"{now.strftime('%d.%m.%Y %H:%M')}, {weekdays[now.weekday()]}"
            sp = sp.replace("{datetime}", dt_str)
        return sp

    def add_to_history(self, role: str, content: str):
        """Добавляет сообщение в историю и персистит на диск.

        Под локом история перечитывается с диска: если параллельный
        процесс (CLI + bridge) успел дописать свои ходы, они не
        затираются нашей копией. Обратная сторона: при по-настоящему
        одновременных диалогах чужой ход может вклиниться между нашими
        user/assistant — полная изоляция сессий обеспечивается архивами
        ui-history в ui_bridge; лок здесь только против потери/порчи.
        """
        with _history_lock():
            # Перезагружаем всегда: соседние same-role ходы (наш user +
            # чужой user при реальной одновременной беседе) провайдеры
            # склеивают в один ход — Anthropic это документированное
            # поведение, потерь ходов быть не должно.
            self.history = _load_history_raw()
            self.history.append({"role": role, "content": content})

            # Обрезаем историю если слишком длинная
            self.history = _safe_truncate_history(self.history, self.max_history)

            _save_history_raw(self.history)

    def _discard_pending_user(self):
        """Drop trailing user message left unanswered by a failed call.

        Without this, one network failure leaves an orphaned user entry;
        Anthropic/OpenAI then reject every following request with
        "consecutive user messages" forever.
        """
        with _history_lock():
            # Перечитываем диск и снимаем ТОЛЬКО наш осиротевший user
            # (матч по содержимому): параллельный процесс мог дописать
            # свои ходы после нашей неудачи — их затирать нельзя.
            pending = (
                self.history[-1]
                if self.history and self.history[-1].get("role") == "user"
                else None
            )
            fresh = _load_history_raw()
            if pending and fresh and fresh[-1] == pending:
                self.history = fresh[:-1]
                _save_history_raw(self.history)
            elif fresh:
                self.history = fresh

    def clear_history(self):
        """Очищает историю (в памяти и на диске)"""
        with _history_lock():
            self.history = []
            _save_history_raw(self.history)

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

        base_url = anthropic_config.get("base_url")
        if base_url:
            self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        else:
            self.client = anthropic.Anthropic(api_key=api_key)
        self.model = anthropic_config.get("model", "claude-sonnet-4-20250514")
        self.temperature = anthropic_config.get("temperature", 0.7)
        self.max_tokens = anthropic_config.get("max_tokens", 1024)
        self.timeout = anthropic_config.get("timeout", 30)

        logger.info(f"✅ Anthropic клиент: {self.model}")

    def chat(self, message: str, stream_callback=None) -> str:
        """Отправляет сообщение в Anthropic API"""
        if stream_callback is not None:
            # Anthropic-клиент пока не стримит: параметр принимается, чтобы
            # LLMManager звал всех клиентов единообразно (иначе — TypeError).
            logger.debug("Anthropic client does not support streaming — ignoring")
        try:
            self.add_to_history("user", message)

            response = with_rate_limit_retry(
                lambda: self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=self._render_system_prompt(),
                    messages=cast(Any, self.history),
                    timeout=self.timeout,
                ),
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                max_delay=self.max_delay,
            )

            # Empty or tool_use/thinking-only responses have no text block.
            answer = next(
                (
                    str(getattr(b, "text", "")).strip()
                    for b in response.content
                    if getattr(b, "type", "") == "text"
                ),
                "",
            )
            if not answer:
                # Пустой assistant-контент Anthropic отвергает на следующем
                # запросе — не отравляем историю, снимаем осиротевший user.
                self._discard_pending_user()
                return ""
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка Anthropic: {e}")
            self._discard_pending_user()
            raise LLMError(str(e)) from e

    def chat_with_tools(
        self,
        message: str,
        tools: list,
        on_tool_call=None,
        max_iterations: int = 5,
        stream_callback: Optional[Callable[[str], None]] = None,
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

            base_messages: list[dict[str, Any]] = list(self.history)
            executed_tools: list[str] = []

            for iteration in range(max_iterations):
                response = with_rate_limit_retry(
                    lambda: self.client.messages.create(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        system=self._render_system_prompt(),
                        messages=cast(Any, base_messages),
                        tools=cast(Any, anthropic_tools),
                        timeout=self.timeout,
                    ),
                    max_retries=self.max_retries,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )

                # Anthropic returns content as a list of blocks
                # (TextBlock | ToolUseBlock)
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                text_blocks = [
                    b for b in response.content if getattr(b, "type", "") == "text"
                ]
                final_text = "".join(
                    str(getattr(b, "text", "")) for b in text_blocks
                ).strip()

                if not tool_use_blocks:
                    if final_text:
                        if stream_callback is not None:
                            try:
                                stream_callback(final_text)
                            except Exception:
                                pass
                        history_content = final_text
                        if executed_tools:
                            tools_summary = "\n".join(executed_tools)
                            history_content = f"[Контекст работы инструментов:\n{tools_summary}]\n\n{final_text}"
                        self.add_to_history("assistant", history_content)
                        return final_text
                    self._discard_pending_user()
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

                    executed_tools.append(f"- {name}({args}) -> {result[:500]}...")

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
            self._discard_pending_user()
            if final_text:
                if stream_callback is not None:
                    try:
                        stream_callback(final_text)
                    except Exception:
                        pass
                history_content = final_text
                if executed_tools:
                    tools_summary = "\n".join(executed_tools)
                    history_content = f"[Контекст работы инструментов:\n{tools_summary}]\n\n{final_text}"
                self.add_to_history("assistant", history_content)
                return final_text
            return "Извините, сэр, задача потребовала слишком много шагов."

        except Exception as e:
            logger.error(f"❌ Ошибка Anthropic chat_with_tools: {e}")
            self._discard_pending_user()
            raise LLMError(str(e)) from e


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
        self.timeout = openrouter_config.get("timeout", 30)

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY не установлен")

        logger.info(f"✅ OpenRouter клиент: {self.model}")

    def chat(self, message: str, stream_callback=None) -> str:
        """Отправляет сообщение в OpenRouter"""
        if stream_callback is not None:
            logger.debug("OpenRouter client does not support streaming — ignoring")
        try:
            self.add_to_history("user", message)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
            }

            messages = []
            if self.system_prompt:
                messages.append(
                    {"role": "system", "content": self._render_system_prompt()}
                )

            messages.extend(self.history)

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            }

            def _send():
                resp = _http_post(
                    self.session,
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp

            response = with_rate_limit_retry(
                _send,
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                max_delay=self.max_delay,
            )
            data = response.json()

            answer = data["choices"][0]["message"]["content"].strip()
            if not answer:
                self._discard_pending_user()
                return ""
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка OpenRouter: {e}")
            self._discard_pending_user()
            raise LLMError(str(e)) from e


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

    def _build_messages(self) -> list[dict[str, Any]]:
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self._render_system_prompt()})
        msgs.extend(self.history)
        return msgs

    def chat(self, message: str, stream_callback=None) -> str:
        try:
            self.add_to_history("user", message)

            if stream_callback is not None:
                stream: Any = with_rate_limit_retry(
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=cast(Any, self._build_messages()),
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        stream=True,
                    ),
                    max_retries=self.max_retries,
                    base_delay=self.base_delay,
                    max_delay=self.max_delay,
                )
                parts: list[str] = []
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        parts.append(delta)
                        stream_callback(delta)
                answer = "".join(parts).strip() or "(пустой ответ)"
                self.add_to_history("assistant", answer)
                return answer

            response = with_rate_limit_retry(
                lambda: self.client.chat.completions.create(  # type: ignore[call-overload]
                    model=self.model,
                    messages=self._build_messages(),  # type: ignore[arg-type]
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                ),
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                max_delay=self.max_delay,
            )
            answer = (response.choices[0].message.content or "").strip()
            if not answer:
                self._discard_pending_user()
                return ""
            self.add_to_history("assistant", answer)
            return answer
        except Exception as e:
            logger.error(f"❌ Ошибка OpenAI: {e}")
            self._discard_pending_user()
            raise LLMError(str(e)) from e

    def chat_with_tools(
        self,
        message: str,
        tools: list,
        on_tool_call=None,
        max_iterations: int = 5,
        stream_callback=None,
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
            executed_tools: list[str] = []

            for iteration in range(max_iterations):
                tool_calls: list[dict[str, Any]] = []
                # Last allowed iteration must not stream: we need the whole
                # text even if the model keeps trying to call tools.
                can_stream = (
                    stream_callback is not None and iteration < max_iterations - 1
                )
                content_parts: list[str] = []

                if can_stream:
                    stream = with_rate_limit_retry(
                        lambda: self.client.chat.completions.create(  # type: ignore[call-overload]
                            model=self.model,
                            messages=base_messages,  # type: ignore[arg-type]
                            tools=tools,  # type: ignore[arg-type]
                            tool_choice="auto",
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                            stream=True,
                        ),
                        max_retries=self.max_retries,
                        base_delay=self.base_delay,
                        max_delay=self.max_delay,
                    )
                    tc_map: dict = {}
                    for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            content_parts.append(delta.content)
                            if stream_callback is not None:
                                stream_callback(delta.content)
                        for tcd in (delta.tool_calls if delta else None) or []:
                            slot = tc_map.setdefault(
                                tcd.index, {"id": "", "name": "", "args": ""}
                            )
                            if tcd.id:
                                slot["id"] = tcd.id
                            if tcd.function and tcd.function.name:
                                slot["name"] = tcd.function.name
                            if tcd.function and tcd.function.arguments:
                                slot["args"] += tcd.function.arguments
                    content = "".join(content_parts).strip()
                    tool_calls = [
                        {
                            "id": slot["id"] or f"call_{index}",
                            "function": {
                                "name": slot["name"],
                                "arguments": slot["args"] or "{}",
                            },
                        }
                        for index, slot in sorted(tc_map.items())
                    ]
                else:
                    response = with_rate_limit_retry(
                        lambda: self.client.chat.completions.create(  # type: ignore[call-overload]
                            model=self.model,
                            messages=base_messages,  # type: ignore[arg-type]
                            tools=tools,  # type: ignore[arg-type]
                            tool_choice="auto",
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                        ),
                        max_retries=self.max_retries,
                        base_delay=self.base_delay,
                        max_delay=self.max_delay,
                    )
                    msg = response.choices[0].message
                    content = (msg.content or "").strip()
                    raw_calls = getattr(msg, "tool_calls", None) or []
                    tool_calls = [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in raw_calls
                    ]

                if not tool_calls:
                    if content:
                        history_content = content
                        if executed_tools:
                            tools_summary = "\n".join(executed_tools)
                            history_content = f"[Контекст работы инструментов:\n{tools_summary}]\n\n{content}"
                        self.add_to_history("assistant", history_content)
                        return content
                    self._discard_pending_user()
                    return ""

                # Append the assistant message with tool_calls to the running
                # transcript. OpenAI needs both content and tool_calls fields.
                base_messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["function"]["name"],
                                    "arguments": call["function"]["arguments"],
                                },
                            }
                            for call in tool_calls
                        ],
                    }
                )

                for call in tool_calls:
                    name = call["function"]["name"]
                    raw_args = call["function"]["arguments"] or "{}"
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

                    executed_tools.append(f"- {name}({args}) -> {result[:500]}...")

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
                            "tool_call_id": call["id"],
                            "content": result,
                        }
                    )

            logger.warning(
                "OpenAI tool loop exceeded max_iterations=%d", max_iterations
            )
            self._discard_pending_user()
            if content:
                history_content = content
                if executed_tools:
                    tools_summary = "\n".join(executed_tools)
                    history_content = (
                        f"[Контекст работы инструментов:\n{tools_summary}]\n\n{content}"
                    )
                self.add_to_history("assistant", history_content)
                return content
            return "Извините, сэр, задача потребовала слишком много шагов."

        except Exception as e:
            logger.error(f"❌ Ошибка OpenAI chat_with_tools: {e}")
            self._discard_pending_user()
            raise LLMError(str(e)) from e


class OllamaClient(LLMClient):
    """Клиент для локального Ollama"""

    def __init__(self, config: dict):
        super().__init__(config)

        ollama_config = config.get("ollama", {})
        self.base_url = ollama_config.get("base_url", "http://localhost:11434")
        self.model = ollama_config.get("model", "qwen2.5:3b")
        self.temperature = ollama_config.get("temperature", 0.7)
        # 120с: локальная модель может грузиться с диска десятки секунд, а
        # не-стриминг /api/chat молчит до конца генерации — 30с убивали
        # первый запрос после холодного старта Ollama.
        self.timeout = ollama_config.get("timeout", 120)

        logger.info(f"✅ Ollama клиент: {self.model}")

    def _post_chat(self, payload: dict) -> dict:
        """Low-level POST to /api/chat. Raises requests.HTTPError on bad status."""

        def _send():
            resp = _http_post(
                self.session,
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()

        return with_rate_limit_retry(
            _send,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
        )

    def chat(self, message: str, stream_callback=None) -> str:
        """Отправляет сообщение в Ollama. Со stream_callback отдаёт дельты."""
        try:
            self.add_to_history("user", message)

            messages = []
            if self.system_prompt:
                messages.append(
                    {"role": "system", "content": self._render_system_prompt()}
                )

            messages.extend(self.history)

            if stream_callback is not None:
                answer = self._chat_stream(messages, stream_callback)
                self.add_to_history("assistant", answer)
                return answer

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.temperature},
            }

            data = self._post_chat(payload)

            answer = data["message"]["content"].strip()
            if not answer:
                self._discard_pending_user()
                return ""
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка Ollama: {e}")
            self._discard_pending_user()
            raise LLMError(str(e)) from e

    def _chat_stream(self, messages: list, stream_callback) -> str:
        """Streaming variant of /api/chat; returns the full answer."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        parts: list[str] = []
        with _http_post(
            self.session,
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("message") or {}).get("content") or ""
                if delta:
                    parts.append(delta)
                    stream_callback(delta)
                if chunk.get("done"):
                    break
        return "".join(parts).strip() or "(пустой ответ)"

    def chat_with_tools(
        self,
        message: str,
        tools: list,
        on_tool_call=None,
        max_iterations: int = 5,
        stream_callback=None,
    ) -> str:
        """LLM ↔ tools conversation loop.

        Args:
            message: User query.
            tools: OpenAI-style tool schemas (list of {type:function,
                function:{...}}). See jarvis.modules.bash_agent.get_tool_schemas().
            on_tool_call: Callable(name, arguments_dict) -> str result. Required.
            max_iterations: Safety cap to prevent infinite tool-call loops.
            stream_callback: Optional; receives content deltas of the FINAL
                text answer (tool iterations stay silent).

        Returns:
            Final assistant text response AFTER all tool calls have been
            executed and their results fed back to the LLM.
        """
        if on_tool_call is None:
            raise RuntimeError("chat_with_tools requires on_tool_call callback")
        try:
            self.add_to_history("user", message)

            base_messages: list[dict[str, Any]] = []
            if self.system_prompt:
                base_messages.append(
                    {"role": "system", "content": self._render_system_prompt()}
                )
            base_messages.extend(self.history)
            executed_tools: list[str] = []

            for iteration in range(max_iterations):
                # Last allowed iteration must not stream: we need the whole
                # text even if the model keeps trying to call tools.
                can_stream = (
                    stream_callback is not None and iteration < max_iterations - 1
                )
                parts: list[str] = []
                data: dict | None = None

                payload = {
                    "model": self.model,
                    "messages": base_messages,
                    "tools": tools,
                    "stream": can_stream,
                    "options": {"temperature": self.temperature},
                }

                if can_stream:
                    with _http_post(
                        self.session,
                        f"{self.base_url}/api/chat",
                        json=payload,
                        timeout=self.timeout,
                        stream=True,
                    ) as resp:
                        resp.raise_for_status()
                        streamed_calls: list = []
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            msg_chunk = chunk.get("message") or {}
                            delta = msg_chunk.get("content") or ""
                            if delta:
                                parts.append(delta)
                                if stream_callback is not None:
                                    stream_callback(delta)
                            for call in msg_chunk.get("tool_calls") or []:
                                streamed_calls.append(call)
                            if chunk.get("done"):
                                break
                        if streamed_calls:
                            data = {
                                "message": {
                                    "content": "".join(parts),
                                    "tool_calls": streamed_calls,
                                }
                            }
                        else:
                            data = {"message": {"content": "".join(parts)}}
                else:
                    data = self._post_chat(payload)

                msg = data.get("message", {})

                tool_calls = msg.get("tool_calls") or []
                content = (msg.get("content") or "").strip()

                if not tool_calls:
                    if content:
                        history_content = content
                        if executed_tools:
                            tools_summary = "\n".join(executed_tools)
                            history_content = f"[Контекст работы инструментов:\n{tools_summary}]\n\n{content}"
                        self.add_to_history("assistant", history_content)
                        return content
                    self._discard_pending_user()
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

                    executed_tools.append(f"- {name}({args}) -> {result[:500]}...")

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
            self._discard_pending_user()
            if content:
                history_content = content
                if executed_tools:
                    tools_summary = "\n".join(executed_tools)
                    history_content = (
                        f"[Контекст работы инструментов:\n{tools_summary}]\n\n{content}"
                    )
                self.add_to_history("assistant", history_content)
                return content
            return "Извините, сэр, задача потребовала слишком много шагов."

        except Exception as e:
            logger.error(f"❌ Ошибка Ollama chat_with_tools: {e}")
            self._discard_pending_user()
            raise LLMError(str(e)) from e


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
        self.clients: dict[str, LLMClient] = {}
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
        cache_key: str | None = None
        if use_cache:
            cache_key = f"{len(self.primary.history)}:{message.strip().lower()}"
            if cache_key in self._cache:
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
            # Пробуем fallback (без streaming). Клиент держит свою копию
            # истории — синхронизируем её с primary, иначе запрос уйдёт без
            # последних сообщений диалога.
            for name, client in self.clients.items():
                if client is self.primary:
                    continue
                try:
                    logger.info(f"🔄 Пробую fallback: {name}")
                    if hasattr(client, "history") and hasattr(self.primary, "history"):
                        client.history = list(self.primary.history)
                    response = client.chat(message)
                    break
                except Exception:
                    continue
            if response is None:
                return "Извините, сэр, все ИИ системы недоступны."

        if use_cache and response and cache_key is not None:
            self._cache[cache_key] = response
            while len(self._cache) > self._CACHE_MAXSIZE:
                self._cache.popitem(last=False)
        return response or ""

    def clear_history(self):
        """Очищает историю всех клиентов и ответный кэш."""
        for client in self.clients.values():
            client.clear_history()
        self._cache.clear()
