#!/usr/bin/env python3
"""
CLI для JARVIS — голосового ассистента

Использование:
  jarvis run                          # запуск (по умолч.)
  jarvis run -p ollama                # с конкретным провайдером
  jarvis run --mode continuous        # без wake word
  jarvis run --mode classic           # с wake word (по умолч.)
  jarvis run --wake-mode vad          # VAD-буфер для wake word
  jarvis run --mute                   # сразу в mute
  jarvis run --dry-run                # проверка без микро
  jarvis setup                        # мастер настройки
  jarvis test                         # тест модулей
  jarvis doctor                       # диагностика окружения
  jarvis presets                      # управление пресетами
  jarvis voice list                   # список TTS голосов
  jarvis voice download ru_RU-irina   # скачать голос
  jarvis dictation                    # режим диктовки
  jarvis service install              # systemd --user unit
  jarvis service remove               # удалить systemd unit
  jarvis -v                           # verbose режим
"""

import sys
import argparse
import subprocess
from pathlib import Path

from jarvis._env import sanitized_env


def _version() -> str:
    try:
        from importlib.metadata import version

        return f"JARVIS {version('jarvis-voice-assistant')}"
    except Exception:
        return "JARVIS (не установлен как пакет — версия недоступна)"


def cmd_run(args):
    """Запуск голосового ассистента"""
    from jarvis import Jarvis

    # Пресет
    provider_config = None
    provider = args.provider

    if args.preset:
        from jarvis.presets import load_presets

        presets = load_presets()
        if args.preset in presets:
            p = presets[args.preset]
            provider = p["provider"]
            provider_config = p["config"]
        else:
            print(f"❌ Пресет «{args.preset}» не найден")
            sys.exit(1)

    # Режимы передаются в Jarvis
    extra = {
        "continuous": args.mode == "continuous",
        "muted": args.mute,
        "wake_mode": args.wake_mode,
    }

    jarvis = Jarvis(
        config_path=args.config,
        verbose=args.verbose,
        provider=provider,
        provider_config=provider_config,
        **extra,
    )
    jarvis.initialize()
    jarvis.run()


def cmd_doctor(args):
    """Диагностика окружения (конфиг, аудио, модели, LLM)."""
    from jarvis.doctor import exit_code, print_report, run_checks

    print("🩺 JARVIS doctor")
    checks = run_checks(args.config)
    print_report(checks)
    sys.exit(exit_code(checks))


def cmd_setup(args):
    """Мастер настройки ассистента"""
    from jarvis.setup import setup_wizard

    setup_wizard()


def cmd_test(args):
    """Запуск тестов (режим dry-run)"""
    from jarvis import Jarvis
    from jarvis.presets import load_presets

    provider = args.provider
    provider_config = None

    if args.preset:
        presets = load_presets()
        if args.preset in presets:
            p = presets[args.preset]
            provider = p["provider"]
            provider_config = p["config"]

    jarvis = Jarvis(
        config_path=args.config,
        verbose=True,
        dry_run=True,
        provider=provider,
        provider_config=provider_config,
    )
    try:
        jarvis.initialize()
        print("\n✅ Тест пройден — все модули инициализированы")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)


def cmd_presets(args):
    """Управление пресетами провайдеров"""
    from jarvis.presets import load_presets, save_presets, select_preset_or_create

    if args.delete:
        presets = load_presets()
        if args.delete in presets:
            del presets[args.delete]
            save_presets(presets)
            print(f"✅ Пресет «{args.delete}» удалён")
        else:
            print(f"❌ Пресет «{args.delete}» не найден")
        return

    if args.list:
        presets = load_presets()
        if not presets:
            print("📭 Нет сохранённых пресетов")
            return
        print(f"📋 Сохранённые пресеты ({len(presets)}):")
        for name, p in presets.items():
            print(f"   • {name} ({p['provider']}: {p['config'].get('model', '?')})")
        return

    # Интерактивный режим
    select_preset_or_create()


def cmd_voice(args):
    """Управление TTS голосами"""

    if args.action == "list":
        print("📋 TTS голоса Piper (русские):")
        print("   • ru_RU-dmitri-medium  — Dmitri (50 MB, по умолч.)")
        print("   • ru_RU-irina-medium   — Irina (50 MB)")
        print("   • ru_RU-ruslan-medium  — Ruslan (50 MB)")
        print("   • ru_RU-denis-medium   — Denis (50 MB)")
        print("\nУстановка: jarvis voice download <имя>")
        return

    if args.action == "download":
        import re

        import requests

        name = args.model
        # HF layout: ru/ru_RU/<голос>/<качество>/ru_RU-<голос>-<качество>.onnx
        m = re.fullmatch(r"ru_RU-([a-z]+)-(medium|low|high)", name)
        if not m:
            print(f"❌ Неверное имя голоса: {name}")
            print("   Формат: ru_RU-<голос>-<качество>, напр. ru_RU-dmitri-medium")
            print("   Список: jarvis voice list")
            sys.exit(1)
        speaker, quality = m.groups()
        voices_dir = Path.home() / ".local" / "share" / "piper" / "voices"
        voices_dir.mkdir(parents=True, exist_ok=True)

        base = (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main"
            f"/ru/ru_RU/{speaker}/{quality}/{name}"
        )

        print(f"⏬ Скачиваю {name}...")
        failed = []
        for ext in (".onnx", ".onnx.json"):
            dest = voices_dir / f"{name}{ext}"
            if dest.exists():
                print(f"   ✅ {name}{ext} уже есть")
                continue
            print(f"   📥 {dest.name}...")
            r = requests.get(base + ext, stream=True, timeout=60)
            if r.status_code != 200:
                print(f"   ⚠️  Не удалось скачать {name}{ext} (HTTP {r.status_code})")
                failed.append(ext)
                continue
            tmp = Path(str(dest) + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            tmp.replace(dest)
            print(f"   ✅ {name}{ext} скачан")

        if failed:
            print(f"\n❌ Не скачались: {', '.join(failed)} — голос не установлен")
            sys.exit(1)

        print(f"\n✅ Голос {name} установлен!")
        print(f"   Путь: {voices_dir}")
        print(f'   В config.yaml укажи: piper.model_path: "{voices_dir / name}.onnx"')


def cmd_dictation(args):
    """Режим диктовки (голосовой ввод текста в активное окно)"""
    from jarvis import Jarvis

    jarvis = Jarvis(
        config_path=args.config,
        verbose=args.verbose,
        provider=getattr(args, "provider", None),
        muted=True,
        dry_run=False,
    )
    jarvis.initialize()
    print("\n" + "=" * 50)
    print("   📝 JARVIS — Режим диктовки")
    print("   Голосовой ввод в активное окно")
    print("   Нажмите Ctrl+C для выхода")
    print("=" * 50 + "\n")
    from jarvis.modules.dictation import dictation_loop

    try:
        result = dictation_loop(jarvis.stt)
        print(f"\n✅ Диктовка завершена, {len(result.split())} слов.")
    except KeyboardInterrupt:
        print("\n⏹ Диктовка прервана.")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)


def _has_systemd() -> bool:
    """Проверяет, доступен ли systemctl"""
    try:
        import subprocess

        r = subprocess.run(
            ["systemctl", "--version"],
            capture_output=True,
            timeout=3,
            env=sanitized_env(),
        )
        return r.returncode == 0
    except Exception:
        return False


def cmd_service(args):
    """Управление systemd-сервисом (только Linux с systemd)"""
    if sys.platform != "linux" or not _has_systemd():
        print("❌ systemd-сервис доступен только на Linux с systemd")
        sys.exit(1)

    if args.action == "install":
        unit_content = f"""[Unit]
Description=JARVIS Voice Assistant
After=sound.target

[Service]
Type=simple
ExecStart={sys.executable} -m jarvis run --preset default
WorkingDirectory={Path.cwd()}
Restart=always
RestartSec=5
EnvironmentFile={Path.cwd() / ".env"}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path = unit_dir / "jarvis.service"
        unit_path.write_text(unit_content)
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            env=sanitized_env(),
        )
        print(f"✅ systemd unit установлен: {unit_path}")
        print("   Запуск: systemctl --user start jarvis")
        print("   Автостарт: systemctl --user enable jarvis")
        print("   Логи: journalctl --user -u jarvis -f")

    elif args.action == "remove":
        unit_path = Path.home() / ".config" / "systemd" / "user" / "jarvis.service"
        if unit_path.exists():
            subprocess.run(
                ["systemctl", "--user", "stop", "jarvis"],
                capture_output=True,
                env=sanitized_env(),
            )
            subprocess.run(
                ["systemctl", "--user", "disable", "jarvis"],
                capture_output=True,
                env=sanitized_env(),
            )
            unit_path.unlink()
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                env=sanitized_env(),
            )
            print("✅ Сервис удалён")
        else:
            print("❌ Сервис не найден")

    elif args.action == "status":
        subprocess.run(["systemctl", "--user", "status", "jarvis"], env=sanitized_env())


def main():
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="JARVIS — голосовой ассистент для Linux",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  jarvis run                         # запуск с меню выбора
  jarvis run -p ollama               # Ollama без меню
  jarvis run --preset home           # загрузить пресет home
  jarvis run --mode continuous       # без wake word
  jarvis run --dry-run               # проверка конфига
  jarvis setup                       # мастер настройки
  jarvis voice download ru_RU-irina  # скачать голос TTS
  jarvis service install             # автозапуск при старте
        """,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Подробные логи (режим разработчика)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=_version(),
        help="Показать версию и выйти",
    )

    sub = parser.add_subparsers(dest="command", help="Команда")

    # ── run ──
    p_run = sub.add_parser("run", help="Запустить ассистента (по умолчанию)")
    p_run.add_argument(
        "-p",
        "--provider",
        choices=["ollama", "openai", "openrouter", "anthropic"],
        help="LLM провайдер (без меню)",
    )
    p_run.add_argument(
        "--preset", type=str, metavar="NAME", help="Загрузить пресет провайдера"
    )
    p_run.add_argument(
        "--mode",
        choices=["classic", "continuous"],
        default="classic",
        help="Режим: classic (wake word) или continuous (без wake word)",
    )
    p_run.add_argument(
        "--wake-mode",
        choices=["classic", "vad"],
        default="classic",
        help="Метод детекции wake word",
    )
    p_run.add_argument("--mute", action="store_true", help="Старт в режиме тишины")
    p_run.add_argument(
        "--dry-run", action="store_true", help="Проверка конфига без микрофона"
    )
    p_run.add_argument(
        "--config", type=str, default="config.yaml", help="Путь к конфигу"
    )

    # ── setup ──

    # ── test ──
    p_test = sub.add_parser("test", help="Тест модулей (dry-run)")
    p_test.add_argument(
        "-p", "--provider", choices=["ollama", "openai", "openrouter", "anthropic"]
    )
    p_test.add_argument("--preset", type=str, metavar="NAME")
    p_test.add_argument("--config", type=str, default="config.yaml")

    # ── presets ──
    p_pre = sub.add_parser("presets", help="Управление пресетами")
    p_pre.add_argument("--list", action="store_true", help="Список пресетов")
    p_pre.add_argument("--delete", type=str, metavar="NAME", help="Удалить пресет")

    # ── voice ──
    p_voice = sub.add_parser("voice", help="Управление TTS голосами")
    p_voice.add_argument("action", choices=["list", "download"], help="Действие")
    p_voice.add_argument(
        "model", nargs="?", default="", help="Название голоса (для download)"
    )

    # ── dictation ──
    p_dict = sub.add_parser("dictation", help="Режим диктовки")
    p_dict.add_argument(
        "-p",
        "--provider",
        choices=["ollama", "openai", "openrouter", "anthropic"],
        help="LLM провайдер (не исп. в диктовке)",
    )
    p_dict.add_argument(
        "--config", type=str, default="config.yaml", help="Путь к конфигу"
    )

    # ── doctor ──
    p_doc = sub.add_parser(
        "doctor", help="Диагностика окружения (конфиг, аудио, модели, LLM)"
    )
    p_doc.add_argument(
        "--config", type=str, default="config.yaml", help="Путь к конфигу"
    )

    # ── service ──
    p_svc = sub.add_parser("service", help="Управление systemd-сервисом")
    p_svc.add_argument(
        "action", choices=["install", "remove", "status"], help="Действие"
    )

    args = parser.parse_args()

    # Без команды = run
    if not args.command:
        # Перенаправляем в run
        sys.argv = [sys.argv[0], "run"] + sys.argv[1:]
        args = parser.parse_args()

    # Диспатч
    commands = {
        "run": cmd_run,
        "setup": cmd_setup,
        "test": cmd_test,
        "presets": cmd_presets,
        "voice": cmd_voice,
        "dictation": cmd_dictation,
        "doctor": cmd_doctor,
        "service": cmd_service,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
