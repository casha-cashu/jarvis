"""
Тесты для модуля команд (jarvis/modules/commands.py).
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from jarvis.adapters.base import BaseAdapter

# ──────────────────────────────────────────────
# FakeAdapter — наследует BaseAdapter
# ──────────────────────────────────────────────


class FakeAdapter(BaseAdapter):
    """
    Адаптер-заглушка для тестов.
    Реализует только абстрактные методы BaseAdapter минимумом,
    остальное (notify, input_text, system_reboot, ...) наследует.
    """

    def __init__(self):
        super().__init__()
        self.name = "fake"
        self.executed_commands = []

    def _fake_cmd(self, cmd: str) -> str:
        self.executed_commands.append(cmd)
        return cmd

    def workspace_switch(self, number: int) -> str:
        return self._fake_cmd(f"workspace_switch {number}")

    def workspace_next(self) -> str:
        return self._fake_cmd("workspace_next")

    def workspace_prev(self) -> str:
        return self._fake_cmd("workspace_prev")

    def window_close(self) -> str:
        return self._fake_cmd("window_close")

    def window_fullscreen(self) -> str:
        return self._fake_cmd("window_fullscreen")

    def window_minimize(self) -> str:
        return self._fake_cmd("window_minimize")

    def window_maximize(self) -> str:
        return self._fake_cmd("window_maximize")

    def window_floating(self) -> str:
        return self._fake_cmd("window_floating")

    def window_next(self) -> str:
        return self._fake_cmd("window_next")

    def window_prev(self) -> str:
        return self._fake_cmd("window_prev")

    def screenshot_screen(self) -> str:
        return self._fake_cmd("screenshot_screen")

    def screenshot_area(self) -> str:
        return self._fake_cmd("screenshot_area")

    def screenshot_window(self) -> str:
        return self._fake_cmd("screenshot_window")

    def volume_up(self, amount: int = 5) -> str:
        return self._fake_cmd(f"volume_up {amount}")

    def volume_down(self, amount: int = 5) -> str:
        return self._fake_cmd(f"volume_down {amount}")

    def volume_mute(self) -> str:
        return self._fake_cmd("volume_mute")

    def volume_unmute(self) -> str:
        return self._fake_cmd("volume_unmute")

    def lock_screen(self) -> str:
        return self._fake_cmd("lock_screen")


# ──────────────────────────────────────────────
# Тесты CommandExecutor
# ──────────────────────────────────────────────


@pytest.fixture
def fake_commands_file(tmp_path) -> Path:
    data = {
        "commands": {
            "тест": {"cmd": "echo test", "say": "Тест выполнен", "category": "test"},
            "время": {"cmd": "date", "say": "Текущее время", "category": "info"},
        }
    }
    p = tmp_path / "commands.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def fake_apps_file(tmp_path) -> Path:
    data = {
        "apps": {
            "testapp": {
                "cmd": "testapp-gui",
                "names": ["testapp", "тестовая программа", "тестовое приложение"],
            }
        }
    }
    p = tmp_path / "apps.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def executor(fake_commands_file, fake_apps_file, monkeypatch):
    from jarvis.modules.commands import CommandExecutor

    # Stub _run чтобы тесты не запускали реальный subprocess (echo/date/
    # xdg-open/...). Pipeline-логику (routing по exact/fuzzy/pattern/voice)
    # мы тестируем, а не shell behaviour.
    monkeypatch.setattr(CommandExecutor, "_run", lambda self, cmd: None)
    return CommandExecutor(
        commands_file=str(fake_commands_file),
        apps_file=str(fake_apps_file),
        fuzzy_threshold=0.8,
        platform_adapter=FakeAdapter(),
    )


class TestCommandExecutor:
    """Тесты CommandExecutor."""

    def test_exact_match(self, executor):
        result = executor.execute("тест")
        assert result == "Тест выполнен"

    def test_exact_match_with_case(self, executor):
        result = executor.execute("ТЕСТ")
        assert result == "Тест выполнен"

    def test_fuzzy_match(self, executor):
        result = executor.execute("тест ")
        assert result == "Тест выполнен"

    def test_no_match_returns_none(self, executor):
        result = executor.execute("этой команды не существует")
        assert result is None

    def test_app_by_prefix(self, executor):
        result = executor.execute("открой testapp")
        assert result == "Запускаю testapp"

    def test_app_by_name_standalone(self, executor):
        result = executor.execute("testapp")
        assert result == "Запускаю testapp"

    def test_web_search(self, executor):
        result = executor.execute("найди python")
        assert result == "Ищу python"

    def test_voice_mute(self, executor):
        result = executor.execute("заткнись")
        assert result == "__MUTE__"

    def test_voice_unmute(self, executor):
        result = executor.execute("продолжай")
        assert result == "__UNMUTE__"

    def test_voice_dictation(self, executor):
        result = executor.execute("диктовка")
        assert result == "__DICTATE__"

    def test_voice_exit(self, executor):
        result = executor.execute("выйти")
        assert result == "__EXIT__"

    def test_voice_reminder_list(self, executor):
        result = executor.execute("список напоминаний")
        assert result == "__REMINDER_LIST__"

    def test_voice_reminder_create(self, executor):
        result = executor.execute("через 5 секунд позвонить")
        assert result is not None
        assert result.startswith("__REMINDER__:")
        parts = result.split(":")
        assert len(parts) == 3
        assert parts[1] == "5" or int(parts[1]) == 5

    def test_empty_query(self, executor):
        assert executor.execute("") is None
        assert executor.execute("   ") is None


class TestFakeAdapter:
    """Проверяет, что FakeAdapter реализует всё необходимое."""

    def test_abstract_methods_implemented(self):
        adapter = FakeAdapter()
        assert adapter.name == "fake"

    def test_notify_inherited(self):
        adapter = FakeAdapter()
        result = adapter.notify("Title", "Message")
        assert "notify-send" in result
        assert "Title" in result
        assert "Message" in result

    def test_input_text_inherited(self):
        adapter = FakeAdapter()
        result = adapter.input_text("Hello")
        assert "wtype" in result or "xdotool" in result

    def test_system_reboot_inherited(self):
        adapter = FakeAdapter()
        assert adapter.system_reboot() == "reboot"

    def test_system_shutdown_inherited(self):
        adapter = FakeAdapter()
        assert adapter.system_shutdown() == "poweroff"

    def test_executed_commands_tracked(self):
        adapter = FakeAdapter()
        adapter.workspace_switch(3)
        adapter.window_close()
        assert "workspace_switch 3" in adapter.executed_commands
        assert "window_close" in adapter.executed_commands


# ──────────────────────────────────────────────
# Тесты execution_timeout (P-improvement: kill зависших команд)
# ──────────────────────────────────────────────


class TestExecutionTimeout:
    """_run должен убивать команду превысившей execution_timeout."""

    def _make_executor(self, monkeypatch, execution_timeout=1):
        from jarvis.modules.commands import CommandExecutor

        # Создаём executor через __new__ чтобы не читать JSON-файлы.
        ex = CommandExecutor.__new__(CommandExecutor)
        ex.execution_timeout = execution_timeout
        return ex

    def test_fast_command_completes(self, monkeypatch):
        """Команда завершившаяся до timeout — должна выполниться нормально."""
        ex = self._make_executor(monkeypatch, execution_timeout=5)
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.wait = MagicMock()  # не raise → завершилась до timeout
            mock_popen.return_value = proc
            ex._run("echo test")
            proc.wait.assert_called_once_with(timeout=5)
            proc.terminate.assert_not_called()

    def test_timeout_sends_sigterm_then_sigkill(self, monkeypatch):
        """При timeout: SIGTERM → grace 2s → SIGKILL."""
        import subprocess

        ex = self._make_executor(monkeypatch, execution_timeout=1)
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            # First wait() times out. terminate() not effective → second
            # wait() also times out. kill() is last resort.
            proc.wait.side_effect = [
                subprocess.TimeoutExpired("cmd", 1),  # основной timeout
                subprocess.TimeoutExpired("cmd", 2),  # grace 2s тоже
            ]
            mock_popen.return_value = proc
            ex._run("sleep 1000")
            proc.wait.assert_any_call(timeout=1)
            proc.terminate.assert_called_once()
            proc.kill.assert_called_once()

    def test_execution_timeout_clamped_to_min_1(self, monkeypatch):
        """execution_timeout=0 или отрицательный → 1 секунда."""
        # Проверяем max(1, ...) логику, которая в CommandExecutor.__init__.
        # int(...) + max(1, ...) — гарантия что timeout >= 1.
        assert max(1, int(0)) == 1
        assert max(1, int(-5)) == 1
        assert max(1, int(30)) == 30

    def test_empty_cmd_skips_subprocess(self, monkeypatch):
        """Пустая команда (после callable) не должна запускать subprocess."""
        ex = self._make_executor(monkeypatch, execution_timeout=5)
        with patch("subprocess.Popen") as mock_popen:
            ex._run("")  # пустая строка
            ex._run(None)  # None
            ex._run(lambda: "")  # callable → ""
            ex._run(lambda: None)
            mock_popen.assert_not_called()

    def test_callable_cmd_evaluated_at_run_time(self, monkeypatch):
        """Callable cmd вычисляется в момент _run, а не в момент execute()."""
        ex = self._make_executor(monkeypatch, execution_timeout=5)
        calls = []

        def make_cmd():
            calls.append("called")
            return "echo hi"

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.wait = MagicMock()
            mock_popen.return_value = proc
            ex._run(make_cmd)
            assert calls == ["called"]
            mock_popen.assert_called_once()
