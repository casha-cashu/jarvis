#!/usr/bin/env python3
"""
Platform detection and adapter selection
Автоопределение платформы и выбор соответствующего адаптера
"""

import os
import sys
import platform
import subprocess
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def detect_os() -> str:
    """
    Определяет операционную систему

    Returns:
        'linux', 'macos', 'windows', или 'unknown'
    """
    system = platform.system().lower()

    if system == 'linux':
        return 'linux'
    elif system == 'darwin':
        return 'macos'
    elif system == 'windows':
        return 'windows'
    else:
        return 'unknown'


def detect_distro() -> Optional[str]:
    """
    Определяет дистрибутив Linux

    Returns:
        'arch', 'debian', 'ubuntu', 'fedora', и т.д., или None
    """
    if detect_os() != 'linux':
        return None

    try:
        # Пробуем /etc/os-release
        if os.path.exists('/etc/os-release'):
            with open('/etc/os-release', 'r') as f:
                content = f.read().lower()

                if 'arch' in content or 'cachyos' in content or 'manjaro' in content:
                    return 'arch'
                elif 'debian' in content:
                    return 'debian'
                elif 'ubuntu' in content:
                    return 'ubuntu'
                elif 'fedora' in content:
                    return 'fedora'
                elif 'opensuse' in content:
                    return 'opensuse'

        # Проверяем наличие пакетных менеджеров
        if os.path.exists('/usr/bin/pacman'):
            return 'arch'
        elif os.path.exists('/usr/bin/apt'):
            return 'debian'
        elif os.path.exists('/usr/bin/dnf'):
            return 'fedora'

    except Exception as e:
        logger.warning(f"Ошибка определения дистрибутива: {e}")

    return 'unknown'


def detect_de() -> str:
    """
    Определяет desktop environment или window manager

    Returns:
        'hyprland', 'kde', 'gnome', 'i3', 'sway', 'macos', или 'unknown'
    """
    os_type = detect_os()

    if os_type == 'macos':
        return 'macos'

    if os_type != 'linux':
        return 'unknown'

    # Проверяем переменные окружения
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    session = os.environ.get('DESKTOP_SESSION', '').lower()
    wayland_display = os.environ.get('WAYLAND_DISPLAY', '')

    # Hyprland
    if 'hyprland' in desktop or 'hyprland' in session:
        return 'hyprland'
    if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        return 'hyprland'

    # KDE
    if 'kde' in desktop or 'plasma' in desktop:
        return 'kde'

    # GNOME
    if 'gnome' in desktop:
        return 'gnome'

    # i3
    if 'i3' in session or os.environ.get('I3SOCK'):
        return 'i3'

    # Sway
    if 'sway' in session or os.environ.get('SWAYSOCK'):
        return 'sway'

    # Проверяем запущенные процессы
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            timeout=2
        )
        processes = result.stdout.lower()

        if 'hyprland' in processes:
            return 'hyprland'
        elif 'kwin' in processes or 'plasmashell' in processes:
            return 'kde'
        elif 'gnome-shell' in processes:
            return 'gnome'
        elif 'i3' in processes and 'sway' not in processes:
            return 'i3'
        elif 'sway' in processes:
            return 'sway'

    except Exception as e:
        logger.warning(f"Ошибка определения DE: {e}")

    return 'unknown'


def get_adapter_class(de: str):
    """
    Возвращает класс адаптера для данного DE

    Args:
        de: Название DE/WM

    Returns:
        Класс адаптера
    """
    if de == 'hyprland':
        from ..adapters.hyprland import HyprlandAdapter
        return HyprlandAdapter
    elif de == 'kde':
        from ..adapters.kde import KDEAdapter
        return KDEAdapter
    elif de == 'gnome':
        from ..adapters.gnome import GNOMEAdapter
        return GNOMEAdapter
    elif de == 'i3':
        from ..adapters.i3 import I3Adapter
        return I3Adapter
    elif de == 'sway':
        from ..adapters.sway import SwayAdapter
        return SwayAdapter
    elif de == 'macos':
        from ..adapters.macos import MacOSAdapter
        return MacOSAdapter
    else:
        # Fallback - используем базовый адаптер с заглушками
        logger.warning(f"⚠️ Неизвестный DE: {de}, используем базовый адаптер")
        from ..adapters.base import BaseAdapter

        # Создаём минимальный рабочий адаптер
        class FallbackAdapter(BaseAdapter):
            def workspace_switch(self, n): return f"echo 'Workspace {n} not supported'"
            def workspace_next(self): return "echo 'Not supported'"
            def workspace_prev(self): return "echo 'Not supported'"
            def window_close(self): return "echo 'Not supported'"
            def window_fullscreen(self): return "echo 'Not supported'"
            def window_minimize(self): return "echo 'Not supported'"
            def window_maximize(self): return "echo 'Not supported'"
            def window_floating(self): return "echo 'Not supported'"
            def window_next(self): return "echo 'Not supported'"
            def window_prev(self): return "echo 'Not supported'"
            def screenshot_screen(self): return "scrot"
            def screenshot_area(self): return "scrot -s"
            def screenshot_window(self): return "scrot -u"
            def volume_up(self, amount=5): return f"amixer set Master {amount}%+"
            def volume_down(self, amount=5): return f"amixer set Master {amount}%-"
            def volume_mute(self): return "amixer set Master toggle"
            def volume_unmute(self): return "amixer set Master unmute"
            def lock_screen(self): return "xdg-screensaver lock"
            def system_reboot(self): return "systemctl reboot"
            def system_shutdown(self): return "systemctl poweroff"

        return FallbackAdapter


class PlatformAdapter:
    """
    Главный класс для работы с платформой
    Автоматически определяет ОС/DE и предоставляет унифицированный API
    """

    def __init__(self):
        """Инициализация с автоопределением платформы"""
        self.os = detect_os()
        self.distro = detect_distro()
        self.de = detect_de()

        logger.info(f"🖥️  Платформа: OS={self.os}, Distro={self.distro}, DE={self.de}")

        # Получаем соответствующий адаптер
        adapter_class = get_adapter_class(self.de)
        self.adapter = adapter_class()

        logger.info(f"✅ Используется адаптер: {self.adapter.name}")

    # Делегируем все методы адаптеру
    def workspace_switch(self, number: int) -> str:
        return self.adapter.workspace_switch(number)

    def workspace_next(self) -> str:
        return self.adapter.workspace_next()

    def workspace_prev(self) -> str:
        return self.adapter.workspace_prev()

    def window_close(self) -> str:
        return self.adapter.window_close()

    def window_fullscreen(self) -> str:
        return self.adapter.window_fullscreen()

    def window_minimize(self) -> str:
        return self.adapter.window_minimize()

    def window_maximize(self) -> str:
        return self.adapter.window_maximize()

    def window_floating(self) -> str:
        return self.adapter.window_floating()

    def window_next(self) -> str:
        return self.adapter.window_next()

    def window_prev(self) -> str:
        return self.adapter.window_prev()

    def screenshot_screen(self) -> str:
        return self.adapter.screenshot_screen()

    def screenshot_area(self) -> str:
        return self.adapter.screenshot_area()

    def screenshot_window(self) -> str:
        return self.adapter.screenshot_window()

    def volume_up(self, amount: int = 5) -> str:
        return self.adapter.volume_up(amount)

    def volume_down(self, amount: int = 5) -> str:
        return self.adapter.volume_down(amount)

    def volume_mute(self) -> str:
        return self.adapter.volume_mute()

    def volume_unmute(self) -> str:
        return self.adapter.volume_unmute()

    def lock_screen(self) -> str:
        return self.adapter.lock_screen()

    def system_reboot(self) -> str:
        return self.adapter.system_reboot()

    def system_shutdown(self) -> str:
        return self.adapter.system_shutdown()

    def get_terminal(self) -> str:
        return self.adapter.get_terminal()

    def get_file_manager(self) -> str:
        return self.adapter.get_file_manager()

    def get_task_manager(self) -> str:
        return self.adapter.get_task_manager()

    def notify(self, title: str, message: str) -> str:
        """Показывает системное уведомление"""
        return self.adapter.notify(title, message)

    def input_text(self, text: str) -> str:
        """Вводит текст в активное поле (диктовка)"""
        return self.adapter.input_text(text)
