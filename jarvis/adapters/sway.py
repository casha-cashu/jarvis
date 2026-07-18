#!/usr/bin/env python3
"""
Sway adapter - commands for Sway window manager (i3-compatible Wayland)
"""

import json
import logging
import os
import shlex
import shutil
import subprocess
from datetime import datetime

from jarvis._env import sanitized_env

from .base import BaseAdapter

logger = logging.getLogger(__name__)


def _screenshot_path() -> str:
    return os.path.expanduser(
        f"~/Pictures/screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
    )


def _slurp_geometry() -> str | None:
    """Запускает slurp и возвращает выбранный регион (например '10,20 800x600').

    Возвращает None если slurp не установлен или пользователь отменил выбор.
    """
    if not shutil.which("slurp"):
        return None
    try:
        result = subprocess.run(
            ["slurp"],
            capture_output=True,
            text=True,
            timeout=60,
            env=sanitized_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("slurp failed: %s", exc)
        return None
    if result.returncode != 0:
        return None
    geom = result.stdout.strip()
    return geom or None


def _focused_window_geometry() -> str | None:
    """Парсит swaymsg -t get_tree и возвращает геометрию активного окна."""
    if not shutil.which("swaymsg"):
        return None
    try:
        result = subprocess.run(
            ["swaymsg", "-t", "get_tree"],
            capture_output=True,
            text=True,
            timeout=5,
            env=sanitized_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("swaymsg failed: %s", exc)
        return None
    if result.returncode != 0:
        return None
    try:
        tree = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    def find_focused(node):
        if node.get("focused"):
            return node
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            found = find_focused(child)
            if found is not None:
                return found
        return None

    focused = find_focused(tree)
    if not focused:
        return None
    rect = focused.get("rect", {})
    if not all(k in rect for k in ("x", "y", "width", "height")):
        return None
    return f"{rect['x']},{rect['y']} {rect['width']}x{rect['height']}"


class SwayAdapter(BaseAdapter):
    """Adapter for Sway WM"""

    def __init__(self):
        super().__init__()
        self.name = "sway"

    # Workspace management
    def workspace_switch(self, number: int) -> str:
        return f"swaymsg workspace {number}"

    def workspace_next(self) -> str:
        return "swaymsg workspace next"

    def workspace_prev(self) -> str:
        return "swaymsg workspace prev"

    # Window management
    def window_close(self) -> str:
        return "swaymsg kill"

    def window_fullscreen(self) -> str:
        return "swaymsg fullscreen toggle"

    def window_minimize(self) -> str:
        return "swaymsg move scratchpad"

    def window_maximize(self) -> str:
        return "swaymsg fullscreen enable"

    def window_floating(self) -> str:
        return "swaymsg floating toggle"

    def window_next(self) -> str:
        return "swaymsg focus next"

    def window_prev(self) -> str:
        return "swaymsg focus prev"

    # Screenshots — раскрываем ~, timestamp и геометрию (slurp/swaymsg)
    # на стороне Python, иначе shell=False не распарсит $(...).
    # Пустая строка означает «отменено / нет инструмента» — _run пропустит.
    def screenshot_screen(self) -> str:
        return f"grim {shlex.quote(_screenshot_path())}"

    def screenshot_area(self) -> str:
        geom = _slurp_geometry()
        if not geom:
            return ""
        return f"grim -g {shlex.quote(geom)} {shlex.quote(_screenshot_path())}"

    def screenshot_window(self) -> str:
        geom = _focused_window_geometry()
        if not geom:
            return ""
        return f"grim -g {shlex.quote(geom)} {shlex.quote(_screenshot_path())}"

    # Audio control
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
        return "swaylock"

    # Notifications через mako (стандарт в Sway)
    def notify(self, title: str, message: str) -> str:
        escaped_title = title.replace("'", "'\\''")
        escaped_msg = message.replace("'", "'\\''")
        return f"notify-send -u normal '{escaped_title}' '{escaped_msg}'"

    # Applications
    def get_terminal(self) -> str:
        return "foot"

    def get_file_manager(self) -> str:
        return "pcmanfm"

    def get_task_manager(self) -> str:
        return "foot -e htop"
