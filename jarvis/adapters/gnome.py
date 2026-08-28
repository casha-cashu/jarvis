#!/usr/bin/env python3
"""
GNOME adapter - commands for GNOME Shell (Mutter)

org.gnome.Shell.Eval закрыт с GNOME 41 ("unsafe mode"), поэтому все
команды через Eval не работали на любом современном GNOME. Здесь:

- окна/воркспейсы — через EWMH/xdotool (X11; на Wayland xdotool не
  работает, там остаются pactl/notify-send/loginctl/скриншоты);
- скриншоты — через org.gnome.Shell.Screenshot (D-Bus API не закрыт,
  в отличие от Eval; gnome-screenshot выпален из GNOME 42+).

Активное окно: комбинации клавиш действуют на сфокусированное окно —
это чинит баг старого кода, таргетировавшего actors[0] (произвольное
окно из стека).
"""

import os
import shlex
from datetime import datetime
from pathlib import Path

from .base import BaseAdapter


def _screenshot_path() -> str:
    return os.path.expanduser(
        f"~/Pictures/screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
    )


def _ensure_pictures_dir() -> None:
    """~/Pictures может не существовать — создаём в момент вызова команды
    (метод вызывается CommandExecutor._run в execute-time, callable)."""
    Path("~/Pictures").expanduser().mkdir(parents=True, exist_ok=True)


class GNOMEAdapter(BaseAdapter):
    """Adapter for GNOME Shell"""

    def __init__(self):
        super().__init__()
        self.name = "gnome"

    # Workspace management
    def workspace_switch(self, number: int) -> str:
        # wmctrl говорит с Mutter через EWMH (_NET_CURRENT_DESKTOP),
        # воркспейсы 0-indexed.
        return f"wmctrl -s {number - 1}"

    def workspace_next(self) -> str:
        return "xdotool key ctrl+alt+Right"

    def workspace_prev(self) -> str:
        return "xdotool key ctrl+alt+Left"

    # Window management (действуют на сфокусированное окно)
    def window_close(self) -> str:
        return "xdotool key alt+F4"

    def window_fullscreen(self) -> str:
        # App-level fullscreen (как F11 в большинстве приложений)
        return "xdotool key F11"

    def window_minimize(self) -> str:
        # GNOME default: "Hide window" = Super+H
        return "xdotool key super+h"

    def window_maximize(self) -> str:
        # GNOME default: "Toggle maximize state" = Alt+F10
        return "xdotool key alt+F10"

    def window_floating(self) -> str:
        # В GNOME нет концепции floating-окон (это тайлинг-WM термин)
        return "echo 'Floating windows not supported on GNOME'"

    def window_next(self) -> str:
        # GNOME default: "Switch windows directly" = Alt+Esc
        return "xdotool key alt+Escape"

    def window_prev(self) -> str:
        return "xdotool key alt+shift+Escape"

    # Screenshots — org.gnome.Shell.Screenshot (не закрыт, в отличие от
    # Eval). Путь и время раскрываем в Python (shell=False), mkdir тоже
    # заранее — CommandExecutor не исполняет shell-цепочки.
    def screenshot_screen(self) -> str:
        _ensure_pictures_dir()
        path = shlex.quote(_screenshot_path())
        return (
            "gdbus call --session --dest org.gnome.Shell.Screenshot "
            "--object-path /org/gnome/Shell/Screenshot "
            f"--method org.gnome.Shell.Screenshot.Screenshot false false {path}"
        )

    def screenshot_area(self) -> str:
        # Интерактивный выбор области: вне-shell нельзя ни спросить геометрию
        # (slurp), ни передать координаты в D-Bus. Print открывает
        # интерактивный UI скриншотов GNOME 42+; файл кладётся в
        # ~/Pictures/Screenshots средствами Shell.
        _ensure_pictures_dir()
        return "xdotool key Print"

    def screenshot_window(self) -> str:
        _ensure_pictures_dir()
        path = shlex.quote(_screenshot_path())
        return (
            "gdbus call --session --dest org.gnome.Shell.Screenshot "
            "--object-path /org/gnome/Shell/Screenshot "
            f"--method org.gnome.Shell.Screenshot.ScreenshotWindow false false {path}"
        )

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
        # gnome-screensaver-command не входит в стоковый GNOME;
        # loginctl работает на любом systemd-дистрибутиве.
        return "loginctl lock-session"

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
