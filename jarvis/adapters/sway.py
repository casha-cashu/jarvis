#!/usr/bin/env python3
"""
Sway adapter - commands for Sway window manager (i3-compatible Wayland)
"""

from .base import BaseAdapter


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

    # Screenshots
    def screenshot_screen(self) -> str:
        return "grim ~/Pictures/screenshot-$(date +%Y%m%d-%H%M%S).png"

    def screenshot_area(self) -> str:
        return "grim -g \"$(slurp)\" ~/Pictures/screenshot-$(date +%Y%m%d-%H%M%S).png"

    def screenshot_window(self) -> str:
        return "grim -g \"$(swaymsg -t get_tree | jq -r '.. | select(.focused?) | .rect | \"\\(.x),\\(.y) \\(.width)x\\(.height)\"')\" ~/Pictures/screenshot-$(date +%Y%m%d-%H%M%S).png"

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
