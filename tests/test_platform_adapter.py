"""
Тесты для platform_adapter.py.
"""

import pytest
from unittest.mock import patch


class TestDetectOS:
    def test_detect_os_linux(self):
        with patch("jarvis.modules.platform_adapter.platform.system", return_value="Linux"):
            from jarvis.modules.platform_adapter import detect_os
            assert detect_os() == "linux"

    def test_detect_os_macos(self):
        with patch("jarvis.modules.platform_adapter.platform.system", return_value="Darwin"):
            from jarvis.modules.platform_adapter import detect_os
            assert detect_os() == "macos"

    def test_detect_os_windows(self):
        with patch("jarvis.modules.platform_adapter.platform.system", return_value="Windows"):
            from jarvis.modules.platform_adapter import detect_os
            assert detect_os() == "windows"

    def test_detect_os_unknown(self):
        with patch("jarvis.modules.platform_adapter.platform.system", return_value="SomeOS"):
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
