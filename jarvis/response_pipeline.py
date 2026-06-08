"""Response-pipeline: текст пользователя → команда / LLM → TTS.

Изолирует роутинг (commands.py → LLM → TTS) от main loop'а и audio.
Также управляет lifecycle'ом TTS/LLM/CommandManager.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ResponsePipeline:
    """Owns TTS, LLM, CommandManager — routes user text to one of them."""

    def __init__(self, config: dict, platform=None):
        self.config = config
        self.platform = platform
        self.tts = None
        self.llm = None
        self.commands = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return

        # TTS
        from jarvis.modules.tts import TTSManager
        self.tts = TTSManager(self.config.get('tts', {}))

        # Platform (нужно ДО LLM — system_prompt подставляет platform info)
        if self.platform is None:
            from jarvis.modules.platform_adapter import PlatformAdapter
            self.platform = PlatformAdapter()

        # LLM — фигачим platform info в system_prompt
        from jarvis.modules.llm import LLMManager
        llm_cfg = dict(self.config.get('llm', {}))
        platform_str = self._platform_string()
        if 'system_prompt' in llm_cfg and platform_str:
            llm_cfg['system_prompt'] = llm_cfg['system_prompt'].replace(
                '{platform}', platform_str
            )
        self.llm = LLMManager(llm_cfg)

        # Commands
        from jarvis.modules.commands import CommandManager
        self.commands = CommandManager(self.config)

        self._started = True

    def _platform_string(self) -> str:
        if not self.platform:
            return ""
        s = f"{self.platform.os}"
        if getattr(self.platform, 'distro', None):
            s += f"/{self.platform.distro}"
        if getattr(self.platform, 'de', None):
            s += f" ({self.platform.de})"
        return s

    def speak(self, text: str) -> None:
        print(f"\r🤖 {text}")
        if self.tts:
            self.tts.speak(text)

    def process_query(self, query: str) -> str:
        """commands.py first, then LLM, then default error message."""
        if self.commands is None:
            return ""
        cmd_resp = self.commands.process(query)
        if cmd_resp is not None:
            if cmd_resp.startswith('__'):
                return ""  # special marker — обрабатывается в conversation_manager
            return cmd_resp if cmd_resp else "Готово, сэр."

        if self.llm is None:
            return ""
        try:
            return self.llm.chat(query) or ""
        except Exception as e:
            logger.error(f"❌ LLM: {e}")
            return "Извините, сэр, произошла ошибка."

    def stop(self) -> None:
        # TTS/LLM/CommandManager не требуют явного shutdown.
        self._started = False
