"""
Тесты для модуля напоминаний (jarvis/modules/reminder.py).
"""

import time
import json
import pytest
from unittest.mock import patch, MagicMock

from jarvis.modules.reminder import (
    parse_time,
    ReminderManager,
    _save_reminders,
    _load_reminders,
)


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


class TestReminderPersistence:
    """Персистентность: атомарность записи и гонки RMW (filelock)."""

    @pytest.fixture
    def mock_reminders_file(self, tmp_path):
        reminders_file = tmp_path / "reminders.json"
        with patch("jarvis.modules.reminder.REMINDERS_FILE", new=reminders_file):
            yield reminders_file

    def test_concurrent_add_no_lost_updates(self, mock_reminders_file):
        """add() из десяти потоков не теряет напоминания — RMW под локом."""
        import threading

        mgr = ReminderManager(on_trigger=lambda text: None)

        def do_add(i):
            mgr.add(f"напоминание {i}", 9999)

        threads = [threading.Thread(target=do_add, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        data = json.loads(mock_reminders_file.read_text(encoding="utf-8"))
        assert len(data) == 10

    def test_save_leaves_no_tmp_files(self, mock_reminders_file):
        """Атомарная запись (tmp+replace) не оставляет .tmp-мусор."""
        _save_reminders(
            [{"text": "x", "time": time.time() + 60, "created": time.time()}]
        )
        leftovers = list(mock_reminders_file.parent.glob("*.tmp"))
        assert leftovers == []

    def test_modify_reminders_saves_on_exit(self, mock_reminders_file):
        """_modify_reminders пишет список на диск при выходе из with."""
        from jarvis.modules.reminder import _modify_reminders

        with _modify_reminders() as reminders:
            reminders.append(
                {"text": "новое", "time": time.time() + 60, "created": time.time()}
            )
        data = json.loads(mock_reminders_file.read_text(encoding="utf-8"))
        assert [d["text"] for d in data] == ["новое"]

    def test_nested_lock_same_thread_no_deadlock(self, mock_reminders_file):
        """Регрессия: старая _save_reminders_locked дедлочила сама на себя —
        FileLock должен быть реентерабельным в том же потоке."""
        from jarvis.modules.reminder import _file_lock

        with _file_lock():
            with _file_lock():
                _save_reminders([])


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
        expired = {
            "text": "просрочено",
            "time": time.time() - 100,
            "created": time.time() - 200,
        }
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


# ──────────────────────────────────────────────
# Тесты persistence: restart-резистентность напоминаний
# ──────────────────────────────────────────────


class TestReminderPersistence:
    """Главный UX-кейс: установил напоминание, перезапустил jarvis —
    напоминание выполнилось в срок (или сразу если просрочено)."""

    @pytest.fixture
    def mock_reminders_file(self, tmp_path):
        reminders_file = tmp_path / "reminders.json"
        with patch("jarvis.modules.reminder.REMINDERS_FILE", new=reminders_file):
            yield reminders_file

    def test_load_active_on_init(self, mock_reminders_file):
        """__init__ подгружает pending reminders из файла и стартует таймеры."""
        future = time.time() + 10
        _save_reminders(
            [
                {
                    "text": "перезапущенное напоминание",
                    "time": future,
                    "created": time.time(),
                }
            ]
        )
        mgr = ReminderManager(on_trigger=lambda text: None)
        assert len(mgr.timers) == 1
        assert "перезапущенное" in mock_reminders_file.read_text(encoding="utf-8")

    def test_expired_reminders_pruned_on_load(self, mock_reminders_file):
        """Просроченные напоминания при старте не активируются."""
        _save_reminders(
            [
                {
                    "text": "просрочка",
                    "time": time.time() - 100,
                    "created": time.time() - 200,
                },
                {"text": "живое", "time": time.time() + 500, "created": time.time()},
            ]
        )
        mgr = ReminderManager(on_trigger=lambda text: None)
        assert len(mgr.timers) == 1
        saved = _load_reminders()
        texts = [r["text"] for r in saved]
        assert "живое" in texts
        assert "просрочка" not in texts

    def test_shutdown_preserves_pending_reminders(self, mock_reminders_file):
        """shutdown() отменяет таймеры, но записывает невыполненные напоминания
        обратно в файл."""
        mgr = ReminderManager(on_trigger=lambda text: None)
        mgr.add("не успеет сработать", 9999)
        mgr.add("тоже", 9999)
        assert len(mgr.timers) == 2

        mgr.shutdown()
        assert len(mgr.timers) == 0
        saved = _load_reminders()
        texts = [r["text"] for r in saved]
        assert "не успеет сработать" in texts
        assert "тоже" in texts

    def test_survives_restart_cycle(self, mock_reminders_file):
        """End-to-end: add → shutdown → новый _load_active()."""
        mgr1 = ReminderManager(on_trigger=lambda text: None)
        mgr1.add("купить молоко", 3600)
        mgr1.shutdown()
        assert len(mgr1.timers) == 0
        assert mock_reminders_file.exists()

        mgr2 = ReminderManager(on_trigger=lambda text: None)
        assert len(mgr2.timers) == 1
        active = ReminderManager.list_active()
        assert len(active) == 1
        assert active[0][0] == "купить молоко"
        assert 3500 < active[0][1] <= 3600

    def test_corrupt_file_does_not_crash(self, mock_reminders_file):
        """Грязный JSON → пустой список, без исключений при __init__."""
        mock_reminders_file.parent.mkdir(parents=True, exist_ok=True)
        mock_reminders_file.write_text("{это не json", encoding="utf-8")
        mgr = ReminderManager(on_trigger=lambda text: None)
        assert mgr.timers == []

    def test_empty_when_no_file(self, tmp_path):
        """Без файла reminders.json ReminderManager стартует чисто."""
        non_existent = tmp_path / "absent_reminders.json"
        with patch("jarvis.modules.reminder.REMINDERS_FILE", new=non_existent):
            mgr = ReminderManager(on_trigger=lambda text: None)
            assert mgr.timers == []
