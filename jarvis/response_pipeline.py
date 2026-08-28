"""Response-pipeline: текст пользователя → команда / LLM → TTS.

Изолирует роутинг (commands.py → LLM → TTS) от main loop'а и audio.
Также управляет lifecycle'ом TTS/LLM/CommandManager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from jarvis.modules.tts import TTSWorker

logger = logging.getLogger(__name__)


class ResponsePipeline:
    """Owns TTS, LLM, CommandManager — routes user text to one of them."""

    def __init__(self, config: dict, platform=None, tts_worker: "TTSWorker" = None):
        self.config = config
        self.platform = platform
        self.tts = None
        # Фоновая очередь озвучки. Может быть внедрена снаружи (тесты/UI);
        # иначе создаётся в start() вокруг TTSManager. Внедрённый worker
        # при start() НЕ подменяется.
        self.tts_worker = tts_worker
        self._internal_worker = False
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
        # Определяется в start() из llm.agent_query_prefix_enabled;
        # до start() префикс не применяется.
        self._agent_query_prefix_enabled = False

    def start(self) -> None:
        if self._started:
            return

        # TTS
        from jarvis.modules.tts import TTSManager, TTSWorker

        if self._internal_worker and self.tts_worker is not None:
            # Перезапуск pipeline: глушим старый внутренний worker.
            try:
                self.tts_worker.close(timeout=2.0)
            except Exception as e:
                logger.warning(f"⚠️ Старый TTS worker не закрылся: {e}")

        self.tts = TTSManager(self.config.get("tts", {}))
        if self.tts_worker is None or self._internal_worker:
            self.tts_worker = TTSWorker(self.tts)
            self._internal_worker = True

        # Platform (нужно ДО LLM — system_prompt подставляет platform info)
        if self.platform is None:
            from jarvis.modules.platform_adapter import PlatformAdapter

            self.platform = PlatformAdapter()

        # LLM — system prompt собирается в prompt_builder: {platform}
        # подставляется здесь, {datetime} клиентом на каждый запрос
        # (см. LLMClient._render_system_prompt). При agent_enabled секция
        # про инструменты (llm.system_prompt_tools) дописывается к базе.
        from jarvis.modules.llm import LLMManager
        from jarvis.prompt_builder import compose_system_prompt

        llm_cfg = dict(self.config.get("llm", {}))
        self._agent_query_prefix_enabled = bool(
            llm_cfg.get("agent_query_prefix_enabled", False)
        )
        llm_cfg["system_prompt"] = compose_system_prompt(
            llm_cfg.get("system_prompt"),
            self.agent_enabled,
            tools_prompt=llm_cfg.get("system_prompt_tools"),
            platform_str=self._platform_string(),
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
        # Голосовой путь: перед озвучкой вычищаем markdown/эмодзи, режем
        # длину (TTS-UX) и маскируем секреты. Текстовый чат (ui_bridge)
        # показывает ПОЛНЫЙ ответ — санитайз живёт только здесь.
        from jarvis.prompt_builder import redact_secrets, sanitize_for_tts

        try:
            spoken = redact_secrets(sanitize_for_tts(text))
        except Exception:
            spoken = text  # санитайз не должен рвать озвучку
        print(f"\r🤖 {spoken}")
        if self.tts_worker is not None:
            self.tts_worker.speak(spoken)
        elif self.tts is not None:
            self.tts.speak(spoken)

    def cancel_speech(self) -> None:
        """«Тихо»: глушит текущую озвучку и чистит очередь фраз."""
        if self.tts_worker is not None:
            self.tts_worker.cancel()

    def wait_for_speech(self, timeout: Optional[float] = None) -> bool:
        """Ждёт, пока worker доиграет очередь (чтобы не слушать свой голос).

        Если worker'а нет — True немедленно.
        """
        if self.tts_worker is None:
            return True
        return self.tts_worker.wait_idle(timeout)

    def process_query(
        self,
        query: str,
        stream_callback=None,
        tool_callback=None,
        tool_result_callback=None,
    ) -> str:
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
                return (
                    self._run_agent_loop(
                        query,
                        stream_callback=stream_callback,
                        tool_callback=tool_callback,
                        tool_result_callback=tool_result_callback,
                    )
                    or ""
                )
            except Exception as e:
                logger.error(f"❌ Agent loop failed: {e} — fallback to plain LLM")

        try:
            kwargs = {}
            if stream_callback is not None:
                kwargs["stream_callback"] = stream_callback
            return self.llm.chat(query, **kwargs) or ""
        except Exception as e:
            logger.error(f"❌ LLM: {e}")
            return "Извините, сэр, произошла ошибка."

    def _can_use_agent(self) -> bool:
        """Returns True iff the active LLM client supports chat_with_tools."""
        if not self.llm or not self.llm.primary:
            return False
        return hasattr(self.llm.primary, "chat_with_tools")

    def _run_agent_loop(
        self,
        query: str,
        stream_callback=None,
        tool_callback=None,
        tool_result_callback=None,
    ) -> Optional[str]:
        """Invoke chat_with_tools with bash_agent's tools + approval gate.

        The approval gate is enforced here (not inside bash_agent) so that
        the safety contract is visible at the pipeline level: any tool_call
        hitting ``bash`` is checked via bash_agent.check_approval before
        execution. Block → replaced with refusal message.
        """
        from jarvis.modules import bash_agent
        from jarvis.prompt_builder import agent_query_prefix

        client = self.llm.primary
        if client is None:
            return None

        # Опциональный пуш маленьких локальных моделей к прямому tool-call
        # (qwen2.5:3b любит «Я сейчас проверю...» вместо вызова).
        query = agent_query_prefix(
            query,
            provider=self.llm.provider,
            enabled=self._agent_query_prefix_enabled,
        )

        tools = bash_agent.get_tool_schemas()

        def _on_tool_call(name: str, args: dict) -> str:
            if tool_callback is not None:
                try:
                    tool_callback(name, args)
                except Exception:
                    pass  # UI notification must not break execution
            result = ""
            # Special: bash tool — apply approval gate before execute_tool.
            if name == "bash":
                cmd = args.get("cmd", "")
                block_reason = bash_agent.check_approval(
                    cmd, approval_mode=self.agent_approval_mode
                )
                if block_reason:
                    result = f"[BLOCKED] {block_reason}"
            if not result:
                result = str(bash_agent.execute_tool(name, args))
            # Token-budget guard + secret scrubbing before feeding back to LLM.
            from jarvis.prompt_builder import redact_secrets, truncate_tool_output

            result = truncate_tool_output(redact_secrets(result))
            if tool_result_callback is not None:
                try:
                    tool_result_callback(name, args, result)
                except Exception:
                    pass
            return result

        kwargs = {
            "tools": tools,
            "on_tool_call": _on_tool_call,
            "max_iterations": self.agent_max_iterations,
        }
        if stream_callback is not None:
            kwargs["stream_callback"] = stream_callback
        return client.chat_with_tools(query, **kwargs)

    def stop(self) -> None:
        # TTS worker: даём уже поставленным фразам доиграть и глушим поток.
        if self.tts_worker is not None:
            try:
                self.tts_worker.close()
            except Exception as e:
                logger.error(f"❌ TTS worker shutdown: {e}")
        # LLM/CommandManager явного shutdown'а не требуют.
        self._started = False
