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
from typing import Optional

logger = logging.getLogger(__name__)


class ConversationManager:
    """State machine: idle → wake-detected → query → follow-up loop."""

    UNMUTE_KEYWORDS = ("проснись", "джарвис", "хай")

    def __init__(self, wake_words: list[str], muted: bool = False):
        if not wake_words:
            wake_words = ["джарвис"]
        self.wake_words = [w.lower() for w in wake_words]
        self.is_muted = muted

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
                query = re.sub(rf"^.*?\b{re.escape(wake)}\b\s*", "", lower, count=1).strip()
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
