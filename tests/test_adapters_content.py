"""
Content tests for all platform adapters.
Verifies every method returns the EXACT expected command string.

6 adapters × 25 methods = 150+ parametrized test cases.
"""

import os

import pytest

from jarvis.adapters.base import BaseAdapter
from jarvis.adapters.i3 import I3Adapter
from jarvis.adapters.sway import SwayAdapter
from jarvis.adapters.hyprland import HyprlandAdapter
from jarvis.adapters.gnome import GNOMEAdapter
from jarvis.adapters.kde import KDEAdapter
from jarvis.adapters.macos import MacOSAdapter


# In the post-P2 refactor, adapter screenshot methods resolve `~` and the
# timestamp in Python (see AGENTS.md), so expected strings use the expanded
# home path here.
_SHOT_DIR = os.path.expanduser("~/Pictures/screenshot-")


# ─── Helpers ────────────────────────────────────────────────────────────────


def _normalize(cmd: str) -> str:
    """Collapse multiple spaces for consistent comparison."""
    import re

    return re.sub(r" +", " ", cmd).strip()


# ─── Test data: (adapter_cls, method, kwargs, expected_or_prefix, exact) ───
# exact=True  → assert result == expected_or_prefix
# exact=False → assert result.startswith(expected_or_prefix)


def _t():
    """Build test cases for all adapters."""
    cases = []

    # ---- i3 ----
    i3 = I3Adapter
    cases.extend(
        [
            # Workspace
            pytest.param(
                i3,
                "workspace_switch",
                {"number": 3},
                "i3-msg workspace 3",
                True,
                id="i3-workspace_switch",
            ),
            pytest.param(
                i3,
                "workspace_switch",
                {"number": 10},
                "i3-msg workspace 10",
                True,
                id="i3-workspace_switch_10",
            ),
            pytest.param(
                i3,
                "workspace_next",
                {},
                "i3-msg workspace next",
                True,
                id="i3-workspace_next",
            ),
            pytest.param(
                i3,
                "workspace_prev",
                {},
                "i3-msg workspace prev",
                True,
                id="i3-workspace_prev",
            ),
            # Window
            pytest.param(
                i3, "window_close", {}, "i3-msg kill", True, id="i3-window_close"
            ),
            pytest.param(
                i3,
                "window_fullscreen",
                {},
                "i3-msg fullscreen toggle",
                True,
                id="i3-window_fullscreen",
            ),
            pytest.param(
                i3,
                "window_minimize",
                {},
                "i3-msg move scratchpad",
                True,
                id="i3-window_minimize",
            ),
            pytest.param(
                i3,
                "window_maximize",
                {},
                "i3-msg fullscreen enable",
                True,
                id="i3-window_maximize",
            ),
            pytest.param(
                i3,
                "window_floating",
                {},
                "i3-msg floating toggle",
                True,
                id="i3-window_floating",
            ),
            pytest.param(
                i3, "window_next", {}, "i3-msg focus right", True, id="i3-window_next"
            ),
            pytest.param(
                i3, "window_prev", {}, "i3-msg focus left", True, id="i3-window_prev"
            ),
            # Screenshots (prefix check because of $(date ...))
            pytest.param(
                i3,
                "screenshot_screen",
                {},
                "scrot " + _SHOT_DIR,
                False,
                id="i3-screenshot_screen",
            ),
            pytest.param(
                i3,
                "screenshot_area",
                {},
                "scrot -s " + _SHOT_DIR,
                False,
                id="i3-screenshot_area",
            ),
            pytest.param(
                i3,
                "screenshot_window",
                {},
                "scrot -u " + _SHOT_DIR,
                False,
                id="i3-screenshot_window",
            ),
            # Volume
            pytest.param(
                i3,
                "volume_up",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ +5%",
                True,
                id="i3-volume_up",
            ),
            pytest.param(
                i3,
                "volume_up",
                {"amount": 10},
                "pactl set-sink-volume @DEFAULT_SINK@ +10%",
                True,
                id="i3-volume_up_10",
            ),
            pytest.param(
                i3,
                "volume_down",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ -5%",
                True,
                id="i3-volume_down",
            ),
            pytest.param(
                i3,
                "volume_down",
                {"amount": 3},
                "pactl set-sink-volume @DEFAULT_SINK@ -3%",
                True,
                id="i3-volume_down_3",
            ),
            pytest.param(
                i3,
                "volume_mute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ toggle",
                True,
                id="i3-volume_mute",
            ),
            pytest.param(
                i3,
                "volume_unmute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ 0",
                True,
                id="i3-volume_unmute",
            ),
            # System
            pytest.param(i3, "lock_screen", {}, "i3lock", True, id="i3-lock_screen"),
            pytest.param(
                i3, "system_reboot", {}, "reboot", True, id="i3-system_reboot"
            ),
            pytest.param(
                i3, "system_shutdown", {}, "poweroff", True, id="i3-system_shutdown"
            ),
            # Notifications
            pytest.param(
                i3,
                "notify",
                {"title": "Hello", "message": "World"},
                "notify-send -u normal 'Hello' 'World'",
                True,
                id="i3-notify",
            ),
            pytest.param(
                i3,
                "notify",
                {"title": "it's", "message": "test's"},
                "notify-send -u normal 'it'\\''s' 'test'\\''s'",
                True,
                id="i3-notify_escape",
            ),
            # Text input
            pytest.param(
                i3,
                "input_text",
                {"text": "hello"},
                "wtype 'hello' 2>/dev/null || xdotool type 'hello' 2>/dev/null || echo 'input_text: hello'",
                True,
                id="i3-input_text",
            ),
            pytest.param(
                i3,
                "input_text",
                {"text": "it's fine"},
                "wtype 'it'\\''s fine' 2>/dev/null || xdotool type 'it'\\''s fine' 2>/dev/null || echo 'input_text: it'\\''s fine'",
                True,
                id="i3-input_text_escape",
            ),
            # Apps
            pytest.param(
                i3,
                "get_terminal",
                {},
                "i3-sensible-terminal",
                True,
                id="i3-get_terminal",
            ),
            pytest.param(
                i3, "get_file_manager", {}, "pcmanfm", True, id="i3-get_file_manager"
            ),
            pytest.param(
                i3,
                "get_task_manager",
                {},
                "i3-sensible-terminal -e htop",
                True,
                id="i3-get_task_manager",
            ),
        ]
    )

    # ---- Sway ----
    sway = SwayAdapter
    cases.extend(
        [
            pytest.param(
                sway,
                "workspace_switch",
                {"number": 3},
                "swaymsg workspace 3",
                True,
                id="sway-workspace_switch",
            ),
            pytest.param(
                sway,
                "workspace_next",
                {},
                "swaymsg workspace next",
                True,
                id="sway-workspace_next",
            ),
            pytest.param(
                sway,
                "workspace_prev",
                {},
                "swaymsg workspace prev",
                True,
                id="sway-workspace_prev",
            ),
            pytest.param(
                sway, "window_close", {}, "swaymsg kill", True, id="sway-window_close"
            ),
            pytest.param(
                sway,
                "window_fullscreen",
                {},
                "swaymsg fullscreen toggle",
                True,
                id="sway-window_fullscreen",
            ),
            pytest.param(
                sway,
                "window_minimize",
                {},
                "swaymsg move scratchpad",
                True,
                id="sway-window_minimize",
            ),
            pytest.param(
                sway,
                "window_maximize",
                {},
                "swaymsg fullscreen enable",
                True,
                id="sway-window_maximize",
            ),
            pytest.param(
                sway,
                "window_floating",
                {},
                "swaymsg floating toggle",
                True,
                id="sway-window_floating",
            ),
            pytest.param(
                sway,
                "window_next",
                {},
                "swaymsg focus next",
                True,
                id="sway-window_next",
            ),
            pytest.param(
                sway,
                "window_prev",
                {},
                "swaymsg focus prev",
                True,
                id="sway-window_prev",
            ),
            pytest.param(
                sway,
                "screenshot_screen",
                {},
                "grim " + _SHOT_DIR,
                False,
                id="sway-screenshot_screen",
            ),
            pytest.param(
                sway,
                "screenshot_area",
                {},
                "grim -g '100,100 500x400' " + _SHOT_DIR,
                False,
                id="sway-screenshot_area",
            ),
            pytest.param(
                sway,
                "screenshot_window",
                {},
                "grim -g '0,0 1920x1080' " + _SHOT_DIR,
                False,
                id="sway-screenshot_window",
            ),
            pytest.param(
                sway,
                "volume_up",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ +5%",
                True,
                id="sway-volume_up",
            ),
            pytest.param(
                sway,
                "volume_down",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ -5%",
                True,
                id="sway-volume_down",
            ),
            pytest.param(
                sway,
                "volume_mute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ toggle",
                True,
                id="sway-volume_mute",
            ),
            pytest.param(
                sway,
                "volume_unmute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ 0",
                True,
                id="sway-volume_unmute",
            ),
            pytest.param(
                sway, "lock_screen", {}, "swaylock", True, id="sway-lock_screen"
            ),
            pytest.param(
                sway, "system_reboot", {}, "reboot", True, id="sway-system_reboot"
            ),
            pytest.param(
                sway, "system_shutdown", {}, "poweroff", True, id="sway-system_shutdown"
            ),
            pytest.param(
                sway,
                "notify",
                {"title": "Hello", "message": "World"},
                "notify-send -u normal 'Hello' 'World'",
                True,
                id="sway-notify",
            ),
            pytest.param(
                sway,
                "input_text",
                {"text": "hello"},
                "wtype 'hello' 2>/dev/null || xdotool type 'hello' 2>/dev/null || echo 'input_text: hello'",
                True,
                id="sway-input_text",
            ),
            pytest.param(
                sway, "get_terminal", {}, "foot", True, id="sway-get_terminal"
            ),
            pytest.param(
                sway,
                "get_file_manager",
                {},
                "pcmanfm",
                True,
                id="sway-get_file_manager",
            ),
            pytest.param(
                sway,
                "get_task_manager",
                {},
                "foot -e htop",
                True,
                id="sway-get_task_manager",
            ),
        ]
    )

    # ---- Hyprland ----
    hypr = HyprlandAdapter
    cases.extend(
        [
            pytest.param(
                hypr,
                "workspace_switch",
                {"number": 3},
                "hyprctl dispatch workspace 3",
                True,
                id="hyprland-workspace_switch",
            ),
            pytest.param(
                hypr,
                "workspace_next",
                {},
                "hyprctl dispatch workspace e+1",
                True,
                id="hyprland-workspace_next",
            ),
            pytest.param(
                hypr,
                "workspace_prev",
                {},
                "hyprctl dispatch workspace e-1",
                True,
                id="hyprland-workspace_prev",
            ),
            pytest.param(
                hypr,
                "window_close",
                {},
                "hyprctl dispatch killactive",
                True,
                id="hyprland-window_close",
            ),
            pytest.param(
                hypr,
                "window_fullscreen",
                {},
                "hyprctl dispatch fullscreen",
                True,
                id="hyprland-window_fullscreen",
            ),
            pytest.param(
                hypr,
                "window_minimize",
                {},
                "hyprctl dispatch movetoworkspacesilent special",
                True,
                id="hyprland-window_minimize",
            ),
            pytest.param(
                hypr,
                "window_maximize",
                {},
                "hyprctl dispatch fullscreen 1",
                True,
                id="hyprland-window_maximize",
            ),
            pytest.param(
                hypr,
                "window_floating",
                {},
                "hyprctl dispatch togglefloating",
                True,
                id="hyprland-window_floating",
            ),
            pytest.param(
                hypr,
                "window_next",
                {},
                "hyprctl dispatch cyclenext",
                True,
                id="hyprland-window_next",
            ),
            pytest.param(
                hypr,
                "window_prev",
                {},
                "hyprctl dispatch cyclenext prev",
                True,
                id="hyprland-window_prev",
            ),
            pytest.param(
                hypr,
                "screenshot_screen",
                {},
                "grimblast copy screen",
                True,
                id="hyprland-screenshot_screen",
            ),
            pytest.param(
                hypr,
                "screenshot_area",
                {},
                "grimblast copy area",
                True,
                id="hyprland-screenshot_area",
            ),
            pytest.param(
                hypr,
                "screenshot_window",
                {},
                "grimblast copy active",
                True,
                id="hyprland-screenshot_window",
            ),
            pytest.param(
                hypr,
                "volume_up",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ +5%",
                True,
                id="hyprland-volume_up",
            ),
            pytest.param(
                hypr,
                "volume_down",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ -5%",
                True,
                id="hyprland-volume_down",
            ),
            pytest.param(
                hypr,
                "volume_mute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ toggle",
                True,
                id="hyprland-volume_mute",
            ),
            pytest.param(
                hypr,
                "volume_unmute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ 0",
                True,
                id="hyprland-volume_unmute",
            ),
            pytest.param(
                hypr, "lock_screen", {}, "hyprlock", True, id="hyprland-lock_screen"
            ),
            pytest.param(
                hypr, "system_reboot", {}, "reboot", True, id="hyprland-system_reboot"
            ),
            pytest.param(
                hypr,
                "system_shutdown",
                {},
                "poweroff",
                True,
                id="hyprland-system_shutdown",
            ),
            pytest.param(
                hypr,
                "notify",
                {"title": "Hello", "message": "World"},
                "notify-send -u normal 'Hello' 'World'",
                True,
                id="hyprland-notify",
            ),
            pytest.param(
                hypr,
                "input_text",
                {"text": "hello"},
                "wtype 'hello' 2>/dev/null || xdotool type 'hello' 2>/dev/null || echo 'input_text: hello'",
                True,
                id="hyprland-input_text",
            ),
            pytest.param(
                hypr, "get_terminal", {}, "kitty", True, id="hyprland-get_terminal"
            ),
            pytest.param(
                hypr,
                "get_file_manager",
                {},
                "thunar",
                True,
                id="hyprland-get_file_manager",
            ),
            pytest.param(
                hypr,
                "get_task_manager",
                {},
                "kitty -e btop",
                True,
                id="hyprland-get_task_manager",
            ),
        ]
    )

    # ---- GNOME ----
    # Eval закрыт с GNOME 41 (см. комментарий в gnome.py): окна/воркспейсы
    # через EWMH/xdotool, скриншоты через незакрытый org.gnome.Shell.Screenshot.
    gnome = GNOMEAdapter
    cases.extend(
        [
            pytest.param(
                gnome,
                "workspace_switch",
                {"number": 1},
                "wmctrl -s 0",
                True,
                id="gnome-workspace_switch_1",
            ),
            pytest.param(
                gnome,
                "workspace_switch",
                {"number": 3},
                "wmctrl -s 2",
                True,
                id="gnome-workspace_switch_3",
            ),
            pytest.param(
                gnome,
                "workspace_next",
                {},
                "xdotool key ctrl+alt+Right",
                True,
                id="gnome-workspace_next",
            ),
            pytest.param(
                gnome,
                "workspace_prev",
                {},
                "xdotool key ctrl+alt+Left",
                True,
                id="gnome-workspace_prev",
            ),
            pytest.param(
                gnome,
                "window_close",
                {},
                "xdotool key alt+F4",
                True,
                id="gnome-window_close",
            ),
            pytest.param(
                gnome,
                "window_fullscreen",
                {},
                "xdotool key F11",
                True,
                id="gnome-window_fullscreen",
            ),
            pytest.param(
                gnome,
                "window_minimize",
                {},
                "xdotool key super+h",
                True,
                id="gnome-window_minimize",
            ),
            pytest.param(
                gnome,
                "window_maximize",
                {},
                "xdotool key alt+F10",
                True,
                id="gnome-window_maximize",
            ),
            pytest.param(
                gnome,
                "window_floating",
                {},
                "echo 'Floating windows not supported on GNOME'",
                True,
                id="gnome-window_floating",
            ),
            pytest.param(
                gnome,
                "window_next",
                {},
                "xdotool key alt+Escape",
                True,
                id="gnome-window_next",
            ),
            pytest.param(
                gnome,
                "window_prev",
                {},
                "xdotool key alt+shift+Escape",
                True,
                id="gnome-window_prev",
            ),
            pytest.param(
                gnome,
                "screenshot_screen",
                {},
                "xdotool key Print",
                True,
                id="gnome-screenshot_screen",
            ),
            pytest.param(
                gnome,
                "screenshot_area",
                {},
                "xdotool key Print",
                True,
                id="gnome-screenshot_area",
            ),
            pytest.param(
                gnome,
                "screenshot_window",
                {},
                "xdotool key Print",
                True,
                id="gnome-screenshot_window",
            ),
            pytest.param(
                gnome,
                "volume_up",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ +5%",
                True,
                id="gnome-volume_up",
            ),
            pytest.param(
                gnome,
                "volume_down",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ -5%",
                True,
                id="gnome-volume_down",
            ),
            pytest.param(
                gnome,
                "volume_mute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ toggle",
                True,
                id="gnome-volume_mute",
            ),
            pytest.param(
                gnome,
                "volume_unmute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ 0",
                True,
                id="gnome-volume_unmute",
            ),
            pytest.param(
                gnome,
                "lock_screen",
                {},
                "loginctl lock-session",
                True,
                id="gnome-lock_screen",
            ),
            pytest.param(
                gnome, "system_reboot", {}, "reboot", True, id="gnome-system_reboot"
            ),
            pytest.param(
                gnome,
                "system_shutdown",
                {},
                "poweroff",
                True,
                id="gnome-system_shutdown",
            ),
            pytest.param(
                gnome,
                "notify",
                {"title": "Hello", "message": "World"},
                "notify-send -u normal 'Hello' 'World'",
                True,
                id="gnome-notify",
            ),
            pytest.param(
                gnome,
                "input_text",
                {"text": "hello"},
                "wtype 'hello' 2>/dev/null || xdotool type 'hello' 2>/dev/null || echo 'input_text: hello'",
                True,
                id="gnome-input_text",
            ),
            pytest.param(
                gnome,
                "get_terminal",
                {},
                "gnome-terminal",
                True,
                id="gnome-get_terminal",
            ),
            pytest.param(
                gnome,
                "get_file_manager",
                {},
                "nautilus",
                True,
                id="gnome-get_file_manager",
            ),
            pytest.param(
                gnome,
                "get_task_manager",
                {},
                "gnome-system-monitor",
                True,
                id="gnome-get_task_manager",
            ),
        ]
    )

    # ---- KDE ----
    kde = KDEAdapter
    cases.extend(
        [
            pytest.param(
                kde,
                "workspace_switch",
                {"number": 3},
                "qdbus org.kde.KWin /KWin setCurrentDesktop 3",
                True,
                id="kde-workspace_switch",
            ),
            pytest.param(
                kde,
                "workspace_next",
                {},
                "qdbus org.kde.KWin /KWin nextDesktop",
                True,
                id="kde-workspace_next",
            ),
            pytest.param(
                kde,
                "workspace_prev",
                {},
                "qdbus org.kde.KWin /KWin previousDesktop",
                True,
                id="kde-workspace_prev",
            ),
            pytest.param(
                kde,
                "window_close",
                {},
                "qdbus org.kde.KWin /KWin killWindow",
                True,
                id="kde-window_close",
            ),
            pytest.param(
                kde,
                "window_fullscreen",
                {},
                "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Window Fullscreen'",
                True,
                id="kde-window_fullscreen",
            ),
            pytest.param(
                kde,
                "window_minimize",
                {},
                "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Window Minimize'",
                True,
                id="kde-window_minimize",
            ),
            pytest.param(
                kde,
                "window_maximize",
                {},
                "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Window Maximize'",
                True,
                id="kde-window_maximize",
            ),
            pytest.param(
                kde,
                "window_floating",
                {},
                "echo 'Floating windows not supported on KDE'",
                True,
                id="kde-window_floating",
            ),
            pytest.param(
                kde,
                "window_next",
                {},
                "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Walk Through Windows'",
                True,
                id="kde-window_next",
            ),
            pytest.param(
                kde,
                "window_prev",
                {},
                "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Walk Through Windows (Reverse)'",
                True,
                id="kde-window_prev",
            ),
            pytest.param(
                kde,
                "screenshot_screen",
                {},
                "spectacle -f -b -n",
                True,
                id="kde-screenshot_screen",
            ),
            pytest.param(
                kde,
                "screenshot_area",
                {},
                "spectacle -r -b -n",
                True,
                id="kde-screenshot_area",
            ),
            pytest.param(
                kde,
                "screenshot_window",
                {},
                "spectacle -a -b -n",
                True,
                id="kde-screenshot_window",
            ),
            pytest.param(
                kde,
                "volume_up",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ +5%",
                True,
                id="kde-volume_up",
            ),
            pytest.param(
                kde,
                "volume_down",
                {"amount": 5},
                "pactl set-sink-volume @DEFAULT_SINK@ -5%",
                True,
                id="kde-volume_down",
            ),
            pytest.param(
                kde,
                "volume_mute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ toggle",
                True,
                id="kde-volume_mute",
            ),
            pytest.param(
                kde,
                "volume_unmute",
                {},
                "pactl set-sink-mute @DEFAULT_SINK@ 0",
                True,
                id="kde-volume_unmute",
            ),
            pytest.param(
                kde,
                "lock_screen",
                {},
                "loginctl lock-session",
                True,
                id="kde-lock_screen",
            ),
            pytest.param(
                kde, "system_reboot", {}, "reboot", True, id="kde-system_reboot"
            ),
            pytest.param(
                kde, "system_shutdown", {}, "poweroff", True, id="kde-system_shutdown"
            ),
            pytest.param(
                kde,
                "notify",
                {"title": "Hello", "message": "World"},
                "notify-send -u normal 'Hello' 'World'",
                True,
                id="kde-notify",
            ),
            pytest.param(
                kde,
                "input_text",
                {"text": "hello"},
                "wtype 'hello' 2>/dev/null || xdotool type 'hello' 2>/dev/null || echo 'input_text: hello'",
                True,
                id="kde-input_text",
            ),
            pytest.param(
                kde, "get_terminal", {}, "konsole", True, id="kde-get_terminal"
            ),
            pytest.param(
                kde, "get_file_manager", {}, "dolphin", True, id="kde-get_file_manager"
            ),
            pytest.param(
                kde,
                "get_task_manager",
                {},
                "plasma-systemmonitor",
                True,
                id="kde-get_task_manager",
            ),
        ]
    )

    # ---- macOS ----
    macos = MacOSAdapter
    cases.extend(
        [
            pytest.param(
                macos,
                "workspace_switch",
                {"number": 1},
                "osascript -e 'tell application \"System Events\" to key code 18 using control down'",
                True,
                id="macos-workspace_switch_1",
            ),
            pytest.param(
                macos,
                "workspace_switch",
                {"number": 3},
                "osascript -e 'tell application \"System Events\" to key code 20 using control down'",
                True,
                id="macos-workspace_switch_3",
            ),
            pytest.param(
                macos,
                "workspace_next",
                {},
                "osascript -e 'tell application \"System Events\" to key code 124 using control down'",
                True,
                id="macos-workspace_next",
            ),
            pytest.param(
                macos,
                "workspace_prev",
                {},
                "osascript -e 'tell application \"System Events\" to key code 123 using control down'",
                True,
                id="macos-workspace_prev",
            ),
            pytest.param(
                macos,
                "window_close",
                {},
                'osascript -e \'tell application "System Events" to keystroke "w" using command down\'',
                True,
                id="macos-window_close",
            ),
            pytest.param(
                macos,
                "window_fullscreen",
                {},
                'osascript -e \'tell application "System Events" to keystroke "f" using {control down, command down}\'',
                True,
                id="macos-window_fullscreen",
            ),
            pytest.param(
                macos,
                "window_minimize",
                {},
                'osascript -e \'tell application "System Events" to keystroke "m" using command down\'',
                True,
                id="macos-window_minimize",
            ),
            pytest.param(
                macos,
                "window_floating",
                {},
                "echo 'Not supported on macOS'",
                True,
                id="macos-window_floating",
            ),
            pytest.param(
                macos,
                "window_next",
                {},
                'osascript -e \'tell application "System Events" to keystroke "`" using command down\'',
                True,
                id="macos-window_next",
            ),
            pytest.param(
                macos,
                "window_prev",
                {},
                'osascript -e \'tell application "System Events" to keystroke "`" using {command down, shift down}\'',
                True,
                id="macos-window_prev",
            ),
            pytest.param(
                macos,
                "screenshot_screen",
                {},
                "screencapture -c " + _SHOT_DIR,
                False,
                id="macos-screenshot_screen",
            ),
            pytest.param(
                macos,
                "screenshot_area",
                {},
                "screencapture -i " + _SHOT_DIR,
                False,
                id="macos-screenshot_area",
            ),
            pytest.param(
                macos,
                "screenshot_window",
                {},
                "screencapture -w " + _SHOT_DIR,
                False,
                id="macos-screenshot_window",
            ),
            pytest.param(
                macos,
                "volume_up",
                {"amount": 5},
                "osascript -e 'set volume output volume (output volume of (get volume settings) + 5)'",
                True,
                id="macos-volume_up",
            ),
            pytest.param(
                macos,
                "volume_up",
                {"amount": 10},
                "osascript -e 'set volume output volume (output volume of (get volume settings) + 10)'",
                True,
                id="macos-volume_up_10",
            ),
            pytest.param(
                macos,
                "volume_down",
                {"amount": 5},
                "osascript -e 'set volume output volume (output volume of (get volume settings) - 5)'",
                True,
                id="macos-volume_down",
            ),
            pytest.param(
                macos,
                "volume_mute",
                {},
                "osascript -e 'set volume output muted (not (output muted of (get volume settings)))'",
                True,
                id="macos-volume_mute",
            ),
            pytest.param(
                macos,
                "volume_unmute",
                {},
                "osascript -e 'set volume output muted false'",
                True,
                id="macos-volume_unmute",
            ),
            pytest.param(
                macos,
                "lock_screen",
                {},
                "'/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession' -suspend",
                True,
                id="macos-lock_screen",
            ),
            pytest.param(
                macos,
                "system_reboot",
                {},
                "osascript -e 'tell application \"System Events\" to restart'",
                True,
                id="macos-system_reboot",
            ),
            pytest.param(
                macos,
                "system_shutdown",
                {},
                "osascript -e 'tell application \"System Events\" to shut down'",
                True,
                id="macos-system_shutdown",
            ),
            pytest.param(
                macos,
                "notify",
                {"title": "Hello", "message": "World"},
                'osascript -e \'display notification "World" with title "Hello"\'',
                True,
                id="macos-notify",
            ),
            pytest.param(
                macos,
                "notify",
                {"title": "it's", "message": "test"},
                "osascript -e 'display notification \"test\" with title \"it'\\''s\"'",
                True,
                id="macos-notify_escape",
            ),
            pytest.param(
                macos,
                "input_text",
                {"text": "hello"},
                'osascript -e \'tell application "System Events" to keystroke "hello"\'',
                True,
                id="macos-input_text",
            ),
            pytest.param(
                macos,
                "get_terminal",
                {},
                "open -a Terminal",
                True,
                id="macos-get_terminal",
            ),
            pytest.param(
                macos,
                "get_file_manager",
                {},
                "open -a Finder",
                True,
                id="macos-get_file_manager",
            ),
            pytest.param(
                macos,
                "get_task_manager",
                {},
                "open -a 'Activity Monitor'",
                True,
                id="macos-get_task_manager",
            ),
        ]
    )

    return cases


# ─── Special additional tests ───────────────────────────────────────────────


class TestMacOSWindowMaximize:
    """window_maximize on macOS should equal window_fullscreen."""

    def test_window_maximize_equals_fullscreen(self):
        adapter = MacOSAdapter()
        assert adapter.window_maximize() == adapter.window_fullscreen()


class _MinimalAdapter(BaseAdapter):
    """Concrete subclass of BaseAdapter for testing default implementations."""

    def __init__(self):
        super().__init__()
        self.name = "minimal"

    def workspace_switch(self, number):
        return f"ws {number}"

    def workspace_next(self):
        return "ws next"

    def workspace_prev(self):
        return "ws prev"

    def window_close(self):
        return "kill"

    def window_fullscreen(self):
        return "fullscreen"

    def window_minimize(self):
        return "minimize"

    def window_maximize(self):
        return "maximize"

    def window_floating(self):
        return "floating"

    def window_next(self):
        return "next"

    def window_prev(self):
        return "prev"

    def screenshot_screen(self):
        return "scrot"

    def screenshot_area(self):
        return "scrot -s"

    def screenshot_window(self):
        return "scrot -u"

    def volume_up(self, amount=5):
        return f"vol +{amount}"

    def volume_down(self, amount=5):
        return f"vol -{amount}"

    def volume_mute(self):
        return "mute"

    def volume_unmute(self):
        return "unmute"

    def lock_screen(self):
        return "lock"


class TestBaseAdapterFallback:
    """Tests for the BaseAdapter default (inherited) implementations."""

    def test_base_adapter_name(self):
        adapter = _MinimalAdapter()
        assert adapter.name == "minimal"

    def test_base_notify(self):
        adapter = _MinimalAdapter()
        result = adapter.notify("Test", "Message")
        assert result == "notify-send 'Test' 'Message'"
        # Note: base adapter does NOT add -u normal

    def test_base_notify_escape(self):
        adapter = _MinimalAdapter()
        result = adapter.notify("it's", "test's")
        assert result == "notify-send 'it'\\''s' 'test'\\''s'"

    def test_base_input_text(self):
        adapter = _MinimalAdapter()
        result = adapter.input_text("hello")
        assert (
            result
            == "wtype 'hello' 2>/dev/null || xdotool type 'hello' 2>/dev/null || echo 'input_text: hello'"
        )

    def test_base_system_reboot(self):
        adapter = _MinimalAdapter()
        assert adapter.system_reboot() == "reboot"

    def test_base_system_shutdown(self):
        adapter = _MinimalAdapter()
        assert adapter.system_shutdown() == "poweroff"

    def test_base_get_terminal(self):
        adapter = _MinimalAdapter()
        assert adapter.get_terminal() == "xterm"

    def test_base_get_file_manager(self):
        adapter = _MinimalAdapter()
        assert adapter.get_file_manager() == "xdg-open ~"

    def test_base_get_task_manager(self):
        adapter = _MinimalAdapter()
        assert adapter.get_task_manager() == "xterm -e htop"


# ─── Main parametrized test ────────────────────────────────────────────────


TEST_CASES = _t()


@pytest.mark.parametrize(
    "adapter_cls,method,kwargs,expected,exact",
    TEST_CASES,
)
def test_adapter_command(adapter_cls, method, kwargs, expected, exact, monkeypatch):
    """Verify adapter method returns the correct command string."""
    adapter = adapter_cls()

    # Sway area/window screenshots need a live compositor (slurp for
    # interactive selection, sway IPC for focused window geometry). Mock
    # these helper functions so the test doesn't need real Sway running.
    from jarvis.adapters import sway as sway_mod

    if adapter.name == "sway" and method == "screenshot_area":
        monkeypatch.setattr(sway_mod, "_slurp_geometry", lambda: "100,100 500x400")
    elif adapter.name == "sway" and method == "screenshot_window":
        monkeypatch.setattr(
            sway_mod, "_focused_window_geometry", lambda: "0,0 1920x1080"
        )

    impl = getattr(adapter, method)
    result = impl(**kwargs)

    # Пустая строка — это регрессия (упавший/замолчавший адаптер),
    # а не повод молча пропустить тест.
    assert result, f"{adapter.name}.{method} вернул пустую команду"

    if exact:
        assert _normalize(result) == _normalize(expected), (
            f"{adapter.name}.{method}({kwargs}):\n"
            f"  expected: {expected}\n"
            f"  got:      {result}"
        )
    else:
        assert result.startswith(expected), (
            f"{adapter.name}.{method}({kwargs}):\n"
            f"  expected prefix: {expected}\n"
            f"  got:             {result}"
        )


class TestCommonPatterns:
    """Cross-cutting patterns that should hold across adapters."""

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            I3Adapter,
            SwayAdapter,
            HyprlandAdapter,
            GNOMEAdapter,
            KDEAdapter,
        ],
    )
    def test_linux_notify_has_notify_send(self, adapter_cls):
        adapter = adapter_cls()
        result = adapter.notify("Title", "Message")
        assert "notify-send" in result

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            I3Adapter,
            SwayAdapter,
            HyprlandAdapter,
            GNOMEAdapter,
            KDEAdapter,
        ],
    )
    def test_linux_input_text_has_wtype_or_xdotool(self, adapter_cls):
        adapter = adapter_cls()
        result = adapter.input_text("test")
        assert "wtype" in result or "xdotool" in result

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            I3Adapter,
            SwayAdapter,
            HyprlandAdapter,
            GNOMEAdapter,
            KDEAdapter,
        ],
    )
    def test_linux_pactl_volume(self, adapter_cls):
        adapter = adapter_cls()
        assert "pactl set-sink-volume" in adapter.volume_up()
        assert "pactl set-sink-volume" in adapter.volume_down()
        assert "pactl set-sink-mute" in adapter.volume_mute()

    def test_macos_notify_has_osascript(self):
        adapter = MacOSAdapter()
        assert "osascript" in adapter.notify("T", "M")

    def test_macos_volume_has_osascript(self):
        adapter = MacOSAdapter()
        assert "osascript" in adapter.volume_up()

    @pytest.mark.parametrize(
        "adapter_cls,expected_name",
        [
            (I3Adapter, "i3"),
            (SwayAdapter, "sway"),
            (HyprlandAdapter, "hyprland"),
            (GNOMEAdapter, "gnome"),
            (KDEAdapter, "kde"),
            (MacOSAdapter, "macos"),
        ],
    )
    def test_adapter_name(self, adapter_cls, expected_name):
        assert adapter_cls().name == expected_name
