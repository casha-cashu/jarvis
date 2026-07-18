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
        # Agent loop config — read from llm section
        self.agent_enabled = bool(config.get("llm", {}).get("agent_enabled", False))
        self.agent_max_iterations = int(
            config.get("llm", {}).get("agent_max_iterations", 5)
        )
        self.agent_approval_mode = config.get("llm", {}).get(
            "agent_approval_mode", "auto"
        )

    def start(self) -> None:
        if self._started:
            return

        # TTS
        from jarvis.modules.tts import TTSManager

        self.tts = TTSManager(self.config.get("tts", {}))

        # Platform (нужно ДО LLM — system_prompt подставляет platform info)
        if self.platform is None:
            from jarvis.modules.platform_adapter import PlatformAdapter

            self.platform = PlatformAdapter()

        # LLM — фигачим platform info в system_prompt
        from jarvis.modules.llm import LLMManager

        llm_cfg = dict(self.config.get("llm", {}))
        platform_str = self._platform_string()
        if "system_prompt" in llm_cfg and platform_str:
            llm_cfg["system_prompt"] = llm_cfg["system_prompt"].replace(
                "{platform}", platform_str
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
        if getattr(self.platform, "distro", None):
            s += f"/{self.platform.distro}"
        if getattr(self.platform, "de", None):
            s += f" ({self.platform.de})"
        return s

    def speak(self, text: str) -> None:
        print(f"\r🤖 {text}")
        if self.tts:
            self.tts.speak(text)

    def process_query(self, query: str) -> str:
        """commands.py first, then LLM (optionally with bash-agent loop), then default."""
        if self.commands is None:
            return ""
        cmd_resp = self.commands.process(query)
        if cmd_resp is not None:
            if cmd_resp.startswith("__"):
                return ""  # special marker — обрабатывается в conversation_manager
            return cmd_resp if cmd_resp else "Готово, сэр."

        if self.llm is None:
            return ""

        # Agent loop: if agent_enabled and LLM provider supports tools
        # (currently Ollama), use chat_with_tools → bash_agent.
        if self.agent_enabled and self._can_use_agent():
            try:
                return self._run_agent_loop(query) or ""
            except Exception as e:
                logger.error(f"❌ Agent loop failed: {e} — fallback to plain LLM")

        try:
            return self.llm.chat(query) or ""
        except Exception as e:
            logger.error(f"❌ LLM: {e}")
            return "Извините, сэр, произошла ошибка."

    def _can_use_agent(self) -> bool:
        """Returns True iff the active LLM client supports chat_with_tools."""
        if not self.llm or not self.llm.primary:
            return False
        return hasattr(self.llm.primary, "chat_with_tools")

    def _run_agent_loop(self, query: str) -> Optional[str]:
        """Invoke chat_with_tools with bash_agent's tools + approval gate.

        The approval gate is enforced here (not inside bash_agent) so that
        the safety contract is visible at the pipeline level: any tool_call
        hitting ``bash`` is checked via bash_agent.check_approval before
        execution. Block → replaced with refusal message.
        """
        from jarvis.modules import bash_agent

        client = self.llm.primary
        if client is None:
            return None

        tools = bash_agent.get_tool_schemas()

        def _on_tool_call(name: str, args: dict) -> str:
            # Special: bash tool — apply approval gate before execute_tool.
            if name == "bash":
                cmd = args.get("cmd", "")
                block_reason = bash_agent.check_approval(
                    cmd, approval_mode=self.agent_approval_mode
                )
                if block_reason:
                    return f"[BLOCKED] {block_reason}"
            return bash_agent.execute_tool(name, args)

        return client.chat_with_tools(
            query,
            tools=tools,
            on_tool_call=_on_tool_call,
            max_iterations=self.agent_max_iterations,
        )

    def stop(self) -> None:
        # TTS/LLM/CommandManager не требуют явного shutdown.
        self._started = False
