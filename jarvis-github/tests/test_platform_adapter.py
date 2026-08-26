"""
Тесты для platform_adapter.py.
"""

from unittest.mock import patch


class TestDetectOS:
    def test_detect_os_linux(self):
        with patch(
            "jarvis.modules.platform_adapter.platform.system", return_value="Linux"
        ):
            from jarvis.modules.platform_adapter import detect_os

            assert detect_os() == "linux"

    def test_detect_os_macos(self):
        with patch(
            "jarvis.modules.platform_adapter.platform.system", return_value="Darwin"
        ):
            from jarvis.modules.platform_adapter import detect_os

            assert detect_os() == "macos"

    def test_detect_os_windows(self):
        with patch(
            "jarvis.modules.platform_adapter.platform.system", return_value="Windows"
        ):
            from jarvis.modules.platform_adapter import detect_os

            assert detect_os() == "windows"

    def test_detect_os_unknown(self):
        with patch(
            "jarvis.modules.platform_adapter.platform.system", return_value="SomeOS"
        ):
            from jarvis.modules.platform_adapter import detect_os

            assert detect_os() == "unknown"


class TestGetAdapterClass:
    def test_get_adapter_class_hyprland(self):
        from jarvis.modules.platform_adapter import get_adapter_class
        from jarvis.adapters.hyprland import HyprlandAdapter

        assert get_adapter_class("hyprland") is HyprlandAdapter

    def test_get_adapter_class_macos(self):
        from jarvis.modules.platform_adapter import get_adapter_class
        from jarvis.adapters.macos import MacOSAdapter

        assert get_adapter_class("macos") is MacOSAdapter

    def test_get_adapter_class_kde(self):
        from jarvis.modules.platform_adapter import get_adapter_class
        from jarvis.adapters.kde import KDEAdapter

        assert get_adapter_class("kde") is KDEAdapter

    def test_get_adapter_class_gnome(self):
        from jarvis.modules.platform_adapter import get_adapter_class
        from jarvis.adapters.gnome import GNOMEAdapter

        assert get_adapter_class("gnome") is GNOMEAdapter

    def test_get_adapter_class_i3(self):
        from jarvis.modules.platform_adapter import get_adapter_class
        from jarvis.adapters.i3 import I3Adapter

        assert get_adapter_class("i3") is I3Adapter

    def test_get_adapter_class_sway(self):
        from jarvis.modules.platform_adapter import get_adapter_class
        from jarvis.adapters.sway import SwayAdapter

        assert get_adapter_class("sway") is SwayAdapter

    def test_get_adapter_class_unknown_returns_fallback(self):
        from jarvis.modules.platform_adapter import get_adapter_class
        from jarvis.adapters.base import BaseAdapter

        cls = get_adapter_class("unknown_de")
        assert issubclass(cls, BaseAdapter)


class TestDetectDeProcessList:
    """P7+P11: detect_de must be testable via mocked process list, без
    зависимости от env переменных и реальных команд."""

    def _detect(self, processes):
        from jarvis.modules.platform_adapter import detect_de

        return detect_de(actual_processes=processes)

    def test_sway(self):
        assert self._detect(["sway", "waybar", "swayidle"]) == "sway"

    def test_i3(self):
        assert self._detect(["i3", "i3status", "i3bar"]) == "i3"

    def test_i3_with_only_i3status_returns_unknown(self):
        # Только статусбар без i3-сервера — не определяем i3.
        assert self._detect(["i3status"]) == "unknown"

    def test_hyprland(self):
        assert self._detect(["Hyprland", "waybar"]) == "hyprland"

    def test_kde_plasmashell(self):
        assert self._detect(["plasmashell", "kwin_x11"]) == "kde"

    def test_kde_kwin_only(self):
        assert self._detect(["kwin_wayland"]) == "kde"

    def test_gnome(self):
        assert self._detect(["gnome-shell", "gjs"]) == "gnome"

    def test_macos_windowserver(self):
        assert self._detect(["WindowServer", "loginwindow"]) == "macos"

    def test_unknown_when_no_match(self):
        assert self._detect(["bash", "vim", "tmux"]) == "unknown"

    def test_empty_list(self):
        assert self._detect([]) == "unknown"


class TestDetectDeFallbackChain:
    """env → loginctl → ps — каждый шаг graceful."""

    def test_env_xdg_current_desktop_hyprland(self, monkeypatch):
        from jarvis.modules.platform_adapter import detect_de

        monkeypatch.setattr(
            "jarvis.modules.platform_adapter.detect_os",
            lambda: "linux",
        )
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Hyprland")
        monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
        assert detect_de() == "hyprland"

    def test_falls_through_to_ps_when_env_empty(self, monkeypatch):
        """Env-чек не находит — переходим к loginctl (gracefully fails)
        и потом к ps (mocked)."""
        from jarvis.modules import platform_adapter as pa

        monkeypatch.setattr(pa, "detect_os", lambda: "linux")
        for var in (
            "XDG_CURRENT_DESKTOP",
            "DESKTOP_SESSION",
            "I3SOCK",
            "SWAYSOCK",
            "HYPRLAND_INSTANCE_SIGNATURE",
        ):
            monkeypatch.delenv(var, raising=False)
        # Force loginctl to fail
        monkeypatch.setattr(pa, "_detect_de_from_session", lambda: None)
        # Force ps result
        monkeypatch.setattr(
            pa,
            "_detect_de_from_process_list",
            lambda processes=None: "sway",
        )
        assert pa.detect_de() == "sway"

    def test_macos_short_circuits(self, monkeypatch):
        from jarvis.modules import platform_adapter as pa

        monkeypatch.setattr(pa, "detect_os", lambda: "macos")
        assert pa.detect_de() == "macos"
