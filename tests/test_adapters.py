"""
Тесты для платформенных адаптеров (jarvis/adapters/).
"""

import inspect
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
    "workspace_switch", "workspace_next", "workspace_prev",
    "window_close", "window_fullscreen", "window_minimize",
    "window_maximize", "window_floating", "window_next", "window_prev",
    "screenshot_screen", "screenshot_area", "screenshot_window",
    "volume_up", "volume_down", "volume_mute", "volume_unmute",
    "lock_screen",
]

INHERITED_METHODS = [
    "system_reboot", "system_shutdown", "notify", "input_text",
    "get_terminal", "get_file_manager", "get_task_manager",
]


class TestAdapterInterface:

    @pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
    @pytest.mark.parametrize("method", MANDATORY_METHODS)
    def test_mandatory_method_exists(self, adapter_name, method):
        adapter = _get_adapter(adapter_name)
        assert hasattr(adapter, method), f"{adapter_name} missing {method}"
        assert callable(getattr(adapter, method)), f"{adapter_name}.{method} not callable"

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
    def test_system_shutdown(self, adapter_name):
        adapter = _get_adapter(adapter_name)
        result = adapter.system_shutdown()
        assert isinstance(result, str)
        assert len(result) > 0
        if adapter_name != "macos":
            assert "poweroff" in result.lower() or "shutdown" in result.lower()
        else:
            assert "shut" in result.lower()
