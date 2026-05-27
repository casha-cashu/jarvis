#!/usr/bin/env python3
"""
Прессеты провайдеров LLM
Хранятся в ~/.config/jarvis/presets.json
"""

import json
import sys
from pathlib import Path
from typing import Tuple, Optional

PRESETS_DIR = Path.home() / '.config' / 'jarvis'
PRESETS_FILE = PRESETS_DIR / 'presets.json'


def load_presets() -> dict:
    """Загружает сохранённые пресеты"""
    if PRESETS_FILE.exists():
        try:
            return json.loads(PRESETS_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_presets(presets: dict):
    """Сохраняет пресеты в файл"""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(
        json.dumps(presets, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )


def save_preset(name: str, provider: str, config: dict):
    """Сохраняет один пресет"""
    presets = load_presets()
    presets[name] = {'provider': provider, 'config': config}
    save_presets(presets)


def select_preset_or_create() -> Tuple[str, dict]:
    """
    Интерактивное меню: выбор пресета или создание нового.
    Возвращает (provider_name, config_override).
    """
    from jarvis.cli_helpers import select_provider_interactive, _save_current_as_preset

    presets = load_presets()

    print()
    print("╔" + "═" * 56 + "╗")
    print("║         🤖  JARVIS — ВЫБОР МОДЕЛИ           ║")
    print("╠" + "═" * 56 + "╣")

    preset_names = list(presets.keys())
    has_presets = bool(preset_names)

    if has_presets:
        print("║  ── СОХРАНЁННЫЕ ПРЕСЕТЫ ──" + " " * 28 + "║")
        for i, name in enumerate(preset_names, 1):
            p = presets[name]
            prov = p['provider']
            model = p['config'].get('model', '?')
            print(f"║  {i}. {name:<20} ({prov}: {model})" + " " * max(1, 20 - len(name)) + "║")
        offset = len(preset_names) + 1
    else:
        offset = 1
        print("║  📭 Нет сохранённых пресетов" + " " * 28 + "║")

    n_new = offset
    n_manage = offset + 1 if has_presets else offset
    print(f"║{'':>56}║")
    print(f"║  {n_new}. ✨ Создать новый пресет" + " " * 30 + "║")
    if has_presets:
        print(f"║  {n_manage}. 🗑️  Управлять пресетами" + " " * 29 + "║")
    print("║  0. Выйти" + " " * 43 + "║")
    print("╚" + "═" * 56 + "╝")

    while True:
        try:
            choice = input(f"\n  👉 Выбери (0-{n_manage}): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  👋 Выход.")
            sys.exit(0)

        if choice == '0':
            print("\n  👋 Выход.")
            sys.exit(0)

        # Выбор пресета
        if has_presets:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(preset_names):
                    selected = presets[preset_names[idx]]
                    print(f"\n  ✅ Загружен пресет «{preset_names[idx]}»")
                    print(f"     {selected['provider']}: {selected['config'].get('model', '?')}")
                    return (selected['provider'], selected['config'])
            except ValueError:
                pass

        # Создать новый
        if choice == str(n_new):
            provider, config = select_provider_interactive({})
            _save_current_as_preset(provider, config)
            return (provider, config)

        # Управлять
        if has_presets and choice == str(n_manage):
            presets = load_presets()
            if not presets:
                print("  📭 Нет пресетов для удаления.")
                continue
            names = list(presets.keys())
            print("\n  ── Выбери пресет для удаления ──")
            for i, n in enumerate(names, 1):
                print(f"  {i}. {n}")
            print("  0. Отмена")
            try:
                c = input("  👉 Номер: ").strip()
                if c == '0':
                    continue
                idx = int(c) - 1
                if 0 <= idx < len(names):
                    del presets[names[idx]]
                    save_presets(presets)
                    print(f"  ✅ Пресет «{names[idx]}» удалён.")
            except (ValueError, EOFError):
                pass
            continue

        print(f"  ❌ Введи число от 0 до {n_manage}")
