"""Wake-word, mute/unmute и multi-turn логика.

Раньше эти ~150 строк жили в Jarvis. Здесь они чистые — без зависимости
от STT/TTS/LLM конкретных инстансов; conversation_manager оперирует
текстом, а audio/response pipelines подключаются через callbacks.

P15: убран дубль wake-word проверки в _listen_follow_up — там были две
одинаковые петли подряд (lines 466-477 в старом __init__.py).
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ConversationManager:
    """State machine: idle → wake-detected → query → follow-up loop."""

    UNMUTE_KEYWORDS = ("проснись", "джарвис", "хай")

    def __init__(
        self,
        wake_words: list[str],
        muted: bool = False,
        on_mute: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            wake_words: Wake-слова (первое — основное)
            muted: Стартовать в режиме тишины
            on_mute: Callback при входе в тишину голосом («тихо») —
                обычно ResponsePipeline.cancel_speech, чтобы заглушить
                уже играющую озвучку и очистить очередь.
        """
        if not wake_words:
            wake_words = ["джарвис"]
        self.wake_words = [w.lower() for w in wake_words]
        self.is_muted = muted
        self.on_mute = on_mute

    def mute(self) -> None:
        """Вход в режим тишины + глушение текущей озвучки."""
        self.is_muted = True
        if self.on_mute is not None:
            try:
                self.on_mute()
            except Exception as e:
                logger.warning(f"⚠️ on_mute callback failed: {e}")

    def detect_wake(self, text: str) -> tuple[bool, Optional[str]]:
        """Возвращает (wake_detected, query_after_wake_word).

        Если wake-слово найдено и после него есть текст — возвращает (True, query).
        Если wake-слово в конце фразы — (True, None) и вызывающий запросит ещё.
        Иначе (False, None).
        """
        if not text:
            return False, None
        lower = text.lower()
        for wake in self.wake_words:
            # Word-boundary match: "джарвиссимо" must NOT trigger.
            if re.search(rf"\b{re.escape(wake)}\b", lower):
                query = re.sub(
                    rf"^.*?\b{re.escape(wake)}\b\s*", "", lower, count=1
                ).strip()
                return True, (query or None)
        return False, None

    def is_unmute_phrase(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower()
        return any(w in lower for w in self.UNMUTE_KEYWORDS)

    def has_wake_in_follow_up(self, text: str) -> bool:
        """True если в follow-up прозвучало wake-слово —
        значит, multi-turn прерван и начинается новый запрос."""
        if not text:
            return False
        lower = text.lower()
        return any(w in lower for w in self.wake_words)
