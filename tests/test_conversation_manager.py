"""
Тесты для jarvis.conversation_manager.ConversationManager.
Проверка логики обнаружения wake-word, границ слов, режима тишины и многошагового диалога.
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from jarvis.conversation_manager import ConversationManager


class TestConversationManagerInit:
    def test_default_wake_words(self):
        cm = ConversationManager([])
        assert cm.wake_words == ["джарвис"]
        assert cm.is_muted is False
        assert cm.on_mute is None

    def test_custom_wake_words_lowercased(self):
        cm = ConversationManager(["Джарвис", "ЖАРВИС", "Jarvis"], muted=True)
        assert cm.wake_words == ["джарвис", "жарвис", "jarvis"]
        assert cm.is_muted is True


class TestConversationManagerMute:
    def test_mute_sets_flag_and_calls_callback(self):
        on_mute_mock = MagicMock()
        cm = ConversationManager(["джарвис"], on_mute=on_mute_mock)

        cm.mute()
        assert cm.is_muted is True
        on_mute_mock.assert_called_once()

    def test_mute_catches_callback_exception(self):
        on_mute_mock = MagicMock(side_effect=RuntimeError("audio device busy"))
        cm = ConversationManager(["джарвис"], on_mute=on_mute_mock)

        # Не должно вызывать падение
        cm.mute()
        assert cm.is_muted is True


class TestConversationManagerDetectWake:
    @pytest.fixture
    def manager(self):
        return ConversationManager(["джарвис", "жарвис", "jarvis"])

    def test_empty_or_none(self, manager):
        assert manager.detect_wake("") == (False, None)
        assert manager.detect_wake(None) == (False, None)

    def test_exact_wake_word_alone(self, manager):
        detected, query = manager.detect_wake("джарвис")
        assert detected is True
        assert query is None

    def test_wake_word_at_start_with_query(self, manager):
        detected, query = manager.detect_wake("джарвис сколько сейчас времени")
        assert detected is True
        assert query == "сколько сейчас времени"

    def test_wake_word_with_punctuation(self, manager):
        detected, query = manager.detect_wake("Джарвис, переключи на 2 воркспейс!")
        assert detected is True
        assert "переключи на 2 воркспейс!" in query

    def test_wake_word_in_middle(self, manager):
        detected, query = manager.detect_wake("эй джарвис открой терминал")
        assert detected is True
        assert query == "открой терминал"

    def test_wake_word_at_end(self, manager):
        detected, query = manager.detect_wake("ты слушаешь меня джарвис")
        assert detected is True
        assert query is None

    def test_wake_word_boundary_isolation(self, manager):
        # "джарвиссимо" НЕ должно триггерить детекцию
        detected, query = manager.detect_wake("джарвиссимо включи музыку")
        assert detected is False
        assert query is None

        detected, query = manager.detect_wake("мегаджарвис привет")
        assert detected is False
        assert query is None

    def test_alternative_wake_words(self, manager):
        detected, query = manager.detect_wake("жарвис сделай громче")
        assert detected is True
        assert query == "сделай громче"

        detected, query = manager.detect_wake("jarvis what time is it")
        assert detected is True
        assert query == "what time is it"


class TestConversationManagerUnmuteAndFollowUp:
    @pytest.fixture
    def manager(self):
        return ConversationManager(["джарвис", "жарвис"])

    def test_is_unmute_phrase(self, manager):
        assert manager.is_unmute_phrase("джарвис, проснись") is True
        assert manager.is_unmute_phrase("хай") is True
        assert manager.is_unmute_phrase("джарвис") is True
        assert manager.is_unmute_phrase("какая погода") is False
        assert manager.is_unmute_phrase("") is False

    def test_has_wake_in_follow_up(self, manager):
        assert manager.has_wake_in_follow_up("джарвис, а расскажи анекдот") is True
        assert manager.has_wake_in_follow_up("жарвис подожди") is True
        assert manager.has_wake_in_follow_up("а почему так?") is False
        assert manager.has_wake_in_follow_up("") is False
