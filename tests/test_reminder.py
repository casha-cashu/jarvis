"""
Тесты для модуля напоминаний (jarvis/modules/reminder.py).
"""

import time
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from jarvis.modules.reminder import parse_time, ReminderManager, _load_reminders, _save_reminders


# ──────────────────────────────────────────────
# Тесты parse_time
# ──────────────────────────────────────────────

class TestParseTime:
    """Тестирует parse_time()."""

    def test_seconds_digits(self):
        result = parse_time("через 30 секунд позвонить маме")
        assert result is not None
        seconds, text = result
        assert seconds == 30
        assert text == "позвонить маме"

    def test_minutes_digits(self):
        result = parse_time("через 5 минут проверить почту")
        assert result is not None
        seconds, text = result
        assert seconds == 300
        assert text == "проверить почту"

    def test_hours_digits(self):
        result = parse_time("через 2 часа выключить свет")
        assert result is not None
        seconds, text = result
        assert seconds == 7200
        assert text == "выключить свет"

    def test_napomni_through(self):
        result = parse_time("напомни через 10 минут сделать зарядку")
        assert result is not None
        seconds, text = result
        assert seconds == 600
        assert text == "сделать зарядку"

    def test_timer(self):
        result = parse_time("таймер на 10 минут")
        assert result is not None
        seconds, text = result
        assert seconds == 600

    def test_no_match(self):
        result = parse_time("привет как дела")
        assert result is None

    def test_edge_spaces(self):
        result = parse_time("  через   5   минут   сделать   ")
        assert result is not None
        seconds, text = result
        assert seconds == 300
        assert text == "сделать"


# ──────────────────────────────────────────────
# Тесты ReminderManager
# ──────────────────────────────────────────────

class TestReminderManager:

    @pytest.fixture
    def mock_reminders_file(self, tmp_path):
        reminders_file = tmp_path / "reminders.json"
        with patch("jarvis.modules.reminder.REMINDERS_FILE", new=reminders_file):
            yield reminders_file

    def test_add_reminder(self, mock_reminders_file):
        mgr = ReminderManager(on_trigger=lambda text: None)
        result = mgr.add("тестовое напоминание", 30)
        assert "напомню" in result
        assert mock_reminders_file.exists()
        data = json.loads(mock_reminders_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["text"] == "тестовое напоминание"

    def test_add_multiple(self, mock_reminders_file):
        mgr = ReminderManager(on_trigger=lambda text: None)
        mgr.add("первое", 60)
        mgr.add("второе", 120)
        data = json.loads(mock_reminders_file.read_text(encoding="utf-8"))
        assert len(data) == 2

    def test_list_active_empty(self, mock_reminders_file):
        reminders = ReminderManager.list_active()
        assert reminders == []

    def test_list_active_with_items(self, mock_reminders_file):
        mgr = ReminderManager(on_trigger=lambda text: None)
        mgr.add("активное", 9999)
        mgr.add("тоже активное", 9999)
        active = ReminderManager.list_active()
        assert len(active) == 2

    def test_list_active_excludes_expired(self, mock_reminders_file):
        expired = {"text": "просрочено", "time": time.time() - 100, "created": time.time() - 200}
        _save_reminders([expired])
        active = ReminderManager.list_active()
        texts = [t for t, s in active]
        assert "просрочено" not in texts

    def test_fire_calls_on_trigger(self, mock_reminders_file):
        callback = MagicMock()
        mgr = ReminderManager(on_trigger=callback)
        mgr.add("сработай", 0.01)
        time.sleep(0.05)
        callback.assert_called_once_with("сработай")
