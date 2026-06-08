#!/usr/bin/env python3
"""
GNOME adapter - commands for GNOME Shell (Mutter)
"""

import os
import shlex
from datetime import datetime

from .base import BaseAdapter


def _screenshot_path() -> str:
    return os.path.expanduser(
        f"~/Pictures/screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
    )


class GNOMEAdapter(BaseAdapter):
    """Adapter for GNOME Shell"""

    def __init__(self):
        super().__init__()
        self.name = "gnome"

    # Workspace management
    def workspace_switch(self, number: int) -> str:
        # GNOME uses 0-indexed workspaces
        index = number - 1
        return f"gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'Main.wm.actionMoveWorkspace(global.workspace_manager.get_workspace_by_index({index}))'"

    def workspace_next(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'Main.wm.actionMoveWorkspaceRight()'"

    def workspace_prev(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'Main.wm.actionMoveWorkspaceLeft()'"

    # Window management
    def window_close(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'global.get_window_actors()[0].meta_window.delete(global.get_current_time())'"

    def window_fullscreen(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'global.get_window_actors()[0].meta_window.make_fullscreen()'"

    def window_minimize(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'global.get_window_actors()[0].meta_window.minimize()'"

    def window_maximize(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'global.get_window_actors()[0].meta_window.maximize(Meta.MaximizeFlags.BOTH)'"

    def window_floating(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'global.get_window_actors()[0].meta_window.unmaximize(Meta.MaximizeFlags.BOTH)'"

    def window_next(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'Main.activateWindow(global.display.get_tab_list(Meta.TabList.NORMAL, null)[1])'"

    def window_prev(self) -> str:
        return "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'Main.activateWindow(global.display.get_tab_list(Meta.TabList.NORMAL, null).reverse()[1])'"

    # Screenshots — раскрываем ~ и timestamp здесь, иначе shell=False
    # не распарсит $(date ...).
    def screenshot_screen(self) -> str:
        return f"gnome-screenshot -f {shlex.quote(_screenshot_path())}"

    def screenshot_area(self) -> str:
        return f"gnome-screenshot -a -f {shlex.quote(_screenshot_path())}"

    def screenshot_window(self) -> str:
        return f"gnome-screenshot -w -f {shlex.quote(_screenshot_path())}"

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
        return "gnome-screensaver-command -l"

    # Notifications (GNOME Shell)
    def notify(self, title: str, message: str) -> str:
        escaped_title = title.replace("'", "'\\''")
        escaped_msg = message.replace("'", "'\\''")
        return f"notify-send -u normal '{escaped_title}' '{escaped_msg}'"

    # Applications
    def get_terminal(self) -> str:
        return "gnome-terminal"

    def get_file_manager(self) -> str:
        return "nautilus"

    def get_task_manager(self) -> str:
        return "gnome-system-monitor"
