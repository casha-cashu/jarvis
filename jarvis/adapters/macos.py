#!/usr/bin/env python3
"""
macOS adapter - commands for macOS
"""

import os
import shlex
from datetime import datetime

from .base import BaseAdapter


def _screenshot_path() -> str:
    return os.path.expanduser(
        f"~/Pictures/screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
    )


class MacOSAdapter(BaseAdapter):
    """Adapter for macOS"""

    def __init__(self):
        super().__init__()
        self.name = "macos"

    # Keycodes цифр НЕ подряд: 18=1..21=4, 23=5, 22=6, 26=7, 28=8, 25=9,
    # 29=0. Старая формула 17+n на 8/9/10 жала не те клавиши.
    _DIGIT_KEY_CODES = {
        1: 18,
        2: 19,
        3: 20,
        4: 21,
        5: 23,
        6: 22,
        7: 26,
        8: 28,
        9: 25,
        10: 29,
    }

    # Workspace management (Mission Control)
    def workspace_switch(self, number: int) -> str:
        # Control + number switches desktops
        key_code = self._DIGIT_KEY_CODES.get(number)
        if key_code is None:
            return "echo 'Workspace {n} not supported'".format(n=number)
        return f"osascript -e 'tell application \"System Events\" to key code {key_code} using control down'"

    def workspace_next(self) -> str:
        return "osascript -e 'tell application \"System Events\" to key code 124 using control down'"

    def workspace_prev(self) -> str:
        return "osascript -e 'tell application \"System Events\" to key code 123 using control down'"

    # Window management
    def window_close(self) -> str:
        return 'osascript -e \'tell application "System Events" to keystroke "w" using command down\''

    def window_fullscreen(self) -> str:
        return 'osascript -e \'tell application "System Events" to keystroke "f" using {control down, command down}\''

    def window_minimize(self) -> str:
        return 'osascript -e \'tell application "System Events" to keystroke "m" using command down\''

    def window_maximize(self) -> str:
        # macOS doesn't have maximize, use fullscreen
        return self.window_fullscreen()

    def window_floating(self) -> str:
        # macOS doesn't have floating concept
        return "echo 'Not supported on macOS'"

    def window_next(self) -> str:
        return 'osascript -e \'tell application "System Events" to keystroke "`" using command down\''

    def window_prev(self) -> str:
        return 'osascript -e \'tell application "System Events" to keystroke "`" using {command down, shift down}\''

    # Screenshots — раскрываем ~ и timestamp здесь, иначе shell=False
    # не распарсит $(date ...).
    def screenshot_screen(self) -> str:
        return f"screencapture -c {shlex.quote(_screenshot_path())}"

    def screenshot_area(self) -> str:
        return f"screencapture -i {shlex.quote(_screenshot_path())}"

    def screenshot_window(self) -> str:
        return f"screencapture -w {shlex.quote(_screenshot_path())}"

    # Audio control
    def volume_up(self, amount: int = 5) -> str:
        return f"osascript -e 'set volume output volume (output volume of (get volume settings) + {amount})'"

    def volume_down(self, amount: int = 5) -> str:
        return f"osascript -e 'set volume output volume (output volume of (get volume settings) - {amount})'"

    def volume_mute(self) -> str:
        return "osascript -e 'set volume output muted (not (output muted of (get volume settings)))'"

    def volume_unmute(self) -> str:
        return "osascript -e 'set volume output muted false'"

    # System
    def lock_screen(self) -> str:
        # pmset displaysleepnow гасит экран без блокировки (без пароля при
        # пробуждении, если не включено «сразу требовать пароль»).
        # CGSession -suspend — настоящая блокировка сессии.
        return (
            "'/System/Library/CoreServices/Menu Extras/User.menu/Contents/"
            "Resources/CGSession' -suspend"
        )

    def system_reboot(self) -> str:
        return "osascript -e 'tell application \"System Events\" to restart'"

    def system_shutdown(self) -> str:
        return "osascript -e 'tell application \"System Events\" to shut down'"

    # Notifications (macOS native)
    def notify(self, title: str, message: str) -> str:
        # Два слоя экранирования: shell (одинарные кавычки) и AppleScript
        # (двойные кавычки + бэкслеши) — иначе кавычка/бэкслеш в тексте
        # напоминания ломала osascript и уведомление молча терялось.
        def apple_script_escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace('"', '\\"')

        escaped_title = apple_script_escape(title).replace("'", "'\\''")
        escaped_msg = apple_script_escape(message).replace("'", "'\\''")
        return (
            f'osascript -e \'display notification "{escaped_msg}" '
            f'with title "{escaped_title}"\''
        )

    # Text input (macOS)
    def input_text(self, text: str) -> str:
        escaped = text.replace("'", "'\\''")
        return (
            f'osascript -e \'tell application "System Events" to '
            f'keystroke "{escaped}"\''
        )

    # Applications
    def get_terminal(self) -> str:
        return "open -a Terminal"

    def get_file_manager(self) -> str:
        # 'open ~' не работал: без shell тильда не раскрывается — open
        # получал литеральный '~'. Finder явным образом.
        return "open -a Finder"

    def get_task_manager(self) -> str:
        return "open -a 'Activity Monitor'"
