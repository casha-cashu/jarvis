#!/usr/bin/env python3
"""
KDE adapter - commands for KDE Plasma (KWin)
"""

from .base import BaseAdapter


class KDEAdapter(BaseAdapter):
    """Adapter for KDE Plasma"""

    def __init__(self):
        super().__init__()
        self.name = "kde"

    # Workspace management
    def workspace_switch(self, number: int) -> str:
        return f"qdbus org.kde.KWin /KWin setCurrentDesktop {number}"

    def workspace_next(self) -> str:
        return "qdbus org.kde.KWin /KWin nextDesktop"

    def workspace_prev(self) -> str:
        return "qdbus org.kde.KWin /KWin previousDesktop"

    # Window management
    def window_close(self) -> str:
        return "qdbus org.kde.KWin /KWin killWindow"

    def window_fullscreen(self) -> str:
        return "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Window Fullscreen'"

    def window_minimize(self) -> str:
        return "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Window Minimize'"

    def window_maximize(self) -> str:
        return "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Window Maximize'"

    def window_floating(self) -> str:
        return "qdbus org.kde.kglobalaccel /component/kwin invokeShortcut 'Window Quick Tile Bottom'"

    def window_next(self) -> str:
        return "qdbus org.kde.KWin /KWin nextWindow"

    def window_prev(self) -> str:
        return "qdbus org.kde.KWin /KWin previousWindow"

    # Screenshots
    def screenshot_screen(self) -> str:
        return "spectacle -f -b -n"

    def screenshot_area(self) -> str:
        return "spectacle -r -b -n"

    def screenshot_window(self) -> str:
        return "spectacle -a -b -n"

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
        return "loginctl lock-session"

    # Notifications (KDE Plasma использует собственный notify-send)
    def notify(self, title: str, message: str) -> str:
        escaped_title = title.replace("'", "'\\''")
        escaped_msg = message.replace("'", "'\\''")
        return f"notify-send -u normal '{escaped_title}' '{escaped_msg}'"

    # Applications
    def get_terminal(self) -> str:
        return "konsole"

    def get_file_manager(self) -> str:
        return "dolphin"

    def get_task_manager(self) -> str:
        return "ksysguard"
