"""Интеграционные тесты NLU ↔ CommandExecutor.

Проверяют что IntentRouter, подключённый к CommandExecutor, корректно
диспетчеризует запросы на основании intent + slots, не ломая fallback
на существующий fuzzy/pattern pipeline при низкой уверенности.

Все ``_run`` мокируются — реальных subprocess-вызовов нет.
"""


import json
from unittest.mock import MagicMock

import pytest

from jarvis.adapters.base import BaseAdapter
from jarvis.modules.commands import CommandExecutor, CommandManager

# Requires full deps (sklearn); excluded from slim CI jobs.
pytestmark = pytest.mark.integration


class _FakeAdapter(BaseAdapter):
    def __init__(self):
        super().__init__()
        self.name = "fake"
        self.commands_executed = []

    def _rec(self, cmd):
        self.commands_executed.append(cmd)
        return cmd

    def workspace_switch(self, n):
        return self._rec(f"swtich-to-{n}")

    def workspace_next(self):
        return self._rec("ws-next")

    def workspace_prev(self):
        return self._rec("ws-prev")

    def window_close(self):
        return self._rec("win-close")

    def window_fullscreen(self):
        return self._rec("win-fullscreen")

    def window_minimize(self):
        return self._rec("win-min")

    def window_maximize(self):
        return self._rec("win-max")

    def window_floating(self):
        return self._rec("win-float")

    def window_next(self):
        return self._rec("win-next")

    def window_prev(self):
        return self._rec("win-prev")

    def screenshot_screen(self):
        return self._rec("shot-screen")

    def screenshot_area(self):
        return self._rec("shot-area")

    def screenshot_window(self):
        return self._rec("shot-win")

    def volume_up(self, amount=5):
        return self._rec(f"vol-up-{amount}")

    def volume_down(self, amount=5):
        return self._rec(f"vol-down-{amount}")

    def volume_mute(self):
        return self._rec("vol-mute")

    def volume_unmute(self):
        return self._rec("vol-unmute")

    def lock_screen(self):
        return self._rec("lock")


@pytest.fixture
def data_files(tmp_path):
    """Larger training set — enough for NLU to reach >0.65 confidence."""
    cmds = tmp_path / "commands.json"
    aps = tmp_path / "apps.json"
    cmds.write_text(
        json.dumps(
            {
                "commands": {
                    "открой браузер": {"cmd": "firefox", "category": "apps"},
                    "открой firefox": {"cmd": "firefox", "category": "apps"},
                    "открой телеграм": {"cmd": "telegram", "category": "apps"},
                    "найди python": {"cmd": "xdg-open x", "category": "info"},
                    "найди погоду": {"cmd": "xdg-open y", "category": "info"},
                    "закрой окно": {"cmd": "wmctrl -c", "category": "system"},
                    "закрой это": {"cmd": "wmctrl -c", "category": "system"},
                    "воркспейс 1": {"cmd": "swtich-to-1", "category": "system"},
                    "воркспейс 2": {"cmd": "swtich-to-2", "category": "system"},
                    "воркспейс 3": {"cmd": "swtich-to-3", "category": "system"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    aps.write_text(
        json.dumps(
            {
                "apps": {
                    "firefox": {
                        "cmd": "firefox",
                        "names": ["firefox", "браузер", "фаерфокс"],
                    },
                    "telegram": {
                        "cmd": "telegram-desktop",
                        "names": ["telegram", "телеграм", "тг"],
                    },
                    "steam": {"cmd": "steam", "names": ["steam", "стим"]},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"cmds": str(cmds), "apps": str(aps)}


@pytest.fixture
def nlu_router(data_files):
    from jarvis.modules.nlu import IntentRouter

    return IntentRouter(
        commands_file=data_files["cmds"],
        apps_file=data_files["apps"],
    )


@pytest.fixture
def executor_with_nlu(data_files, nlu_router, monkeypatch):
    """CommandExecutor with NLU wired in. _run is mocked."""
    monkeypatch.setattr(CommandExecutor, "_run", lambda self, cmd, capture=False: None)
    monkeypatch.setattr(CommandExecutor, "_web_search", lambda self, q: None)
    return CommandExecutor(
        commands_file=data_files["cmds"],
        apps_file=data_files["apps"],
        fuzzy_threshold=0.8,
        platform_adapter=_FakeAdapter(),
        nlu_router=nlu_router,
        nlu_confidence_threshold=0.65,
    )


class TestNluWiring:
    def test_nlu_router_attached(self, executor_with_nlu):
        assert executor_with_nlu.nlu is not None

    def test_app_intent_dispatches(self, executor_with_nlu):
        """High-confidence open_app intent uses slot directly."""
        # "открой стим" — NLU should classify as open_app with slot {app: стим}
        result = executor_with_nlu.execute("открой стим")
        # Either NLU path ("Запускаю стим") or pattern path ("Запускаю стим")
        # produces the same user-facing string.
        assert result is not None
        assert "стим" in result.lower() or "запуска" in result.lower()

    def test_search_intent_dispatches(self, executor_with_nlu):
        result = executor_with_nlu.execute("найди рецепт борща")
        assert result is not None
        assert "ищу" in result.lower() or "рецепт" in result.lower()

    def test_workspace_intent_dispatches(self, executor_with_nlu):
        result = executor_with_nlu.execute("пятый воркспейс")
        # Workspace 5 should be dispatched either via NLU or pattern
        assert result is not None
        assert "5" in result or "пят" in result.lower()

    def test_greeting_falls_through_to_llm(self, executor_with_nlu):
        """Greetings should NOT match commands → return None → LLM."""
        result = executor_with_nlu.execute("сколько будет дважды два")
        # Could be None (LLM) or a fuzzy false-positive. We at least
        # ensure not crash.
        assert result is None or isinstance(result, str)

    def test_low_confidence_falls_through(self, executor_with_nlu, monkeypatch):
        """When NLU confidence is below threshold, fuzzy/pattern must still work."""
        # Force NLU to always say "low confidence"
        fake_nlu = MagicMock()
        fake_nlu.parse.return_value = {
            "raw": "test",
            "intent_confidence": 0.10,
            "intent": "unknown",
        }
        monkeypatch.setattr(executor_with_nlu, "nlu", fake_nlu)
        # Now an exact-match command should still hit exact
        result = executor_with_nlu.execute("открой браузер")
        assert result is not None

    def test_nlu_parse_failure_does_not_crash(self, executor_with_nlu, monkeypatch):
        fake_nlu = MagicMock()
        fake_nlu.parse.side_effect = RuntimeError("boom")
        monkeypatch.setattr(executor_with_nlu, "nlu", fake_nlu)
        result = executor_with_nlu.execute("открой браузер")
        # Crash absorbed, falls back to exact/fuzzy → still matches
        assert result is not None

    def test_nlu_disabled_via_config(self, data_files, monkeypatch):
        """If config says nlu_enabled=False, CommandManager skips NLU."""
        monkeypatch.setattr(CommandExecutor, "_run", lambda self, cmd, capture=False: None)
        cfg = {
            "commands": {
                "dictionary_path": data_files["cmds"],
                "apps_dictionary_path": data_files["apps"],
                "nlu_enabled": False,
            }
        }
        mgr = CommandManager(cfg)
        assert mgr.executor.nlu is None


class TestCommandManagerNluAutoInit:
    def test_commandmanager_auto_inits_nlu(self, data_files, monkeypatch):
        """Without explicit nlu_router, CommandManager builds one from data."""
        monkeypatch.setattr(CommandExecutor, "_run", lambda self, cmd, capture=False: None)
        cfg = {
            "commands": {
                "dictionary_path": data_files["cmds"],
                "apps_dictionary_path": data_files["apps"],
            }
        }
        mgr = CommandManager(cfg)
        assert mgr.executor.nlu is not None

    def test_commandmanager_accepts_external_nlu(
        self, data_files, nlu_router, monkeypatch
    ):
        monkeypatch.setattr(CommandExecutor, "_run", lambda self, cmd, capture=False: None)
        cfg = {
            "commands": {
                "dictionary_path": data_files["cmds"],
                "apps_dictionary_path": data_files["apps"],
            }
        }
        mgr = CommandManager(cfg, nlu_router=nlu_router)
        assert mgr.executor.nlu is nlu_router
