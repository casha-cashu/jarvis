"""Пути к ресурсам, упакованным вместе с приложением (data/*.json).

- Dev/из исходников: пути относительны CWD (корень репо).
- PyInstaller onefile (jarvis-bridge): данные распаковываются в sys._MEIPASS.
- PyInstaller onedir: данные рядом с бинарём.

Без этого в установленном deb/AppImage словари команд и приложений не
находятся: cwd там — каталог бинаря (/usr/bin), а не репозиторий.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> str:
    """Первый существующий кандидат для ресурса; иначе — исходный путь.

    Порядок: CWD (dev) → sys._MEIPASS (onefile) → каталог бинаря (onedir).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [Path(relative).resolve()]
    if meipass:
        candidates.append(Path(meipass) / relative)
    candidates.append(Path(sys.executable).resolve().parent / relative)
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return relative
