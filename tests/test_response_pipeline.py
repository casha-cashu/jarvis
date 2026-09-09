"""
Тесты для jarvis.response_pipeline.ResponsePipeline.
Изолирует роутинг команд, вызовы LLM, agent loop и воспроизведение речи (TTS).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jarvis.response_pipeline import ResponsePipeline


class TestResponsePipelineInit:
    def test_init_defaults(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        assert pipeline.config == sample_config
        assert pipeline.platform is None
        assert pipeline.tts_worker is None
        assert pipeline.tts is None
        assert pipeline.llm is None
        assert pipeline.commands is None
        assert pipeline._started is False
        assert pipeline.agent_enabled is False
        assert pipeline.agent_max_iterations == 5
        assert pipeline.agent_approval_mode == "auto"

    def test_init_agent_config(self, sample_config):
        cfg = dict(sample_config)
        cfg["llm"] = dict(sample_config["llm"])
        cfg["llm"]["agent_enabled"] = True
        cfg["llm"]["agent_max_iterations"] = 10
        cfg["llm"]["agent_approval_mode"] = "strict"

        pipeline = ResponsePipeline(cfg)
        assert pipeline.agent_enabled is True
        assert pipeline.agent_max_iterations == 10
        assert pipeline.agent_approval_mode == "strict"


class TestResponsePipelineStartAndStop:
    def test_start_and_stop_lifecycle(self, sample_config):
        mock_tts_mgr = MagicMock()
        mock_tts_worker = MagicMock()
        mock_platform = MagicMock()
        mock_llm_mgr = MagicMock()
        mock_cmd_mgr = MagicMock()

        with (
            patch("jarvis.modules.tts.TTSManager", return_value=mock_tts_mgr),
            patch("jarvis.modules.tts.TTSWorker", return_value=mock_tts_worker),
            patch(
                "jarvis.modules.platform_adapter.PlatformAdapter",
                return_value=mock_platform,
            ),
            patch("jarvis.modules.llm.LLMManager", return_value=mock_llm_mgr),
            patch("jarvis.modules.commands.CommandManager", return_value=mock_cmd_mgr),
        ):
            pipeline = ResponsePipeline(sample_config)
            pipeline.start()

            assert pipeline._started is True
            assert pipeline.tts == mock_tts_mgr
            assert pipeline.tts_worker == mock_tts_worker
            assert pipeline.platform == mock_platform
            assert pipeline.llm == mock_llm_mgr
            assert pipeline.commands == mock_cmd_mgr

            # Идемпотентность start()
            pipeline.start()
            assert pipeline._started is True

            # Stop
            pipeline.stop()
            assert pipeline._started is False
            mock_tts_worker.close.assert_called_once()
            mock_cmd_mgr.cleanup.assert_called_once()

    def test_platform_string_formatting(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        assert pipeline._platform_string() == ""

        mock_platform = MagicMock()
        mock_platform.os = "Linux"
        mock_platform.distro = "Arch"
        mock_platform.de = "Hyprland"
        pipeline.platform = mock_platform

        assert pipeline._platform_string() == "Linux/Arch (Hyprland)"


class TestResponsePipelineSpeechControl:
    def test_speak_sanitizes_and_dispatches_to_worker(self, sample_config):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline(sample_config, tts_worker=mock_worker)

        with (
            patch("jarvis.prompt_builder.sanitize_for_tts", return_value="привет мир"),
            patch("jarvis.prompt_builder.redact_secrets", return_value="привет мир"),
        ):
            pipeline.speak("привет мир **жирный**")
            mock_worker.speak.assert_called_once_with("привет мир")

    def test_cancel_speech(self, sample_config):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline(sample_config, tts_worker=mock_worker)
        pipeline.cancel_speech()
        mock_worker.cancel.assert_called_once()

    def test_wait_for_speech(self, sample_config):
        mock_worker = MagicMock()
        mock_worker.wait_idle.return_value = True
        pipeline = ResponsePipeline(sample_config, tts_worker=mock_worker)

        assert pipeline.wait_for_speech(timeout=2.0) is True
        mock_worker.wait_idle.assert_called_once_with(2.0)

    def test_wait_for_speech_no_worker_returns_true(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        assert pipeline.wait_for_speech() is True


class TestResponsePipelineProcessQuery:
    def test_process_query_command_match(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        mock_commands = MagicMock()
        mock_commands.process.return_value = "Громкость 50%"
        pipeline.commands = mock_commands

        res = pipeline.process_query("сделай громче")
        assert res == "Громкость 50%"
        mock_commands.process.assert_called_once_with("сделай громче")

    def test_process_query_command_empty_reply_defaults(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        mock_commands = MagicMock()
        mock_commands.process.return_value = ""  # пустой say
        pipeline.commands = mock_commands

        res = pipeline.process_query("запусти firefox")
        assert res == "Готово, сэр."

    def test_process_query_command_special_marker_returns_empty(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        mock_commands = MagicMock()
        mock_commands.process.return_value = "__MUTE__"
        pipeline.commands = mock_commands

        res = pipeline.process_query("тихо")
        assert res == ""

    def test_process_query_falls_back_to_llm(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        mock_commands = MagicMock()
        mock_commands.process.return_value = None  # Не команда
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "Привет! Чем могу помочь?"

        pipeline.commands = mock_commands
        pipeline.llm = mock_llm

        stream_cb = MagicMock()
        res = pipeline.process_query("какая погода", stream_callback=stream_cb)
        assert res == "Привет! Чем могу помочь?"
        mock_llm.chat.assert_called_once_with("какая погода", stream_callback=stream_cb)

    def test_process_query_llm_error_returns_polite_message(self, sample_config):
        pipeline = ResponsePipeline(sample_config)
        mock_commands = MagicMock()
        mock_commands.process.return_value = None
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("Connection timed out")

        pipeline.commands = mock_commands
        pipeline.llm = mock_llm

        res = pipeline.process_query("вопрос")
        assert res == "Извините, сэр, произошла ошибка."

    def test_process_query_agent_loop_execution(self, sample_config):
        cfg = dict(sample_config)
        cfg["llm"]["agent_enabled"] = True
        pipeline = ResponsePipeline(cfg)
        pipeline.agent_enabled = True

        mock_commands = MagicMock()
        mock_commands.process.return_value = None
        pipeline.commands = mock_commands

        mock_client = MagicMock()
        mock_client.chat_with_tools = MagicMock(return_value="Выполнено: 3 файла.")
        mock_llm_mgr = MagicMock()
        mock_llm_mgr.primary = mock_client
        mock_llm_mgr.provider = "ollama"
        pipeline.llm = mock_llm_mgr

        tool_cb = MagicMock()
        tool_res_cb = MagicMock()

        with (
            patch(
                "jarvis.modules.bash_agent.get_tool_schemas",
                return_value=[{"name": "bash"}],
            ),
            patch("jarvis.modules.bash_agent.check_approval", return_value=None),
            patch(
                "jarvis.modules.bash_agent.execute_tool",
                return_value="file1\nfile2\nfile3",
            ),
        ):
            res = pipeline.process_query(
                "посчитай файлы в папке",
                tool_callback=tool_cb,
                tool_result_callback=tool_res_cb,
            )
            assert res == "Выполнено: 3 файла."
            mock_client.chat_with_tools.assert_called_once()

    def test_process_query_agent_loop_blocks_dangerous_bash(self, sample_config):
        cfg = dict(sample_config)
        cfg["llm"]["agent_enabled"] = True
        pipeline = ResponsePipeline(cfg)
        pipeline.agent_enabled = True

        mock_commands = MagicMock()
        mock_commands.process.return_value = None
        pipeline.commands = mock_commands

        mock_client = MagicMock()

        def fake_chat_with_tools(query, tools, on_tool_call, max_iterations, **kwargs):
            # Симулируем попытку вызова bash
            tool_output = on_tool_call("bash", {"cmd": "rm -rf /"})
            return f"Результат вызова: {tool_output}"

        mock_client.chat_with_tools = fake_chat_with_tools
        mock_llm_mgr = MagicMock()
        mock_llm_mgr.primary = mock_client
        mock_llm_mgr.provider = "ollama"
        pipeline.llm = mock_llm_mgr

        with (
            patch("jarvis.modules.bash_agent.get_tool_schemas", return_value=[]),
            patch(
                "jarvis.modules.bash_agent.check_approval",
                return_value="Blocked (hardline): recursive forced deletion of '/'",
            ),
        ):
            res = pipeline.process_query("удали всё")
            assert "[BLOCKED]" in res
            assert "Blocked (hardline)" in res

    def test_process_query_agent_tool_output_order(self, sample_config):
        cfg = dict(sample_config)
        cfg["llm"]["agent_enabled"] = True
        pipeline = ResponsePipeline(cfg)
        pipeline.agent_enabled = True

        mock_commands = MagicMock()
        mock_commands.process.return_value = None
        pipeline.commands = mock_commands

        mock_client = MagicMock()
        calls = []

        def fake_chat_with_tools(query, tools, on_tool_call, max_iterations, **kwargs):
            return on_tool_call("read", {"path": "/tmp/test.txt"})

        mock_client.chat_with_tools = fake_chat_with_tools
        mock_llm_mgr = MagicMock()
        mock_llm_mgr.primary = mock_client
        mock_llm_mgr.provider = "ollama"
        pipeline.llm = mock_llm_mgr

        def fake_truncate(text):
            calls.append("truncate")
            return text

        def fake_redact(text):
            calls.append("redact")
            return text

        with (
            patch("jarvis.modules.bash_agent.get_tool_schemas", return_value=[]),
            patch(
                "jarvis.modules.bash_agent.execute_tool",
                return_value="raw_tool_output",
            ),
            patch(
                "jarvis.prompt_builder.truncate_tool_output", side_effect=fake_truncate
            ),
            patch("jarvis.prompt_builder.redact_secrets", side_effect=fake_redact),
        ):
            pipeline.process_query("прочитай файл")
            assert calls == ["truncate", "redact"]
