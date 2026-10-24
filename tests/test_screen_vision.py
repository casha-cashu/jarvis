"""Tests for screen vision and multimodal support."""

from unittest.mock import MagicMock, patch

from jarvis.modules.commands import CommandExecutor
from jarvis.response_pipeline import ResponsePipeline


class TestScreenVision:
    def test_capture_screen_base64_success(self):
        executor = CommandExecutor("data/commands.json", "data/apps.json")
        with patch("PIL.ImageGrab.grab") as mock_grab:
            from PIL import Image

            mock_img = Image.new("RGB", (100, 100), color="blue")
            mock_grab.return_value = mock_img

            b64 = executor._capture_screen_base64()
            assert b64 is not None
            assert isinstance(b64, str)
            assert len(b64) > 50

    def test_screen_vision_command_dispatches_to_llm(self):
        executor = CommandExecutor("data/commands.json", "data/apps.json")
        mock_llm_chat = MagicMock(return_value="На экране открыт терминал.")
        executor.set_llm_chat(mock_llm_chat)

        with patch.object(
            executor, "_capture_screen_base64", return_value="fake_b64_data"
        ):
            resp = executor.execute("что на экране")
            assert resp == "На экране открыт терминал."
            mock_llm_chat.assert_called_once()
            args, kwargs = mock_llm_chat.call_args
            assert "images" in kwargs
            assert kwargs["images"] == ["fake_b64_data"]

    def test_screen_vision_fuzzy_match(self):
        executor = CommandExecutor("data/commands.json", "data/apps.json")
        mock_llm_chat = MagicMock(return_value="Вижу рабочий стол.")
        executor.set_llm_chat(mock_llm_chat)

        with patch.object(
            executor, "_capture_screen_base64", return_value="fake_b64_data"
        ):
            resp = executor.execute("посмотри на экран")
            assert resp == "Вижу рабочий стол."

    def test_screen_vision_failure_when_no_image(self):
        executor = CommandExecutor("data/commands.json", "data/apps.json")
        with patch.object(executor, "_capture_screen_base64", return_value=None):
            resp = executor.execute("что на экране")
            assert "Не удалось сделать снимок" in resp

    def test_screen_vision_failure_when_no_llm(self):
        executor = CommandExecutor("data/commands.json", "data/apps.json")
        executor.set_llm_chat(None)
        with patch.object(executor, "_capture_screen_base64", return_value="fake_b64"):
            resp = executor.execute("что на экране")
            assert "модель не подключена" in resp


class TestMultimodalPipeline:
    def test_process_query_with_images_bypasses_commands(self):
        config = {
            "llm": {"provider": "ollama", "system_prompt": "prompt"},
            "commands": {},
        }
        pipeline = ResponsePipeline(config)
        pipeline.llm = MagicMock()
        pipeline.llm.chat = MagicMock(return_value="Картинка проанализирована.")
        pipeline.commands = MagicMock()

        resp = pipeline.process_query("что это?", images=["img_base64"])
        assert resp == "Картинка проанализирована."
        pipeline.commands.process.assert_not_called()
        pipeline.llm.chat.assert_called_once_with("что это?", images=["img_base64"])
