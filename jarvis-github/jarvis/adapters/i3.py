#!/usr/bin/env python3
"""
i3 adapter - commands for i3 window manager
"""

import os
import shlex
from datetime import datetime

from .base import BaseAdapter


def _screenshot_path() -> str:
    return os.path.expanduser(
        f"~/Pictures/screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
    )


class I3Adapter(BaseAdapter):
    """Adapter for i3 WM"""

    def __init__(self):
        super().__init__()
        self.name = "i3"

    # Workspace management
    def workspace_switch(self, number: int) -> str:
        return f"i3-msg workspace {number}"

    def workspace_next(self) -> str:
        return "i3-msg workspace next"

    def workspace_prev(self) -> str:
        return "i3-msg workspace prev"

    # Window management
    def window_close(self) -> str:
        return "i3-msg kill"

    def window_fullscreen(self) -> str:
        return "i3-msg fullscreen toggle"

    def window_minimize(self) -> str:
        return "i3-msg move scratchpad"

    def window_maximize(self) -> str:
        return "i3-msg fullscreen enable"

    def window_floating(self) -> str:
        return "i3-msg floating toggle"

    def window_next(self) -> str:
        return "i3-msg focus right"

    def window_prev(self) -> str:
        return "i3-msg focus left"

    # Screenshots — раскрываем ~ и timestamp здесь, иначе shell=False
    # не распарсит $(date ...).
    def screenshot_screen(self) -> str:
        return f"scrot {shlex.quote(_screenshot_path())}"

    def screenshot_area(self) -> str:
        return f"scrot -s {shlex.quote(_screenshot_path())}"

    def screenshot_window(self) -> str:
        return f"scrot -u {shlex.quote(_screenshot_path())}"

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
        return "i3lock"

    # Notifications
    def notify(self, title: str, message: str) -> str:
        escaped_title = title.replace("'", "'\\''")
        escaped_msg = message.replace("'", "'\\''")
        return f"notify-send -u normal '{escaped_title}' '{escaped_msg}'"

    # Applications
    def get_terminal(self) -> str:
        return "i3-sensible-terminal"

    def get_file_manager(self) -> str:
        return "pcmanfm"

    def get_task_manager(self) -> str:
        return "i3-sensible-terminal -e htop"
