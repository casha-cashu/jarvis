#!/usr/bin/env python3
"""
Hyprland adapter - commands for Hyprland window manager
"""

from .base import BaseAdapter


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
        return "grimblast copy screen"

    def screenshot_area(self) -> str:
        return "grimblast copy area"

    def screenshot_window(self) -> str:
        return "grimblast copy active"

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
