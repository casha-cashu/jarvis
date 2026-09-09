"""Тесты Telegram-бота: чистые функции без сети (aiogram не нужен)."""

import pytest

from jarvis.config_schema import validate_config
from jarvis.telegram_bot import (
    is_allowed_chat,
    resolve_token,
    split_for_telegram,
)


class TestResolveToken:
    def test_from_config(self):
        cfg = {"telegram": {"bot_token": "123:ABC"}}
        assert resolve_token(cfg) == "123:ABC"

    def test_unfilled_placeholder_falls_back_to_env(self, monkeypatch):
        """${TELEGRAM_BOT_TOKEN} из example — незаполненный плейсхолдер,
        берётся значение из окружения."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        cfg = {"telegram": {"bot_token": "${TELEGRAM_BOT_TOKEN}"}}
        assert resolve_token(cfg) == "env-token"

    def test_env_only(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        assert resolve_token({}) == "env-token"

    def test_none_when_nothing(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        assert resolve_token({}) is None


class TestAllowedChats:
    def test_fail_closed_empty_whitelist(self):
        assert is_allowed_chat(123, []) is False

    def test_allowed_id_passes(self):
        assert is_allowed_chat(123, [123, 456]) is True

    def test_stranger_denied(self):
        assert is_allowed_chat(999, [123]) is False

    def test_strict_types(self):
        """Int-ключ и str-значение не совпадают — защита от путаницы."""
        assert is_allowed_chat("123", [123]) is False


class TestSplitForTelegram:
    def test_short_passes_through(self):
        assert split_for_telegram("привет") == ["привет"]

    def test_empty_gives_empty(self):
        assert split_for_telegram("") == []
        assert split_for_telegram("   ") == []

    def test_long_splits_under_limit(self):
        text = "Слово " * 2000
        chunks = split_for_telegram(text, limit=3900)
        assert all(len(c) <= 3900 for c in chunks)
        assert " ".join(chunks).count("Слово") == 2000

    def test_prefers_paragraph_break(self):
        text = "А" * 100 + "\n\n" + "Б" * 100
        chunks = split_for_telegram(text, limit=150)
        assert len(chunks) == 2
        assert chunks[0] == "А" * 100


class TestSchema:
    def test_telegram_section_validates(self):
        validate_config(
            {
                "telegram": {
                    "enabled": True,
                    "bot_token": "123:ABC",
                    "allowed_chat_ids": [1, 2, 3],
                }
            }
        )

    def test_telegram_typo_rejected(self):
        with pytest.raises(Exception, match="allowed_chat"):
            validate_config({"telegram": {"allowed_chat": [1]}})

    def test_telegram_defaults(self):
        from jarvis.config_schema import JarvisConfig

        c = JarvisConfig()
        assert c.telegram.enabled is False
        assert c.telegram.allowed_chat_ids == []


class TestNormalizeAllowedChatIds:
    def test_strings_and_ints_normalized(self):
        from jarvis.telegram_bot import normalize_allowed_chat_ids

        raw = ["123", 456, "-100987654321", "invalid", None]
        assert normalize_allowed_chat_ids(raw) == [123, 456, -100987654321]


class TestTelegramAssistantFeatures:
    def test_resolve_marker_reminders(self, monkeypatch, tmp_path):
        from jarvis.telegram_bot import TelegramAssistant

        cfg = {"llm": {"provider": "ollama"}, "telegram": {}}
        assistant = TelegramAssistant(cfg)

        assert assistant._resolve_marker("__MUTE__") == "Хорошо, сэр. Я замолкаю."
        assert assistant._resolve_marker("__UNMUTE__") == "Я снова слушаю, сэр."
        assert (
            assistant._resolve_marker("__DICTATE__")
            == "Режим диктовки доступен только при голосовом вводе."
        )
        assert assistant._resolve_marker("__EXIT__") == "Текстовая сессия продолжается."
        assert assistant._resolve_marker("Обычный ответ") == "Обычный ответ"

    def test_session_lifecycle(self, tmp_path, monkeypatch):
        from jarvis.telegram_bot import TelegramAssistant
        from jarvis.modules import llm as llm_module

        # Redirect history
        ui_hist = tmp_path / "ui-history"
        ui_hist.mkdir()
        monkeypatch.setattr(llm_module, "HISTORY_FILE", tmp_path / "history.json")

        cfg = {"llm": {"provider": "ollama"}, "telegram": {}}
        assistant = TelegramAssistant(cfg)
        monkeypatch.setattr(assistant, "_history_dir", lambda: ui_hist)

        # Create session
        sid = assistant.create_new_session("test")
        assert sid.startswith("test-")
        assert assistant._current_session == sid
        assert (ui_hist / f"{sid}.json").exists()

        # List sessions
        sessions = assistant.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid
        assert sessions[0]["is_current"] is True

        # Clear session
        assistant.clear_current_session()
        assert (ui_hist / f"{sid}.json").read_text(encoding="utf-8") == "[]"

    def test_ensure_pipeline_binds_attributes(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from jarvis.telegram_bot import TelegramAssistant

        assistant = TelegramAssistant({})
        mock_jarvis = MagicMock()
        mock_response = MagicMock()
        mock_jarvis.response = mock_response

        with patch("jarvis.Jarvis", return_value=mock_jarvis):
            assistant._ensure_pipeline()
            assert assistant._jarvis.commands == mock_response.commands
            assert assistant._jarvis.llm == mock_response.llm
            assert assistant._jarvis.platform == mock_response.platform

    @pytest.mark.anyio
    async def test_process_resolves_command_markers(self):
        from unittest.mock import MagicMock
        from jarvis.telegram_bot import TelegramAssistant

        assistant = TelegramAssistant({})
        assistant._jarvis = MagicMock()
        assistant._jarvis.commands.process.return_value = "__MUTE__"

        result = await assistant.process("тихо")
        assert result == "Хорошо, сэр. Я замолкаю."
        assistant._jarvis.response.process_query.assert_not_called()

    def test_resolve_reminder_marker(self):
        from unittest.mock import MagicMock
        from jarvis.telegram_bot import TelegramAssistant

        assistant = TelegramAssistant({})
        mock_jarvis = MagicMock()
        mock_reminder = MagicMock()
        mock_reminder.add.return_value = "Напоминание установлено: чай через 60 сек."
        mock_jarvis.reminder_mgr = mock_reminder
        assistant._jarvis = mock_jarvis

        res = assistant._resolve_marker("__REMINDER__:60:чай")
        assert res == "Напоминание установлено: чай через 60 сек."
        mock_reminder.add.assert_called_once_with("чай", 60)

    def test_switch_session(self, tmp_path, monkeypatch):
        from jarvis.telegram_bot import TelegramAssistant
        from jarvis.modules import llm as llm_module
        import json

        ui_hist = tmp_path / "ui-history"
        ui_hist.mkdir()
        monkeypatch.setattr(llm_module, "HISTORY_FILE", tmp_path / "history.json")

        assistant = TelegramAssistant({})
        monkeypatch.setattr(assistant, "_history_dir", lambda: ui_hist)

        # Create session 1
        s1 = assistant.create_new_session("first")
        (ui_hist / f"{s1}.json").write_text(
            json.dumps([{"role": "user", "content": "hello"}]), encoding="utf-8"
        )

        # Create session 2
        s2 = assistant.create_new_session("second")
        assert s2.startswith("second-")

        # Switch back to session 1
        assert assistant.switch_session(s1) is True
        assert assistant._current_session == s1

        # Switch to non-existent session
        assert assistant.switch_session("nonexistent_session") is False

    @pytest.mark.anyio
    async def test_process_normal_query_delegates_to_response_pipeline(self):
        from unittest.mock import MagicMock
        from jarvis.telegram_bot import TelegramAssistant

        assistant = TelegramAssistant({})
        assistant._jarvis = MagicMock()
        assistant._jarvis.commands.process.return_value = None
        assistant._jarvis.response.process_query.return_value = "Ответ модели"

        result = await assistant.process("расскажи что-нибудь")
        assert result == "Ответ модели"
        assert assistant._jarvis.response.process_query.call_count == 1
        args, kwargs = assistant._jarvis.response.process_query.call_args
        assert args[0] == "расскажи что-нибудь"
        assert "tool_callback" in kwargs
