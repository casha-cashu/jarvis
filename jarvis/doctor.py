"""jarvis doctor — диагностика окружения одной командой (HANDOFF TODO #5).

Проверяет конфиг (через forbid-схему — ловит опечатки), аудио-инструменты,
модели STT/TTS, плееры, LLM-провайдера, словари команд и адаптер DE.
Никогда не падает: каждая проверка возвращает статус, doctor собирает
отчёт и выставляет exit code. Безопасно запускать где угодно (CI, docker):
аудио-устройства не открываются, сеть опрашивается только для ollama.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

OK, WARN, FAIL = "ok", "warn", "fail"


def run_checks(config_path: str = "config.yaml") -> list[dict[str, Any]]:
    """Собирает список проверок. Каждая: {name, status, detail}."""
    checks: list[dict[str, Any]] = []
    checks.append(_check_python())
    checks.append(_check_config(config_path))

    config = checks[1].get("config") or {}
    checks.append(_check_data_files(config))
    checks.append(_check_platform())
    checks.append(_check_stt(config))
    checks.append(_check_tts(config))
    checks.append(_check_players())
    checks.append(_check_llm(config))
    checks.append(_check_state_dirs())
    return checks


def exit_code(checks: list[dict[str, Any]]) -> int:
    """0 — нет FAIL; 1 — есть хотя бы один критический провал."""
    return 1 if any(c["status"] == FAIL for c in checks) else 0


def print_report(checks: list[dict[str, Any]]) -> None:
    icons = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
    for c in checks:
        print(f"  {icons[c['status']]} {c['name']}: {c['detail']}")
    fails = sum(1 for c in checks if c["status"] == FAIL)
    warns = sum(1 for c in checks if c["status"] == WARN)
    tail = f"  Итого: {len(checks) - fails - warns} ок, {warns} предупреждений, {fails} ошибок"
    print(tail)


# ── Проверки ─────────────────────────────────────────────────────────────


def _check_python() -> dict[str, Any]:
    v = sys.version_info
    if v < (3, 10):
        return {
            "name": "Python",
            "status": FAIL,
            "detail": f"{v.major}.{v.minor} — нужен >=3.10",
        }
    if v >= (3, 13):
        return {
            "name": "Python",
            "status": WARN,
            "detail": f"{v.major}.{v.minor} — у vosk нет wheels для 3.13+ "
            "(STT-движок whisper работает; vosk — только из не-PyPI источников)",
        }
    return {"name": "Python", "status": OK, "detail": f"{v.major}.{v.minor}.{v.micro}"}


def _check_config(config_path: str) -> dict[str, Any]:
    """Конфиг читается и проходит forbid-схему (опечатки ключей = fail)."""
    p = Path(config_path)
    if not p.is_absolute():
        p = Path.cwd() / config_path
    if not p.exists():
        return {
            "name": "Конфиг",
            "status": FAIL,
            "detail": f"{p} не найден — скопируй config.example.yaml в config.yaml",
        }
    try:
        from jarvis.config_loader import ConfigLoader

        config = ConfigLoader(str(p)).load()
    except SystemExit:
        return {
            "name": "Конфиг",
            "status": FAIL,
            "detail": f"{p}: невалиден (см. ошибку выше)",
        }
    except Exception as e:  # noqa: BLE001 — диагностика не должна падать
        return {"name": "Конфиг", "status": FAIL, "detail": str(e)}
    return {
        "name": "Конфиг",
        "status": OK,
        "detail": f"{p} (схема ок)",
        "config": config,
    }


def _check_data_files(config: dict) -> dict[str, Any]:
    """Словари команд/приложений: в dev — рядом, в packaged — в _MEIPASS."""
    from jarvis.resources import resource_path

    cfg = config.get("commands", {})
    missing = []
    for key in ("dictionary_path", "apps_dictionary_path"):
        resolved = resource_path(cfg.get(key, f"data/{key.split('_')[0]}.json"))
        if not Path(resolved).exists():
            missing.append(cfg.get(key, key))
    if missing:
        return {
            "name": "Словари команд",
            "status": WARN,
            "detail": f"не найдены: {', '.join(missing)} — локальные команды и "
            "запуск приложений не будут работать",
        }
    return {
        "name": "Словари команд",
        "status": OK,
        "detail": "commands.json + apps.json",
    }


def _check_platform() -> dict[str, Any]:
    try:
        from jarvis.modules.platform_adapter import PlatformAdapter

        pa = PlatformAdapter()
    except Exception as e:  # noqa: BLE001
        return {"name": "DE/адаптер", "status": FAIL, "detail": f"детект упал: {e}"}
    if pa.de in ("unknown", ""):
        return {
            "name": "DE/адаптер",
            "status": WARN,
            "detail": f"OS={pa.os}, DE не определён — окна/воркспейсы будут заглушками",
        }
    return {"name": "DE/адаптер", "status": OK, "detail": f"OS={pa.os}, DE={pa.de}"}


def _check_stt(config: dict) -> dict[str, Any]:
    stt_cfg = config.get("stt", {})
    engine = stt_cfg.get("engine", "vosk")
    if engine == "whisper":
        wcfg = stt_cfg.get("whisper", {})
        model_path = wcfg.get("model_path")
        if model_path and not Path(model_path).exists():
            return {
                "name": "STT (whisper)",
                "status": WARN,
                "detail": f"локальная модель {model_path} не найдена — скачается из HF при старте",
            }
        size = wcfg.get("model_size", "tiny")
        return {"name": "STT (whisper)", "status": OK, "detail": f"model_size={size}"}

    try:
        from jarvis.modules.stt import VoskSTT  # noqa: PLC0415
    except ImportError:
        return {
            "name": "STT (vosk)",
            "status": WARN,
            "detail": "vosk не установлен — наличие модели не проверить",
        }

    resolved = VoskSTT._resolve_model_path(
        stt_cfg.get("vosk", {}).get("model_path", "auto")
    )
    if Path(resolved).exists():
        return {"name": "STT (vosk)", "status": OK, "detail": f"модель: {resolved}"}
    return {
        "name": "STT (vosk)",
        "status": WARN,
        "detail": "модель не найдена (ищется в models/, ~/.local/share/vosk, ~/models/vosk) — запусти jarvis setup",
    }


def _check_tts(config: dict) -> dict[str, Any]:
    tts_cfg = config.get("tts", {})
    engine = tts_cfg.get("engine", "piper")
    if engine != "piper":
        return {
            "name": f"TTS ({engine})",
            "status": OK,
            "detail": "проверка не требуется",
        }
    piper_cfg = tts_cfg.get("piper", {})
    binary = piper_cfg.get("binary_path", "piper")
    model = piper_cfg.get("model_path")
    problems = []
    if not shutil.which(str(binary)):
        problems.append(
            f"бинарь {binary} не найден (pacman -S piper-tts / yay -S piper-tts)"
        )
    if model and not Path(model).exists():
        problems.append(f"модель {model} не найдена (jarvis voice download)")
    if problems:
        return {"name": "TTS (piper)", "status": WARN, "detail": "; ".join(problems)}
    return {
        "name": "TTS (piper)",
        "status": OK,
        "detail": f"{binary} + модель на месте",
    }


def _check_players() -> dict[str, Any]:
    """Плеер для озвучки: mpv → ffplay → aplay → paplay (порядок tts.py)."""
    found = [p for p in ("mpv", "ffplay", "aplay", "paplay") if shutil.which(p)]
    if found:
        return {"name": "Аудио-плеер", "status": OK, "detail": found[0]}
    return {
        "name": "Аудио-плеер",
        "status": WARN,
        "detail": "ни mpv/ffplay/aplay/paplay в PATH — озвучка не проиграется",
    }


def _check_llm(config: dict) -> dict[str, Any]:
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "ollama")
    if provider == "ollama":
        ollama_cfg = llm_cfg.get("ollama", {})
        base_url = ollama_cfg.get("base_url", "http://localhost:11434")
        model = ollama_cfg.get("model", "?")
        try:
            import requests  # noqa: PLC0415

            r = requests.get(f"{base_url}/api/tags", timeout=2)
            r.raise_for_status()
            models = [m.get("name", "?") for m in r.json().get("models", [])]
            if model not in models:
                return {
                    "name": "LLM (ollama)",
                    "status": WARN,
                    "detail": f"{base_url} жив, но модели {model} нет — ollama pull {model}",
                }
            return {
                "name": "LLM (ollama)",
                "status": OK,
                "detail": f"{model} на {base_url}",
            }
        except Exception as e:  # noqa: BLE001
            return {
                "name": "LLM (ollama)",
                "status": FAIL,
                "detail": f"{base_url} недоступен: {e} — запусти 'ollama serve'",
            }
    # облачные провайдеры: ключ в конфиге или окружении (не печатаем значение)
    sec = llm_cfg.get(provider, {})
    key = sec.get("api_key") or ""
    env_var = f"{provider.upper()}_API_KEY"
    has_key = bool(key and not key.startswith("${") or os.getenv(env_var))
    if has_key:
        return {"name": f"LLM ({provider})", "status": OK, "detail": "ключ задан"}
    return {
        "name": f"LLM ({provider})",
        "status": FAIL,
        "detail": f"нет api_key в конфиге и ${env_var} в окружении",
    }


def _check_state_dirs() -> dict[str, Any]:
    """Каталоги состояния: history/reminders пишутся при работе."""
    state = Path.home() / ".local" / "share" / "jarvis"
    try:
        state.mkdir(parents=True, exist_ok=True)
        probe = state / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return {"name": "Каталог состояния", "status": FAIL, "detail": f"{state}: {e}"}
    return {"name": "Каталог состояния", "status": OK, "detail": str(state)}
