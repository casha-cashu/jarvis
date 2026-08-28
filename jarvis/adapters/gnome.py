#!/usr/bin/env python3
"""
GNOME adapter - commands for GNOME Shell (Mutter)

org.gnome.Shell.Eval закрыт с GNOME 41 ("unsafe mode"), поэтому все
команды через Eval не работали на любом современном GNOME. Здесь:

- окна/воркспейсы — через EWMH/xdotool (X11; на Wayland xdotool не
  работает, там остаются pactl/notify-send/loginctl);
- скриншоты — НЕ-интерактивного пути на GNOME 41+ нет: org.gnome.Shell
  .Screenshot закрыт тем же MR !1970, что и Eval (gnome-screenshot
  выпален из GNOME 42+), а portal требует диалога согласия. Print
  открывает UI скриншотов Shell — работает и на X11, и на Wayland.

Активное окно: комбинации клавиш действуют на сфокусированное окно —
это чинит баг старого кода, таргетировавшего actors[0] (произвольное
окно из стека).
"""

from .base import BaseAdapter


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

    # Screenshots — НЕ-интерактивного пути на GNOME 41+ нет: org.gnome.Shell
    # .Screenshot закрыт тем же MR !1970, что и Eval, а не-интерактивный
    # org.freedesktop.portal.Screenshot требует диалога согласия.
    # Print открывает UI скриншотов Shell (работает и на X11, и на Wayland);
    # файл кладётся в ~/Pictures/Screenshots средствами Shell — кастомное
    # имя через _screenshot_path недоступно.
    def screenshot_screen(self) -> str:
        return "xdotool key Print"

    def screenshot_area(self) -> str:
        return "xdotool key Print"

    def screenshot_window(self) -> str:
        return "xdotool key Print"

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
