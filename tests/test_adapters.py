"""
Тесты для платформенных адаптеров (jarvis/adapters/).
"""

import inspect
from datetime import datetime

import pytest
from jarvis.adapters.base import BaseAdapter

ALL_ADAPTERS = ["hyprland", "kde", "gnome", "i3", "sway", "macos"]


def _get_adapter(name: str) -> BaseAdapter:
    import importlib

    mod = importlib.import_module(f"jarvis.adapters.{name}")
    cls_name = {
        "hyprland": "HyprlandAdapter",
        "kde": "KDEAdapter",
        "gnome": "GNOMEAdapter",
        "i3": "I3Adapter",
        "sway": "SwayAdapter",
        "macos": "MacOSAdapter",
    }[name]
    return getattr(mod, cls_name)()


MANDATORY_METHODS = [
    "workspace_switch",
    "workspace_next",
    "workspace_prev",
    "window_close",
    "window_fullscreen",
    "window_minimize",
    "window_maximize",
    "window_floating",
    "window_next",
    "window_prev",
    "screenshot_screen",
    "screenshot_area",
    "screenshot_window",
    "volume_up",
    "volume_down",
    "volume_mute",
    "volume_unmute",
    "lock_screen",
]

INHERITED_METHODS = [
    "system_reboot",
    "system_shutdown",
    "notify",
    "input_text",
    "get_terminal",
    "get_file_manager",
    "get_task_manager",
]


class TestAdapterInterface:
    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    @pytest.mark.parametrize("method", MANDATORY_METHODS)
    def test_mandatory_method_exists(self, adapter_name, method):
        adapter = _get_adapter(adapter_name)
        assert hasattr(adapter, method), f"{adapter_name} missing {method}"
        assert callable(getattr(adapter, method)), (
            f"{adapter_name}.{method} not callable"
        )

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    @pytest.mark.parametrize("method", MANDATORY_METHODS)
    def test_mandatory_method_returns_string(self, adapter_name, method):
        adapter = _get_adapter(adapter_name)
        impl = getattr(adapter, method)
        sig = inspect.signature(impl)
        params = list(sig.parameters.values())
        args = {}
        for p in params:  # bound method — self уже привязан
            if p.default is inspect.Parameter.empty:
                args[p.name] = 1 if p.annotation is int else "test"
            else:
                args[p.name] = p.default
        result = impl(**args)
        assert isinstance(result, str), f"{adapter_name}.{method} should return str"

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    @pytest.mark.parametrize("method", INHERITED_METHODS)
    def test_inherited_method_exists(self, adapter_name, method):
        adapter = _get_adapter(adapter_name)
        assert hasattr(adapter, method), f"{adapter_name} missing {method}"

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    @pytest.mark.parametrize("method", INHERITED_METHODS)
    def test_inherited_method_returns_string(self, adapter_name, method):
        adapter = _get_adapter(adapter_name)
        impl = getattr(adapter, method)
        sig = inspect.signature(impl)
        params = list(sig.parameters.values())
        args = {}
        for p in params:  # bound method — self уже привязан
            if p.default is inspect.Parameter.empty:
                args[p.name] = "test" if p.annotation is str else 1
            else:
                args[p.name] = p.default
        result = impl(**args)
        assert isinstance(result, str)

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    def test_adapter_has_name(self, adapter_name):
        adapter = _get_adapter(adapter_name)
        assert hasattr(adapter, "name")
        assert isinstance(adapter.name, str)
        assert adapter.name == adapter_name


class TestNewMethods:
    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    def test_notify_format(self, adapter_name):
        adapter = _get_adapter(adapter_name)
        result = adapter.notify("Заголовок", "Текст")
        assert isinstance(result, str)
        assert len(result) > 0
        if adapter_name == "macos":
            assert "osascript" in result
        else:
            assert "notify-send" in result

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    def test_input_text_format(self, adapter_name):
        adapter = _get_adapter(adapter_name)
        result = adapter.input_text("Привет мир")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    def test_system_reboot(self, adapter_name):
        adapter = _get_adapter(adapter_name)
        result = adapter.system_reboot()
        assert isinstance(result, str)
        assert len(result) > 0
        if adapter_name != "macos":
            assert "reboot" in result.lower() or "restart" in result.lower()
        else:
            assert "restart" in result.lower()

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    def test_screenshot_path_is_resolved_per_call(self, adapter_name):
        """Каждый вызов screenshot_screen должен возвращать строку без shell
        substitutions ($(date), ~) — иначе shell=False создаст файл с
        литералом '$(date...)' в имени, и screenshot не сохранится."""
        import re

        adapter = _get_adapter(adapter_name)
        result = adapter.screenshot_screen()
        # Команды могут вернуть "" если внешний инструмент отсутствует
        # (sway/slurp на macOS) — это допустимо.
        if not result:
            return
        assert "$(date" not in result, (
            f"{adapter_name} leaks $(date) — shell=False won't expand it"
        )
        assert not re.search(r"(^|\s)~/", result), (
            f"{adapter_name} leaks ~ — shell=False won't expand it"
        )
        # И сам timestamp должен присутствовать в имени файла, если адаптер
        # пишет в файл (некоторые, как hyprland's grimblast и kde's spectacle,
        # сами генерируют имя и timestamp в команде не нужен).
        if any(
            tool in result
            for tool in ("scrot", "grim ", "gnome-screenshot", "screencapture")
        ):
            today = datetime.now().strftime("%Y%m%d")
            assert today in result, (
                f"{adapter_name} screenshot path missing today's date"
            )

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    def test_system_shutdown(self, adapter_name):
        adapter = _get_adapter(adapter_name)
        result = adapter.system_shutdown()
        assert isinstance(result, str)
        assert len(result) > 0
        if adapter_name != "macos":
            assert "poweroff" in result.lower() or "shutdown" in result.lower()
        else:
            assert "shut" in result.lower()


class TestMacOSSpecificCommands:
    def test_macos_screenshot_screen_no_clipboard_flag(self):
        adapter = _get_adapter("macos")
        res = adapter.screenshot_screen()
        assert "screencapture" in res
        assert "-c" not in res.split()

    def test_macos_lock_screen_pmset(self):
        adapter = _get_adapter("macos")
        res = adapter.lock_screen()
        assert res == "pmset displaysleepnow"


class TestWave4AdaptersRegression:
    def test_kde_qdbus_fallback(self, monkeypatch):
        import shutil
        from jarvis.adapters.kde import KDEAdapter

        # Case 1: qdbus exists
        monkeypatch.setattr(
            shutil,
            "which",
            lambda cmd: "/usr/bin/qdbus" if cmd == "qdbus" else None,
        )
        adapter = KDEAdapter()
        assert adapter.workspace_switch(2).startswith("qdbus ")

        # Case 2: only qdbus6 exists
        monkeypatch.setattr(
            shutil,
            "which",
            lambda cmd: "/usr/bin/qdbus6" if cmd == "qdbus6" else None,
        )
        adapter = KDEAdapter()
        assert adapter.workspace_switch(2).startswith("qdbus6 ")

        # Case 3: only qdbus-qt6 exists
        monkeypatch.setattr(
            shutil,
            "which",
            lambda cmd: "/usr/bin/qdbus-qt6" if cmd == "qdbus-qt6" else None,
        )
        adapter = KDEAdapter()
        assert adapter.workspace_switch(2).startswith("qdbus-qt6 ")

        # Case 4: none exists -> defaults to qdbus
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        adapter = KDEAdapter()
        assert adapter.workspace_switch(2).startswith("qdbus ")

    def test_hyprland_screenshot_grimblast_and_grim_fallback(self, monkeypatch):
        import shutil
        from jarvis.adapters.hyprland import HyprlandAdapter

        # Case 1: grimblast exists
        monkeypatch.setattr(
            shutil,
            "which",
            lambda cmd: "/usr/bin/grimblast" if cmd == "grimblast" else None,
        )
        adapter = HyprlandAdapter()
        assert adapter.screenshot_screen() == "grimblast copy screen"
        assert adapter.screenshot_area() == "grimblast copy area"
        assert adapter.screenshot_window() == "grimblast copy active"

        # Case 2: grimblast missing, grim available
        monkeypatch.setattr(
            shutil,
            "which",
            lambda cmd: "/usr/bin/grim" if cmd == "grim" else None,
        )
        adapter = HyprlandAdapter()
        screen_cmd = adapter.screenshot_screen()
        assert screen_cmd.startswith("grim ")
        assert "grimblast" not in screen_cmd

    def test_window_floating_kde_and_gnome_no_false_echo(self):
        from jarvis.adapters.kde import KDEAdapter
        from jarvis.adapters.gnome import GNOMEAdapter

        kde = KDEAdapter()
        gnome = GNOMEAdapter()

        # Must not return echo with exit code 0
        assert "echo" not in kde.window_floating()
        assert "echo" not in gnome.window_floating()
        assert kde.window_floating() == "false"
        assert gnome.window_floating() == "false"
