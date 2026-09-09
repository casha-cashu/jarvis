#!/usr/bin/env python3
"""
Hyprland adapter - commands for Hyprland window manager
"""

from datetime import datetime
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Optional

from jarvis._env import sanitized_env
from .base import BaseAdapter


def _screenshot_path() -> str:
    d = Path("~/Pictures").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"screenshot-{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")


def _slurp_geometry() -> Optional[str]:
    if not shutil.which("slurp"):
        return None
    try:
        proc = subprocess.run(
            ["slurp"],
            capture_output=True,
            text=True,
            timeout=10,
            env=sanitized_env(),
        )
        geom = (proc.stdout or "").strip()
        return geom or None
    except Exception:
        return None


class HyprlandAdapter(BaseAdapter):
    """Adapter for Hyprland WM"""

    def __init__(self):
        super().__init__()
        self.name = "hyprland"

    # Workspace management
    def workspace_switch(self, number: int) -> str:
        return f"hyprctl dispatch workspace {number}"

    def workspace_next(self) -> str:
        return "hyprctl dispatch workspace e+1"

    def workspace_prev(self) -> str:
        return "hyprctl dispatch workspace e-1"

    # Window management
    def window_close(self) -> str:
        return "hyprctl dispatch killactive"

    def window_fullscreen(self) -> str:
        return "hyprctl dispatch fullscreen"

    def window_minimize(self) -> str:
        return "hyprctl dispatch movetoworkspacesilent special"

    def window_maximize(self) -> str:
        return "hyprctl dispatch fullscreen 1"

    def window_floating(self) -> str:
        return "hyprctl dispatch togglefloating"

    def window_next(self) -> str:
        return "hyprctl dispatch cyclenext"

    def window_prev(self) -> str:
        return "hyprctl dispatch cyclenext prev"

    # Screenshots
    def screenshot_screen(self) -> str:
        if shutil.which("grimblast"):
            return "grimblast copy screen"
        return f"grim {shlex.quote(_screenshot_path())}"

    def screenshot_area(self) -> str:
        if shutil.which("grimblast"):
            return "grimblast copy area"
        geom = _slurp_geometry()
        if geom:
            return f"grim -g {shlex.quote(geom)} {shlex.quote(_screenshot_path())}"
        return f"grim {shlex.quote(_screenshot_path())}"

    def screenshot_window(self) -> str:
        if shutil.which("grimblast"):
            return "grimblast copy active"
        geom = _slurp_geometry()
        if geom:
            return f"grim -g {shlex.quote(geom)} {shlex.quote(_screenshot_path())}"
        return f"grim {shlex.quote(_screenshot_path())}"

    # Audio control (PipeWire/PulseAudio)
    def volume_up(self, amount: int = 5) -> str:
        return f"pactl set-sink-volume @DEFAULT_SINK@ +{amount}%"

    def volume_down(self, amount: int = 5) -> str:
        return f"pactl set-sink-volume @DEFAULT_SINK@ -{amount}%"

    def volume_mute(self) -> str:
        return "pactl set-sink-mute @DEFAULT_SINK@ toggle"

    def volume_unmute(self) -> str:
        return "pactl set-sink-mute @DEFAULT_SINK@ 0"

    # System
    def lock_screen(self) -> str:
        return "hyprlock"

    # Notifications через Hyprland-native (если есть), fallback на notify-send
    def notify(self, title: str, message: str) -> str:
        escaped_title = title.replace("'", "'\\''")
        escaped_msg = message.replace("'", "'\\''")
        # dunst/notify-send — стандарт на Wayland
        return f"notify-send -u normal '{escaped_title}' '{escaped_msg}'"

    # Applications
    def get_terminal(self) -> str:
        return "kitty"

    def get_file_manager(self) -> str:
        return "thunar"

    def get_task_manager(self) -> str:
        return "kitty -e btop"
