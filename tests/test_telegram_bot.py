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
