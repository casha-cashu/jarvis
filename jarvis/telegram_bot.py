"""Telegram-бот — удалённый доступ к JARVIS из мессенджера.

Тот же ResponsePipeline, что и у голоса: LLM, команды, bash-агент
(с approval gate), напоминания. Аудио не поднимается (dry_run).
Единая экосистема сессий и моделей с десктопным GUI (ui-history).

Безопасность: whitelist chat_id из config.telegram.allowed_chat_ids —
чужие чаты молча игнорируются (fail-closed: пустой whitelist = никто).

Запуск: config.yaml → telegram.enabled: true + bot_token
(или переменная окружения TELEGRAM_BOT_TOKEN). CLI: jarvis telegram.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

TG_LIMIT = 4096  # лимит Telegram на сообщение
_SAFE_LIMIT = 3900  # запас под markdown/хвосты

GREETING = (
    "🤖 **JARVIS на связи, сэр.**\n\n"
    "Пиши запрос текстом — отвечу так же, как голосом.\n\n"
    "**Управление сессиями (как в GUI):**\n"
    "• `/sessions` — список всех чатов из десктопа\n"
    "• `/session <id>` — переключиться на нужный чат\n"
    "• `/new [имя]` — начать новый диалог\n"
    "• `/clear` — очистить текущий диалог\n\n"
    "**Модели и система:**\n"
    "• `/status` — статус системы, аптайм, память, активная модель\n"
    "• `/models` — доступные провайдеры и модели\n"
    "• `/model <provider[:model]>` — переключить модель\n"
    "• `/reminders` — список активных напоминаний\n"
    "• `/help` — это сообщение"
)


def resolve_token(config: dict) -> Optional[str]:
    """Токен бота: config.telegram.bot_token (без незаполненных ${}) → env."""
    tg = config.get("telegram", {})
    token = tg.get("bot_token") or ""
    if token and not token.startswith("${"):
        return token
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def normalize_allowed_chat_ids(raw_list: list) -> list[int]:
    """Приводит строковые/числовые ID чатов к int (включая ID супергрупп)."""
    normalized: list[int] = []
    for item in raw_list:
        try:
            normalized.append(int(item))
        except (ValueError, TypeError):
            continue
    return normalized


def is_allowed_chat(chat_id: Any, allowed: list) -> bool:
    """Fail-closed: пустой whitelist = никто не допущен."""
    return bool(allowed) and chat_id in allowed


def split_for_telegram(text: str, limit: int = _SAFE_LIMIT) -> list[str]:
    """Режет длинный ответ на куски ≤ limit по границам слов/строк."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        # приоритет: перенос строки → конец предложения → пробел
        cut = max(
            window.rfind("\n"),
            window.rfind(". "),
            window.rfind("! "),
            window.rfind("? "),
            window.rfind(" "),
        )
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest.strip())
    return [c for c in chunks if c]


class TelegramAssistant:
    """Обёртка над ResponsePipeline для Telegram с поддержкой сессий GUI."""

    def __init__(
        self,
        config: dict,
        config_path: str = "config.yaml",
        bot: Any = None,
        loop: Any = None,
        allowed_chat_ids: Optional[list[int]] = None,
    ):
        self._config = config
        self._config_path = config_path
        self._bot = bot
        self._loop = loop
        self._allowed_chat_ids = allowed_chat_ids or []
        self._jarvis: Any = None
        self._current_session: Optional[str] = None
        self._lock = asyncio.Lock()
        self.processed = 0

    @staticmethod
    def _history_dir() -> Path:
        """Общая директория сессий (та же, что и у Tauri GUI)."""
        from jarvis.modules import llm as llm_module

        d = llm_module.HISTORY_FILE.parent / "ui-history"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _all_clients(self) -> list[Any]:
        mgr = self._jarvis.response.llm if self._jarvis else None
        if not mgr:
            return []
        clients = getattr(mgr, "clients", None)
        if isinstance(clients, dict):
            return [c for c in clients.values() if c is not None]
        primary = getattr(mgr, "primary", None)
        return [primary] if primary is not None else []

    def _set_clients_history(self, hist: list[Any]) -> None:
        for client in self._all_clients():
            limit = getattr(client, "max_history", 20)
            clean = [
                m
                for m in hist
                if isinstance(m, dict) and "role" in m and "content" in m
            ]
            client.history = clean[-limit:] if len(clean) > limit else list(clean)
        mgr = self._jarvis.response.llm if self._jarvis else None
        cache = getattr(mgr, "_cache", None)
        if cache is not None:
            cache.clear()

    def _ensure_pipeline(self) -> None:
        if self._jarvis is not None:
            return
        from jarvis import Jarvis
        from jarvis.modules.reminder import ReminderManager

        self._jarvis = Jarvis(config_path=self._config_path, dry_run=True)
        self._jarvis.response.start()
        self._jarvis.commands = self._jarvis.response.commands
        self._jarvis.llm = self._jarvis.response.llm
        self._jarvis.platform = self._jarvis.response.platform

        # Подключаем ReminderManager с отправкой уведомлений в Telegram
        if self._bot and self._allowed_chat_ids:

            def _on_reminder(text: str):
                msg = f"⏰ **НАПОМИНАНИЕ:** {text}"
                for cid in self._allowed_chat_ids:
                    try:
                        target_loop = self._loop or asyncio.get_event_loop()
                        asyncio.run_coroutine_threadsafe(
                            self._bot.send_message(cid, msg), target_loop
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось доставить напоминание в TG: {e}")

            self._jarvis.reminder_mgr = ReminderManager(on_trigger=_on_reminder)
        else:
            self._jarvis.reminder_mgr = ReminderManager()

    def _resolve_marker(self, response: str) -> str:
        """Резолвит специальные маркеры команд (напоминания, mute и т.д.)."""
        if not response or not response.startswith("__"):
            return response

        if response.startswith("__REMINDER__:"):
            _, _, rest = response.partition(":")
            seconds_str, _, reminder_text = rest.partition(":")
            try:
                seconds = int(seconds_str)
                mgr = self._jarvis.reminder_mgr if self._jarvis else None
                if mgr:
                    return mgr.add(reminder_text, seconds)
            except ValueError:
                pass
            return "Не удалось установить напоминание."

        if response == "__REMINDER_LIST__":
            return self.get_reminders_text()

        if response == "__MUTE__":
            return "Хорошо, сэр. Я замолкаю."
        if response == "__UNMUTE__":
            return "Я снова слушаю, сэр."
        if response == "__DICTATE__":
            return "Режим диктовки доступен только при голосовом вводе."
        if response == "__EXIT__":
            return "Текстовая сессия продолжается."
        return ""

    # ── Сессии диалога (синхронизированы с GUI) ──────────────────────────

    def list_sessions(self) -> list[dict[str, Any]]:
        """Список сессий из ~/.local/share/jarvis/ui-history."""
        d = self._history_dir()
        sessions = []
        for p in sorted(
            d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True
        ):
            sid = p.stem
            if sid.startswith("."):
                continue
            count = 0
            snippet = "пустой чат"
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    count = len(data)
                    for m in reversed(data):
                        if isinstance(m, dict) and m.get("content"):
                            snippet = m["content"][:45].replace("\n", " ")
                            break
            except Exception:
                pass
            sessions.append(
                {
                    "id": sid,
                    "count": count,
                    "snippet": snippet,
                    "is_current": sid == self._current_session,
                }
            )
        return sessions

    def switch_session(self, sid: str) -> bool:
        """Переключает активный диалог на существующую сессию."""
        from jarvis.modules import llm as llm_module

        self._ensure_pipeline()
        d = self._history_dir()

        # 1. Сохраняем текущий контекст
        if self._current_session:
            cur_path = d / f"{self._current_session}.json"
            cur_hist = llm_module._load_history()
            tmp = cur_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(cur_hist, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(cur_path)

        # 2. Загружаем целевую сессию
        target_path = d / f"{sid}.json"
        if not target_path.exists():
            return False

        try:
            hist = json.loads(target_path.read_text(encoding="utf-8"))
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []

        llm_module._save_history(hist)
        self._set_clients_history(hist)
        self._current_session = sid
        return True

    def create_new_session(self, name: Optional[str] = None) -> str:
        """Создает новую сессию диалога."""
        from jarvis.modules import llm as llm_module

        self._ensure_pipeline()
        d = self._history_dir()

        # Сохраняем текущую если была
        if self._current_session:
            cur_path = d / f"{self._current_session}.json"
            cur_hist = llm_module._load_history()
            tmp = cur_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(cur_hist, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(cur_path)

        clean_name = re.sub(r"[^A-Za-z0-9_-]", "_", name or "").strip("_")
        sid = (
            f"{clean_name}-{int(time.time())}"
            if clean_name
            else f"chat-{int(time.time())}"
        )

        llm_module._save_history([])
        self._set_clients_history([])
        self._current_session = sid

        target_path = d / f"{sid}.json"
        target_path.write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")
        return sid

    def clear_current_session(self) -> None:
        """Очищает контекст текущей сессии."""
        from jarvis.modules import llm as llm_module

        self._ensure_pipeline()
        llm_module._save_history([])
        self._set_clients_history([])
        if self._current_session:
            target_path = self._history_dir() / f"{self._current_session}.json"
            target_path.write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")

    # ── Модели и статус ──────────────────────────────────────────────────

    def get_providers_info(self) -> dict[str, Any]:
        self._ensure_pipeline()
        llm_cfg = self._jarvis.config.get("llm", {})
        active = llm_cfg.get("provider", "ollama")
        providers = {
            "ollama": llm_cfg.get("ollama", {}).get("model", "qwen2.5:3b"),
            "openai": llm_cfg.get("openai", {}).get("model", "gpt-4o-mini"),
            "anthropic": llm_cfg.get("anthropic", {}).get(
                "model", "claude-3-5-sonnet-20241022"
            ),
            "openrouter": llm_cfg.get("openrouter", {}).get(
                "model", "anthropic/claude-3.5-sonnet"
            ),
        }
        return {
            "active_provider": active,
            "active_model": providers.get(active, "неизвестно"),
            "providers": providers,
            "agent_enabled": bool(self._jarvis.response.agent_enabled),
            "approval_mode": self._jarvis.response.agent_approval_mode,
        }

    def set_provider_model(self, target: str) -> str:
        """Переключает провайдера/модель (формат: 'anthropic' или 'ollama:qwen2.5:7b')."""
        self._ensure_pipeline()
        from jarvis.modules.llm import LLMManager
        from jarvis.prompt_builder import compose_system_prompt

        parts = target.strip().split(":", 1)
        provider = parts[0].lower()

        allowed = ("ollama", "openai", "anthropic", "openrouter")
        if provider not in allowed:
            return f"❌ Неизвестный провайдер '{provider}'. Допустимые: {', '.join(allowed)}"

        llm_cfg = self._jarvis.config["llm"]
        llm_cfg["provider"] = provider
        if len(parts) > 1 and parts[1].strip():
            llm_cfg.setdefault(provider, {})["model"] = parts[1].strip()

        llm_cfg["system_prompt"] = compose_system_prompt(
            llm_cfg.get("system_prompt"),
            self._jarvis.response.agent_enabled,
            tools_prompt=llm_cfg.get("system_prompt_tools"),
            platform_str=self._jarvis.response._platform_string(),
        )

        self._jarvis.response.llm = LLMManager(llm_cfg)
        curr_model = llm_cfg.get(provider, {}).get("model", "?")
        return f"✅ Переключено на **{provider}** (модель: `{curr_model}`)."

    def get_system_status(self) -> str:
        self._ensure_pipeline()
        info = self.get_providers_info()
        sessions = self.list_sessions()
        curr_sid = self._current_session or "активная сессия"

        lines = [
            "🤖 **Системный статус JARVIS**",
            f"• Активная сессия: `{curr_sid}`",
            f"• Сохранённых чатов GUI: {len(sessions)}",
            f"• Запросов обработано: {self.processed}",
            f"• Провайдер LLM: **{info['active_provider']}** (`{info['active_model']}`)",
            f"• Bash-агент: {'Включён' if info['agent_enabled'] else 'Выключен'} (режим: `{info['approval_mode']}`)",
        ]

        if os.path.exists("/proc/uptime"):
            try:
                with open("/proc/uptime", "r", encoding="utf-8") as f:
                    up_s = int(float(f.readline().split()[0]))
                lines.append(f"• Аптайм системы: {str(timedelta(seconds=up_s))}")
            except Exception:
                pass

        return "\n".join(lines)

    def get_reminders_text(self) -> str:
        self._ensure_pipeline()
        from jarvis.modules.reminder import ReminderManager

        reminders = ReminderManager.list_active()
        if not reminders:
            return "Нет активных напоминаний."
        lines = [f"• «{t}» — через {s} сек" for t, s in reminders]
        return "⏰ **Активные напоминания:**\n" + "\n".join(lines)

    # ── Обработка сообщений ──────────────────────────────────────────────

    async def process(
        self,
        text: str,
        on_tool: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """Обрабатывает текст через ResponsePipeline с уведомлением о tool calls."""
        async with self._lock:
            try:
                await asyncio.to_thread(self._ensure_pipeline)

                cmd_resp = None
                if getattr(self._jarvis, "commands", None):
                    cmd_resp = await asyncio.to_thread(
                        self._jarvis.commands.process, text
                    )

                if cmd_resp and cmd_resp.startswith("__"):
                    answer = self._resolve_marker(cmd_resp)
                elif cmd_resp is not None:
                    answer = cmd_resp
                else:

                    def _tool_call(name: str, args: dict) -> None:
                        if on_tool and self._loop:
                            cmd = args.get("cmd") or args.get("path") or ""
                            notice = f"🔧 [tool: {name}] {cmd}"
                            asyncio.run_coroutine_threadsafe(
                                on_tool(notice), self._loop
                            )

                    answer = await asyncio.to_thread(
                        self._jarvis.response.process_query,
                        text,
                        tool_callback=_tool_call,
                    )
                    answer = self._resolve_marker(answer)
            except Exception as e:
                logger.exception("telegram: ошибка обработки")
                return f"❌ Ошибка обработки: {e}"
            self.processed += 1
            return (answer or "").strip() or "Готово, сэр."


async def run_bot(config: dict, config_path: str = "config.yaml") -> None:
    """Поднимает бота. Требует aiogram (extras: pip install -e \".[telegram]\")."""
    try:
        from aiogram import Bot, Dispatcher, F
        from aiogram.filters import Command
        from aiogram.types import Message
    except ImportError as e:
        raise RuntimeError('aiogram не установлен: pip install -e ".[telegram]"') from e

    token = resolve_token(config)
    if not token:
        raise RuntimeError(
            "Токен бота не найден: config.yaml → telegram.bot_token "
            "(или переменная окружения TELEGRAM_BOT_TOKEN). "
            "Токен выдаёт @BotFather."
        )

    raw_allowed = list(config.get("telegram", {}).get("allowed_chat_ids", []))
    allowed_ids = normalize_allowed_chat_ids(raw_allowed)
    if not allowed_ids:
        logger.warning(
            "⚠️ telegram.allowed_chat_ids пуст — бот будет игнорировать ВСЕ "
            "сообщения. Добавь свой chat_id в конфиг."
        )

    tg_cfg = config.get("telegram", {})
    loop = asyncio.get_running_loop()
    bot = Bot(token=token)

    assistant = TelegramAssistant(
        config,
        config_path=tg_cfg.get("config_path", config_path),
        bot=bot,
        loop=loop,
        allowed_chat_ids=allowed_ids,
    )

    dp = Dispatcher()

    def _guard(m: Message) -> bool:
        """Whitelist: чужие чаты молча игнорируются (fail-closed)."""
        return is_allowed_chat(m.chat.id, allowed_ids)

    @dp.message(Command("start"))
    async def cmd_start(m: Message) -> None:
        if not _guard(m):
            return
        await m.answer(GREETING)

    @dp.message(Command("help"))
    async def cmd_help(m: Message) -> None:
        if not _guard(m):
            return
        await m.answer(GREETING)

    @dp.message(Command("status"))
    async def cmd_status(m: Message) -> None:
        if not _guard(m):
            return
        async with assistant._lock:
            status = await asyncio.to_thread(assistant.get_system_status)
        await m.answer(status)

    @dp.message(Command("sessions"))
    async def cmd_sessions(m: Message) -> None:
        if not _guard(m):
            return
        async with assistant._lock:
            sessions = await asyncio.to_thread(assistant.list_sessions)
        if not sessions:
            await m.answer("📭 Нет сохранённых сессий диалогов.")
            return
        lines = ["📁 **Сессии приложения:**"]
        for s in sessions[:15]:
            mark = "⭐ " if s["is_current"] else "• "
            lines.append(f"{mark}`{s['id']}` ({s['count']} сообщ.) — _{s['snippet']}_")
        lines.append("\nПереключить: `/session <id>` | Новый: `/new [имя]`")
        await m.answer("\n".join(lines))

    @dp.message(Command("session"))
    async def cmd_session(m: Message) -> None:
        if not _guard(m):
            return
        parts = (m.text or "").strip().split(maxsplit=1)
        if len(parts) < 2:
            await m.answer("Укажи ID сессии: `/session <id>` (список: `/sessions`).")
            return
        sid = parts[1].strip()
        async with assistant._lock:
            ok = await asyncio.to_thread(assistant.switch_session, sid)
        if ok:
            await m.answer(f"✅ Переключено на сессию `{sid}`.")
        else:
            await m.answer(f"❌ Сессия `{sid}` не найдена.")

    @dp.message(Command("new"))
    async def cmd_new(m: Message) -> None:
        if not _guard(m):
            return
        parts = (m.text or "").strip().split(maxsplit=1)
        name = parts[1].strip() if len(parts) > 1 else None
        async with assistant._lock:
            sid = await asyncio.to_thread(assistant.create_new_session, name)
        await m.answer(f"✨ Создана новая сессия: `{sid}`. Контекст диалога чист.")

    @dp.message(Command("clear"))
    async def cmd_clear(m: Message) -> None:
        if not _guard(m):
            return
        async with assistant._lock:
            await asyncio.to_thread(assistant.clear_current_session)
        await m.answer("🧹 Контекст текущего диалога очищен.")

    @dp.message(Command("models"))
    async def cmd_models(m: Message) -> None:
        if not _guard(m):
            return
        async with assistant._lock:
            info = await asyncio.to_thread(assistant.get_providers_info)
        lines = ["🧠 **Настроенные LLM-провайдеры:**"]
        for p, model in info["providers"].items():
            mark = "👉 " if p == info["active_provider"] else "• "
            lines.append(f"{mark}**{p}**: `{model}`")
        lines.append("\nСменить: `/model <provider>` или `/model <provider:model>`")
        await m.answer("\n".join(lines))

    @dp.message(Command("model"))
    async def cmd_model(m: Message) -> None:
        if not _guard(m):
            return
        parts = (m.text or "").strip().split(maxsplit=1)
        if len(parts) < 2:
            async with assistant._lock:
                info = await asyncio.to_thread(assistant.get_providers_info)
            await m.answer(
                f"Текущая модель: **{info['active_provider']}** (`{info['active_model']}`).\n"
                "Сменить: `/model <provider>` (напр. `/model openai` или `/model ollama:llama3`)."
            )
            return
        target = parts[1].strip()
        async with assistant._lock:
            result = await asyncio.to_thread(assistant.set_provider_model, target)
        await m.answer(result)

    @dp.message(Command("reminders"))
    async def cmd_reminders(m: Message) -> None:
        if not _guard(m):
            return
        async with assistant._lock:
            text = await asyncio.to_thread(assistant.get_reminders_text)
        await m.answer(text)

    @dp.message(F.text)
    async def on_text(m: Message) -> None:
        if not _guard(m):
            return

        if assistant._lock.locked():
            await m.answer(
                "⏳ JARVIS занят выполнением предыдущего запроса, ожидайте..."
            )

        notice = await m.answer("…")

        async def _notify_tool(tool_text: str):
            try:
                await m.answer(tool_text)
            except Exception:
                pass

        answer = await assistant.process(m.text or "", on_tool=_notify_tool)

        try:
            await notice.delete()
        except Exception:
            pass

        for chunk in split_for_telegram(answer):
            try:
                await m.answer(chunk)
            except Exception as e:
                logger.warning(f"Ошибка отправки чанка Telegram: {e}")
                try:
                    await m.answer(chunk, parse_mode=None)
                except Exception:
                    pass

    logger.info("🤖 Telegram-бот запущен (whitelist: %s чат(ов))", len(allowed_ids))
    await dp.start_polling(bot)


def main(config: dict, config_path: str = "config.yaml") -> None:
    """Точка входа для CLI: поднимает бота, ошибки — понятным текстом."""
    try:
        asyncio.run(run_bot(config, config_path))
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Telegram-бот остановлен")
    except RuntimeError as e:
        print(f"❌ {e}")
        raise SystemExit(1) from e
