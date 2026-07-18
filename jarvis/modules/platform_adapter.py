#!/usr/bin/env python3
"""
Platform detection and adapter selection
Автоопределение платформы и выбор соответствующего адаптера
"""

import os
import platform
import subprocess
import logging
from typing import Optional

from jarvis._env import sanitized_env

logger = logging.getLogger(__name__)


def detect_os() -> str:
    """
    Определяет операционную систему

    Returns:
        'linux', 'macos', 'windows', или 'unknown'
    """
    system = platform.system().lower()

    if system == "linux":
        return "linux"
    elif system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    else:
        return "unknown"


def detect_distro() -> Optional[str]:
    """
    Определяет дистрибутив Linux

    Returns:
        'arch', 'debian', 'ubuntu', 'fedora', и т.д., или None
    """
    if detect_os() != "linux":
        return None

    try:
        # Пробуем /etc/os-release
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release", "r") as f:
                content = f.read().lower()

                if "arch" in content or "cachyos" in content or "manjaro" in content:
                    return "arch"
                elif "debian" in content:
                    return "debian"
                elif "ubuntu" in content:
                    return "ubuntu"
                elif "fedora" in content:
                    return "fedora"
                elif "opensuse" in content:
                    return "opensuse"

        # Проверяем наличие пакетных менеджеров
        if os.path.exists("/usr/bin/pacman"):
            return "arch"
        elif os.path.exists("/usr/bin/apt"):
            return "debian"
        elif os.path.exists("/usr/bin/dnf"):
            return "fedora"

    except Exception as e:
        logger.warning(f"Ошибка определения дистрибутива: {e}")

    return "unknown"


def _detect_de_from_env() -> Optional[str]:
    """Шаг 1: XDG_CURRENT_DESKTOP / DESKTOP_SESSION / *_INSTANCE_SIGNATURE."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session = os.environ.get("DESKTOP_SESSION", "").lower()
    if (
        "hyprland" in desktop
        or "hyprland" in session
        or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    ):
        return "hyprland"
    if "kde" in desktop or "plasma" in desktop:
        return "kde"
    if "gnome" in desktop:
        return "gnome"
    if "i3" in session or "i3" in desktop or os.environ.get("I3SOCK"):
        return "i3"
    if "sway" in session or "sway" in desktop or os.environ.get("SWAYSOCK"):
        return "sway"
    return None


def _detect_de_from_session() -> Optional[str]:
    """Шаг 2: ``loginctl show-session`` — DesktopName=… (systemd-only)."""
    try:
        result = subprocess.run(
            ["loginctl", "show-session"],
            capture_output=True,
            text=True,
            timeout=2,
            env=sanitized_env(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip().lower() == "desktopname":
            name = v.strip().lower()
            for de in ("i3", "sway", "hyprland", "kde", "plasma", "gnome"):
                if de in name:
                    return "kde" if de == "plasma" else de
    return None


def _detect_de_from_process_list(
    processes: Optional[list[str]] = None,
) -> Optional[str]:
    """Шаг 3: ``ps aux``. Тестируемо — accept actual_processes."""
    if processes is None:
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=2,
                env=sanitized_env(),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"ps aux failed: {e}")
            return None
        processes = result.stdout.lower().splitlines()
    else:
        processes = [p.lower() for p in processes]

    lines = "\n".join(processes)
    # Order matters: more specific markers first.
    if "hyprland" in lines:
        return "hyprland"
    if "plasmashell" in lines or "startplasma" in lines or "kwin" in lines:
        return "kde"
    if "gnome-shell" in lines:
        return "gnome"
    if "windowserver" in lines:
        return "macos"
    # i3 / sway: оба содержат подстроку "i3" в имени бинаря (sway тоже
    # запускает swaybar/swayidle). Проверяем sway первым — sway-сервер
    # называется "sway".
    if any("sway" in p for p in processes):
        return "sway"
    if any(
        ("i3" in p)
        and ("i3status" not in p)
        and ("i3blocks" not in p)
        and ("i3bar" not in p)
        for p in processes
    ):
        return "i3"
    return None


def detect_de(actual_processes: Optional[list[str]] = None) -> str:
    """
    Определяет desktop environment или window manager.

    Args:
        actual_processes: Для тестов — мок-список процессов (как из ps aux).
            Если задан, тесты только process-list ветку (env/loginctl
            пропускаются, чтобы не зависеть от окружения теста).

    Returns:
        'hyprland', 'kde', 'gnome', 'i3', 'sway', 'macos', или 'unknown'.
    """
    # Test mode — только process-list, без зависимости от env.
    if actual_processes is not None:
        result = _detect_de_from_process_list(actual_processes)
        return result or "unknown"

    os_type = detect_os()
    if os_type == "macos":
        return "macos"
    if os_type != "linux":
        return "unknown"

    # P7: fallback chain env → loginctl → ps. Каждый шаг graceful'но
    # возвращает None если источник недоступен (например в Docker нет
    # /proc, нет loginctl на musl-distro и т.д.).
    for source in (
        _detect_de_from_env,
        _detect_de_from_session,
        _detect_de_from_process_list,
    ):
        try:
            de = source()
        except Exception as e:
            logger.debug(f"detect_de step {source.__name__} failed: {e}")
            de = None
        if de:
            return de
    return "unknown"


def get_adapter_class(de: str):
    """
    Возвращает класс адаптера для данного DE

    Args:
        de: Название DE/WM

    Returns:
        Класс адаптера
    """
    if de == "hyprland":
        from ..adapters.hyprland import HyprlandAdapter

        return HyprlandAdapter
    elif de == "kde":
        from ..adapters.kde import KDEAdapter

        return KDEAdapter
    elif de == "gnome":
        from ..adapters.gnome import GNOMEAdapter

        return GNOMEAdapter
    elif de == "i3":
        from ..adapters.i3 import I3Adapter

        return I3Adapter
    elif de == "sway":
        from ..adapters.sway import SwayAdapter

        return SwayAdapter
    elif de == "macos":
        from ..adapters.macos import MacOSAdapter

        return MacOSAdapter
    else:
        # Fallback - используем базовый адаптер с заглушками
        logger.warning(f"⚠️ Неизвестный DE: {de}, используем базовый адаптер")
        from ..adapters.base import BaseAdapter

        # Создаём минимальный рабочий адаптер
        class FallbackAdapter(BaseAdapter):
            def workspace_switch(self, n):
                return f"echo 'Workspace {n} not supported'"

            def workspace_next(self):
                return "echo 'Not supported'"

            def workspace_prev(self):
                return "echo 'Not supported'"

            def window_close(self):
                return "echo 'Not supported'"

            def window_fullscreen(self):
                return "echo 'Not supported'"

            def window_minimize(self):
                return "echo 'Not supported'"

            def window_maximize(self):
                return "echo 'Not supported'"

            def window_floating(self):
                return "echo 'Not supported'"

            def window_next(self):
                return "echo 'Not supported'"

            def window_prev(self):
                return "echo 'Not supported'"

            def screenshot_screen(self):
                return "scrot"

            def screenshot_area(self):
                return "scrot -s"

            def screenshot_window(self):
                return "scrot -u"

            def volume_up(self, amount=5):
                return f"amixer set Master {amount}%+"

            def volume_down(self, amount=5):
                return f"amixer set Master {amount}%-"

            def volume_mute(self):
                return "amixer set Master toggle"

            def volume_unmute(self):
                return "amixer set Master unmute"

            def lock_screen(self):
                return "xdg-screensaver lock"

            def system_reboot(self):
                return "systemctl reboot"

            def system_shutdown(self):
                return "systemctl poweroff"

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
