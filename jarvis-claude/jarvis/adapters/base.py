#!/usr/bin/env python3
"""
Base adapter class - defines interface for platform-specific commands
"""

from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """Base class for platform adapters"""

    def __init__(self):
        self.name = "base"

    # Workspace management
    @abstractmethod
    def workspace_switch(self, number: int) -> str:
        """Switch to workspace by number"""
        pass

    @abstractmethod
    def workspace_next(self) -> str:
        """Switch to next workspace"""
        pass

    @abstractmethod
    def workspace_prev(self) -> str:
        """Switch to previous workspace"""
        pass

    # Window management
    @abstractmethod
    def window_close(self) -> str:
        """Close active window"""
        pass

    @abstractmethod
    def window_fullscreen(self) -> str:
        """Toggle fullscreen for active window"""
        pass

    @abstractmethod
    def window_minimize(self) -> str:
        """Minimize active window"""
        pass

    @abstractmethod
    def window_maximize(self) -> str:
        """Maximize active window"""
        pass

    @abstractmethod
    def window_floating(self) -> str:
        """Toggle floating mode for active window"""
        pass

    @abstractmethod
    def window_next(self) -> str:
        """Focus next window"""
        pass

    @abstractmethod
    def window_prev(self) -> str:
        """Focus previous window"""
        pass

    # Screenshots
    @abstractmethod
    def screenshot_screen(self) -> str:
        """Take screenshot of entire screen"""
        pass

    @abstractmethod
    def screenshot_area(self) -> str:
        """Take screenshot of selected area"""
        pass

    @abstractmethod
    def screenshot_window(self) -> str:
        """Take screenshot of active window"""
        pass

    # Audio control
    @abstractmethod
    def volume_up(self, amount: int = 5) -> str:
        """Increase volume by amount%"""
        pass

    @abstractmethod
    def volume_down(self, amount: int = 5) -> str:
        """Decrease volume by amount%"""
        pass

    @abstractmethod
    def volume_mute(self) -> str:
        """Toggle mute"""
        pass

    @abstractmethod
    def volume_unmute(self) -> str:
        """Unmute"""
        pass

    # System
    @abstractmethod
    def lock_screen(self) -> str:
        """Lock screen"""
        pass

    def system_reboot(self) -> str:
        """Reboot system"""
        # reboot работает на всех Linux-дистрибутивах (systemd/OpenRC/runit)
        # через polkit; на macOS используется osascript в адаптере
        return "reboot"

    def system_shutdown(self) -> str:
        """Shutdown system"""
        return "poweroff"

    # Notifications
    def notify(self, title: str, message: str) -> str:
        """
        Показывает уведомление.
        Возвращает shell-команду.
        """
        escaped_title = title.replace("'", "'\\''")
        escaped_msg = message.replace("'", "'\\''")
        # notify-send — стандарт на Linux с D-Bus
        return f"notify-send '{escaped_title}' '{escaped_msg}'"

    # Text input (для диктовки)
    def input_text(self, text: str) -> str:
        """
        Вводит текст в активное поле (диктовка).
        Пробует wtype (Wayland), затем xdotool (X11), затем osascript (macOS).
        """
        escaped = text.replace("'", "'\\''")
        # Пробуем wtype (Wayland), если нет — xdotool (X11)
        return (
            f"wtype '{escaped}' 2>/dev/null || "
            f"xdotool type '{escaped}' 2>/dev/null || "
            f"echo 'input_text: {escaped}'"
        )

    # Applications
    def get_terminal(self) -> str:
        """Get default terminal emulator"""
        return "xterm"  # Fallback

    def get_file_manager(self) -> str:
        """Get default file manager"""
        return "xdg-open ~"  # Fallback

    def get_task_manager(self) -> str:
        """Get task manager command"""
        return f"{self.get_terminal()} -e htop"  # Fallback
