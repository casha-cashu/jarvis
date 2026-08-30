"""Telegram-бот — удалённый доступ к JARVIS из мессенджера.

Тот же ResponsePipeline, что и у голоса: LLM, команды, bash-агент
(с approval gate), напоминания. Аудио не поднимается (dry_run).

Безопасность: whitelist chat_id из config.telegram.allowed_chat_ids —
чужие чаты молча игнорируются (fail-closed: пустой whitelist = никто).

Запуск: config.yaml → telegram.enabled: true + bot_token
(или переменная окружения TELEGRAM_BOT_TOKEN). CLI: jarvis telegram.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

TG_LIMIT = 4096  # лимит Telegram на сообщение
_SAFE_LIMIT = 3900  # запас под markdown/хвосты
GREETING = (
    "🤖 JARVIS на связи, сэр.\n\n"
    "Пиши запрос текстом — отвечу как голосом, только текстом.\n"
    "Команды: /status — что я могу сейчас, /help — это сообщение."
)


def resolve_token(config: dict) -> Optional[str]:
    """Токен бота: config.telegram.bot_token (без незаполненных ${}) → env."""
    tg = config.get("telegram", {})
    token = tg.get("bot_token") or ""
    if token and not token.startswith("${"):
        return token
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def is_allowed_chat(chat_id: int, allowed: list) -> bool:
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
    """Обёртка над ResponsePipeline для текстового канала Telegram."""

    def __init__(self, config: dict, config_path: str = "config.yaml"):
        self._config = config
        self._config_path = config_path
        self._jarvis: Any = None
        self._lock = asyncio.Lock()  # сериализация: один запрос за раз
        self.processed = 0

    def _ensure_pipeline(self) -> None:
        if self._jarvis is not None:
            return
        from jarvis import Jarvis  # noqa: PLC0415 — тяжёлый импорт ленивый

        self._jarvis = Jarvis(config_path=self._config_path, dry_run=True)
        self._jarvis.response.start()

    async def process(self, text: str) -> str:
        """Обрабатывает текст через общий пайплайн (LLM/команды/агент)."""
        async with self._lock:
            try:
                await asyncio.to_thread(self._ensure_pipeline)
                answer = await asyncio.to_thread(
                    self._jarvis.response.process_query, text
                )
            except Exception as e:  # noqa: BLE001 — юзеру нужен ответ, не трейс
                logger.exception("telegram: ошибка обработки")
                return f"❌ Ошибка обработки: {e}"
            self.processed += 1
            return (answer or "").strip() or "Готово, сэр."


async def run_bot(config: dict, config_path: str = "config.yaml") -> None:
    """Поднимает бота. Требует aiogram (extras: pip install -e \".[telegram]\")."""
    try:
        from aiogram import Bot, Dispatcher, F  # noqa: PLC0415
        from aiogram.filters import Command  # noqa: PLC0415
        from aiogram.types import Message  # noqa: PLC0415
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError('aiogram не установлен: pip install -e ".[telegram]"') from e

    token = resolve_token(config)
    if not token:
        raise RuntimeError(
            "Токен бота не найден: config.yaml → telegram.bot_token "
            "(или переменная окружения TELEGRAM_BOT_TOKEN). "
            "Токен выдаёт @BotFather."
        )
    allowed = list(config.get("telegram", {}).get("allowed_chat_ids", []))
    if not allowed:
        logger.warning(
            "⚠️ telegram.allowed_chat_ids пуст — бот будет игнорировать ВСЕ "
            "сообщения. Добавь свой chat_id в конфиг."
        )

    tg_cfg = config.get("telegram", {})
    assistant = TelegramAssistant(
        config, config_path=tg_cfg.get("config_path", config_path)
    )

    bot = Bot(token=token)
    dp = Dispatcher()

    def _guard(m: Message) -> bool:
        """Whitelist: чужие чаты молча игнорируются (fail-closed)."""
        return is_allowed_chat(m.chat.id, allowed)

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
        await m.answer(
            f"🤖 Обработано запросов: {assistant.processed}\n"
            f"Модель: {config.get('llm', {}).get('provider', '?')}"
        )

    @dp.message(F.text)
    async def on_text(m: Message) -> None:
        if not _guard(m):
            return
        notice = await m.answer("…")
        answer = await assistant.process(m.text)
        await notice.delete()
        # без parse_mode: ответы LLM не экранированы под HTML/Markdown
        for chunk in split_for_telegram(answer):
            await m.answer(chunk)

    logger.info("🤖 Telegram-бот запущен (whitelist: %s чат(ов))", len(allowed))
    await dp.start_polling(bot)


def main(config: dict, config_path: str = "config.yaml") -> None:
    """Точка входа для CLI: поднимает бота, ошибки — понятным текстом."""
    try:
        asyncio.run(run_bot(config, config_path))
    except RuntimeError as e:
        print(f"❌ {e}")
        raise SystemExit(1) from e
