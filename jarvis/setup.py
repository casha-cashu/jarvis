#!/usr/bin/env python3
"""Мастер настройки JARVIS"""

import sys
import shutil
import subprocess
from pathlib import Path

from jarvis._env import sanitized_env


def _check_installed(cmd: str) -> bool:
    """Проверяет что команда установлена"""
    return shutil.which(cmd) is not None


def _prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Да/нет вопрос"""
    hint = "Y/n" if default else "y/N"
    val = input(f"  {prompt} ({hint}): ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


def step_system_deps():
    """Проверка системных зависимостей"""
    print("\n  ── Системные зависимости ──")
    needed = {
        "mpv": "Плеер для TTS (mpv)",
        "ffplay": "Плеер для TTS (ffmpeg)",
        "paplay": "Плеер для TTS (pulseaudio)",
        "grimblast": "Скриншоты (Hyprland)",
        "hyprctl": "Hyprland WM",
        "pactl": "Управление громкостью (pulseaudio)",
    }
    all_ok = True
    for cmd, desc in needed.items():
        found = _check_installed(cmd)
        status = "✅" if found else "⚠️"
        if not found:
            all_ok = False
        print(f"     {status} {cmd} — {desc}")

    if not all_ok:
        print(
            "  Некоторые утилиты не найдены. Это не критично, но часть команд может не работать."
        )
    return all_ok


VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"


def _download_vosk_model(dest_dir: Path) -> None:
    """Скачивает и распаковывает vosk-model-small-ru в ~/models/vosk."""
    import zipfile

    import requests

    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "vosk-model-small-ru.zip"
    print(f"     ⏬ {VOSK_MODEL_URL}")
    try:
        with requests.get(VOSK_MODEL_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
    except Exception as e:
        print(f"     ❌ Не удалось скачать Vosk модель: {e}")
        return
    finally:
        zip_path.unlink(missing_ok=True)
    print(f"     ✅ Vosk модель распакована в {dest_dir}")


def step_models():
    """Проверка/установка моделей"""
    print("\n  ── Модели Vosk и Piper ──")

    vosk_dir = Path.home() / "models" / "vosk"
    piper_dir = Path.home() / "models" / "piper"

    if vosk_dir.exists() and list(vosk_dir.iterdir()):
        print(f"     ✅ Vosk: {vosk_dir}")
    else:
        print(f"     ⚠️  Vosk модель не найдена в {vosk_dir}")
        if _prompt_yes_no("Скачать Vosk модель (~45MB)?"):
            _download_vosk_model(vosk_dir)

    if piper_dir.exists() and list(piper_dir.iterdir()):
        print(f"     ✅ Piper: {piper_dir}")
    else:
        print(f"     ⚠️  Piper модель не найдена в {piper_dir}")
        if _prompt_yes_no("Скачать Piper голос Dmitri (~50MB)?"):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "jarvis",
                    "voice",
                    "download",
                    "ru_RU-dmitri-medium",
                ],
                cwd=Path(__file__).parent.parent,
                env=sanitized_env(),
            )


def step_python_deps():
    """Проверка Python зависимостей"""
    print("\n  ── Python зависимости ──")
    needed = {
        "yaml": "PyYAML",
        "vosk": "Vosk STT",
        "pyaudio": "PyAudio",
        "numpy": "NumPy",
        "anthropic": "Anthropic SDK",
        "requests": "HTTP",
        "gtts": "gTTS",
        "torch": "PyTorch (для VAD)",
    }
    for mod, desc in needed.items():
        try:
            __import__(mod)
            print(f"     ✅ {mod} — {desc}")
        except ImportError:
            print(f"     ❌ {mod} — {desc} (установи: pip install {mod})")


def step_env():
    """Проверка .env файла"""
    print("\n  ── Переменные окружения ──")
    env_path = Path(".env")
    if env_path.exists():
        print("     ✅ .env найден")
        # Проверяем что ключи не плейсхолдеры
        content = env_path.read_text()
        if "${" in content:
            print("     ⚠️  В .env есть незаполненные плейсхолдеры ${VAR}")
    else:
        print("     ⚠️  .env не найден")
        if Path(".env.example").exists():
            if _prompt_yes_no("Создать .env из .env.example?"):
                shutil.copy(".env.example", ".env")
                print("     ✅ .env создан. Заполни ключи!")


def setup_wizard():
    """Запуск мастера настройки"""
    print()
    print("╔" + "═" * 46 + "╗")
    print("║     🔧  МАСТЕР НАСТРОЙКИ JARVIS        ║")
    print("╚" + "═" * 46 + "╝")

    step_system_deps()
    step_python_deps()
    step_env()
    step_models()

    print()
    print("╔" + "═" * 46 + "╗")
    print("║     ✅  НАСТРОЙКА ЗАВЕРШЕНА             ║")
    print("╚" + "═" * 46 + "╝")
    print()
    print("  Запуск: jarvis run")
    print("  Или:    python3 -m jarvis run")


if __name__ == "__main__":
    setup_wizard()
