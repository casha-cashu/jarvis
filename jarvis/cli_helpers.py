#!/usr/bin/env python3
"""
Хелперы для CLI: интерактивный выбор провайдера, ввод данных, опрос моделей.
"""

import os
import sys
import requests
from pathlib import Path
from typing import Tuple, Optional


def _fetch_ollama_models(url: str) -> list:
    """Получает список моделей из Ollama"""
    try:
        r = requests.get(f"{url}/api/tags", timeout=5)
        if r.status_code == 200:
            models = r.json().get('models', [])
            return [m['name'] for m in models]
    except:
        pass
    return []


def _fetch_openai_models(url: str, api_key: str = "") -> list:
    """Получает список моделей из OpenAI-совместимого API"""
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        r = requests.get(f"{url}/models", headers=headers, timeout=5)
        if r.status_code == 200:
            models = r.json().get('data', [])
            return [m['id'] for m in models]
    except:
        pass
    return []


def _pick_model(models: list, prompt: str = "  👉 Выбери модель") -> str:
    """Интерактивный выбор модели из списка или ручной ввод"""
    if models:
        print(f"\n  📋 Доступные модели ({len(models)} шт):")
        show = models[:20]
        for i, m in enumerate(show, 1):
            print(f"     {i}. {m}")
        if len(models) > 20:
            print(f"     ... и ещё {len(models) - 20}")
        print(f"     0. Ввести вручную")

        while True:
            try:
                choice = input(f"{prompt} (0-{len(show)}): ").strip()
                if choice == '0':
                    break
                idx = int(choice) - 1
                if 0 <= idx < len(show):
                    return show[idx]
                print(f"  ❌ Введи от 0 до {len(show)}")
            except ValueError:
                print("  ❌ Введи число")

    return input("  ✏️  Введи название модели: ").strip()


def _input_str(prompt: str, default: str = "") -> str:
    """Ввод строки с дефолтным значением"""
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default


def _save_current_as_preset(provider: str, config: dict):
    """Спрашивает имя и сохраняет пресет"""
    from jarvis.presets import load_presets, save_presets

    print("\n  ── Сохранить как пресет? ──")
    name = input("  Введи название пресета (Enter = не сохранять): ").strip()
    if not name:
        print("  ⏭️  Пресет не сохранён.")
        return

    presets = load_presets()
    presets[name] = {'provider': provider, 'config': config}
    save_presets(presets)
    print(f"  ✅ Пресет «{name}» сохранён!")

    print(f"\n  📋 Сохранённые пресеты ({len(presets)}):")
    for pname in presets:
        mark = " 👈" if pname == name else ""
        p = presets[pname]
        print(f"     • {pname}{mark} ({p['provider']}: {p['config'].get('model', '?')})")


def select_provider_interactive(config: dict) -> Tuple[str, dict]:
    """
    Интерактивная настройка LLM провайдера.
    Возвращает (provider_name, config_override).
    """
    print()
    print("╔" + "═" * 56 + "╗")
    print("║            🤖  НАСТРОЙКА LLM               ║")
    print("╠" + "═" * 56 + "╣")
    print("║  1. 🌐 OpenAI-совместимый (Kiro, OpenRouter, ║")
    print("║     локальный LLM, любой OpenAI proxy)      ║")
    print("║  2. 🎯 Anthropic Claude (прямой API)        ║")
    print("║  3. 💻 Ollama (локально)                    ║")
    print("║  0. Выйти                                   ║")
    print("╚" + "═" * 56 + "╝")

    while True:
        try:
            choice = input("\n  👉 Тип подключения (0-3): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  👋 Выход.")
            sys.exit(0)

        if choice == '1':
            print("\n  ── OpenAI-совместимый API ──")
            url = _input_str("  Введи base URL (с /v1)", "http://localhost:20128/v1")
            api_key = input("  Введи API ключ (Enter если не нужен): ").strip()

            print(f"  🔍 Проверяю {url}...")
            models = _fetch_openai_models(url, api_key)
            if models:
                print(f"  ✅ Сервер ответил, моделей: {len(models)}")
            else:
                print(f"  ⚠️  Не удалось получить список моделей")

            model = _pick_model(models, "  👉 Выбери модель")

            # api_key уезжает в override (и затем в Jarvis(provider_config=))
            # — не пишем в os.environ, чтобы ключ не утёк в child subprocess'ы.
            override = {
                'base_url': url,
                'api_key': api_key,
                'model': model,
                'temperature': 0.7,
                'max_tokens': 1024,
                'timeout': 30
            }
            print(f"\n  ✅ Настроено: OpenAI ({model})")
            return ('kiro', override)

        elif choice == '2':
            print("\n  ── Anthropic Claude ──")
            api_key = _input_str("  Введи API ключ Anthropic", os.getenv('ANTHROPIC_API_KEY', ''))
            if not api_key:
                print("  ❌ API ключ обязателен")
                continue

            anthro_models = [
                "claude-sonnet-4-20250514",
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ]
            model = _pick_model(anthro_models, "  👉 Выбери модель Claude")

            # См. комментарий выше — не пишем ключ в os.environ.
            override = {
                'api_key': api_key,
                'model': model,
                'temperature': 0.7,
                'max_tokens': 1024
            }
            print(f"\n  ✅ Настроено: Anthropic {model}")
            return ('anthropic', override)

        elif choice == '3':
            print("\n  ── Ollama (локальная модель) ──")
            url = _input_str("  Введи URL Ollama", "http://localhost:11434")

            print(f"  🔍 Проверяю {url}...")
            models = _fetch_ollama_models(url)
            if models:
                print(f"  ✅ Ollama работает. Модели: {', '.join(models)}")
                model = _pick_model(models, "  👉 Выбери модель")
            else:
                print(f"  ⚠️  Ollama не отвечает или нет моделей")
                model = _input_str("  ✏️  Введи название модели", "qwen2.5:3b")

            override = {
                'base_url': url,
                'model': model,
                'temperature': 0.7
            }
            print(f"\n  ✅ Настроено: Ollama {url} / {model}")
            return ('ollama', override)

        elif choice == '0':
            print("\n  👋 Выход.")
            sys.exit(0)
        else:
            print("  ❌ Введи 0, 1, 2 или 3")
