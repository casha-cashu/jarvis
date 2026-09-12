"""Line-delimited JSON bridge between the Tauri UI and JARVIS.

The bridge keeps stdout machine-readable: diagnostics belong on stderr.
Commands: start, stop, status, configure, message, list_models, timers,
clear_history, switch_session, delete_session, purge_session,
purge_all_sessions.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

import requests

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from jarvis import Jarvis
    from jarvis.modules.reminder import ReminderManager

T = TypeVar("T")

ANTHROPIC_VERSION = "2023-06-01"


def should_setup_runtime_paths() -> bool:
    """Returns True if runtime path extension is needed (frozen bundle or explicit env override)."""
    return bool(
        getattr(sys, "frozen", False)
        or os.environ.get("JARVIS_ENABLE_RUNTIME_PATHS") == "1"
    )


_CANDIDATE_PATHS: Optional[list[str]] = None


def _setup_runtime_paths(force: bool = False) -> None:
    """If running inside a PyInstaller frozen bundle (or explicitly forced), make system
    and local site-packages available so optional hardware/audio packages (pyaudio,
    faster-whisper, torch) can be loaded dynamically on demand.
    """
    if not force and not should_setup_runtime_paths():
        return

    candidates = _CANDIDATE_PATHS
    if candidates is None:
        candidates = [
            os.path.expanduser("~/.local/lib/python3.14/site-packages"),
            os.path.expanduser("~/.local/lib/python3.13/site-packages"),
            "/usr/lib/python3.14/site-packages",
            "/usr/lib/python3.13/site-packages",
            "/usr/local/lib/python3.14/site-packages",
            "/usr/local/lib/python3.13/site-packages",
        ]
        for p in ["./venv", "../venv", os.path.expanduser("~/Projects/jarvis-py/venv")]:
            d = os.path.join(p, "lib")
            if os.path.isdir(d):
                try:
                    for py_dir in os.listdir(d):
                        sp = os.path.join(d, py_dir, "site-packages")
                        if os.path.isdir(sp):
                            candidates.append(os.path.abspath(sp))
                except Exception:
                    pass
    for c in candidates:
        if os.path.isdir(c) and c not in sys.path:
            sys.path.append(c)


if should_setup_runtime_paths():
    _setup_runtime_paths()

if getattr(sys, "frozen", False):
    # PyInstaller сайдкар работает в чистом ONNX/CTranslate2 режиме.
    # Блокируем импорт хостового PyTorch через meta_path finder, чтобы исключить
    # конфликт pybind11 RpcBackendOptions и сохранить совместимость со sklearn/transformers.
    class _BlockTorchFinder:
        def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
            if fullname == "torch" or fullname.startswith("torch."):
                raise ModuleNotFoundError(
                    f"No module named '{fullname}' (PyTorch disabled in JARVIS sidecar)"
                )
            return None

    sys.meta_path.insert(0, _BlockTorchFinder())


class Bridge:
    def __init__(self) -> None:
        self.jarvis: Jarvis | None = None
        self.started = False
        self._pending_config: Optional[dict[str, Any]] = None
        self._current_session: Optional[str] = None
        self._sessions_dir = (
            Path(
                os.environ.get("JARVIS_DATA_DIR", "~/.local/share/jarvis")
            ).expanduser()
            / "ui-history"
        )
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._continuous_mode: bool = False
        self._voice_enabled: bool = False
        self._voice_lock = threading.Lock()
        self._voice_thread: Optional[threading.Thread] = None
        self._voice_stop = threading.Event()
        # Мультиплексирование: длинный «message» выполняется в отдельном
        # потоке, короткие команды обслуживаются reader-циклом сразу.
        self._message_lock = threading.Lock()
        self._message_busy = False
        self._stop_event = threading.Event()
        self._start_lock = threading.Lock()
        # id активного message: стрим/инструмент строки помечаются им,
        # чтобы Rust-роутер доставил их в персональный канал
        self._current_id: str | None = None
        # Real protocol stdout, captured before any contextlib redirect.
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(errors="replace")
            except Exception:
                pass
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(errors="replace")
            except Exception:
                pass
        self._proto_out = sys.stdout
        self._stdout_lock = threading.Lock()

    @staticmethod
    def _serialize(obj: dict[str, Any]) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return json.dumps(obj, ensure_ascii=True)

    def _try_begin_message(self) -> bool:
        """True если сообщение начало обрабатываться в этом потоке."""
        with self._message_lock:
            if self._message_busy:
                return False
            self._stop_event.clear()
            self._message_busy = True
            return True

    def _end_message(self) -> None:
        with self._message_lock:
            self._message_busy = False

    def _write_response(self, obj: dict[str, Any]) -> None:
        """Ответ протокола — ВСЕГДА через реальный stdout (минуя
        redirect_stdout рабочей ветки: иначе мультиплексированные ответы
        терялись бы в stderr)."""
        try:
            with self._stdout_lock:
                self._proto_out.write(self._serialize(obj) + "\n")
                self._proto_out.flush()
        except Exception:
            pass

    def _emit_delta(self, delta: str) -> None:
        """Streams one chunk as a JSONL line; Rust forwards it to the UI."""
        if self._stop_event.is_set():
            raise InterruptedError("Генерация остановлена пользователем")
        try:
            payload: dict[str, Any] = {"ok": True, "stream": True, "delta": delta}
            if self._current_id:
                payload["id"] = self._current_id
            with self._stdout_lock:
                self._proto_out.write(self._serialize(payload) + "\n")
                self._proto_out.flush()
        except Exception:
            pass  # UI stream loss must never kill generation

    def _emit_tool(self, name: str, args: dict) -> None:
        """Notifies the UI that a tool is about to execute."""
        try:
            payload: dict[str, Any] = {
                "ok": True,
                "tool": {"name": name, "args": args},
            }
            if self._current_id:
                payload["id"] = self._current_id
            with self._stdout_lock:
                self._proto_out.write(self._serialize(payload) + "\n")
                self._proto_out.flush()
        except Exception:
            pass

    def _emit_tool_result(self, name: str, args: dict, result: str) -> None:
        """Notifies the UI of a finished tool execution (output truncated)."""
        try:
            payload: dict[str, Any] = {
                "ok": True,
                "tool_result": {
                    "name": name,
                    "args": args,
                    "output": result[:2000],
                },
            }
            if self._current_id:
                payload["id"] = self._current_id
            with self._stdout_lock:
                self._proto_out.write(self._serialize(payload) + "\n")
                self._proto_out.flush()
        except Exception:
            pass

    def _quiet_call(self, callback: Callable[[], T]) -> T:
        """Keep human-oriented backend prints off the JSONL protocol stdout."""
        with contextlib.redirect_stdout(sys.stderr):
            return callback()

    def _apply_config(self) -> None:
        if not self._pending_config or self.jarvis is None:
            return
        preset = self._pending_config
        api_type = preset["type"]
        llm_config = self.jarvis.config["llm"]
        llm_config["provider"] = api_type
        provider_config = llm_config.setdefault(api_type, {})
        endpoint = preset.get("endpoint") or ""
        api_key = preset.get("api_key")
        if not api_key and self._is_local_endpoint(endpoint):
            api_key = "local-no-key-required"
        provider_config["api_key"] = api_key
        provider_config["model"] = preset.get("model") or provider_config.get("model")
        provider_config["base_url"] = endpoint
        if preset.get("temperature") is not None:
            llm_config["temperature"] = preset["temperature"]
            provider_config["temperature"] = preset["temperature"]
        if preset.get("max_tokens") is not None:
            llm_config["max_tokens"] = preset["max_tokens"]
            provider_config["max_tokens"] = preset["max_tokens"]
        # Bash agent must be enabled explicitly for tool-calling to work.
        # ResponsePipeline copies these values at construction time (before the
        # preset was applied), so mirror them onto the live pipeline instance.
        agent_enabled = bool(preset.get("agent_enabled", True))
        approval_mode = preset.get("approval_mode") or "auto"
        llm_config["agent_enabled"] = agent_enabled
        llm_config["agent_approval_mode"] = approval_mode
        self.jarvis.response.agent_enabled = agent_enabled
        self.jarvis.response.agent_approval_mode = approval_mode

    def _shutdown_reminders(self) -> None:
        """Cancels timers owned by the current reminder manager.

        Restart flows (stop / configure / repeated start) drop the old
        Jarvis without touching its reminder timers; skipping this lets
        every restart fire each reminder N times — once per leaked manager.
        """
        jarvis = self.jarvis
        if jarvis is None:
            return
        mgr = jarvis.reminder_mgr
        if mgr is not None:
            self._quiet_call(mgr.shutdown)
            jarvis.reminder_mgr = None

    def _start(self) -> dict[str, Any]:
        # Сериализуем: двойной _start (автостарт message + кнопка Start)
        # порождал два Jarvis и течь ReminderManager'ов
        with self._start_lock:
            return self._start_serialized()

    def _start_serialized(self) -> dict[str, Any]:
        if self.started:
            return {"ok": True, "started": True}

        try:
            from jarvis import Jarvis

            self._shutdown_reminders()

            # Text mode: initialize only the response pipeline; never open audio.
            import os

            # CI/hermetic runs override via JARVIS_CONFIG_PATH (repo ships
            # config.example.yaml only; personal config.yaml is gitignored).
            config_path = os.environ.get("JARVIS_CONFIG_PATH", "config.yaml")
            self.jarvis = self._quiet_call(
                lambda: Jarvis(config_path=config_path, dry_run=True)
            )
            self._apply_config()
            self._quiet_call(self.jarvis.response.start)
            self.jarvis.tts = self.jarvis.response.tts
            self.jarvis.llm = self.jarvis.response.llm
            self.jarvis.commands = self.jarvis.response.commands
            self.jarvis.platform = self.jarvis.response.platform
            # Reminders work without audio: trigger notifications go to stderr.
            from jarvis.modules.reminder import ReminderManager

            reminder_mgr: ReminderManager = ReminderManager(
                on_trigger=lambda text: print(
                    f"⏰ НАПОМИНАНИЕ: {text}", file=sys.stderr
                )
            )
            self.jarvis.reminder_mgr = reminder_mgr
            self.started = True
            return {"ok": True, "started": True}
        except SystemExit as exc:
            self.started = False
            self.jarvis = None
            code = exc.code if exc.code is not None else 1
            return {
                "ok": False,
                "error": f"Ошибка конфигурации при запуске (код {code})",
            }
        except Exception as exc:
            self.started = False
            self.jarvis = None
            return {"ok": False, "error": f"Ошибка при запуске: {exc}"}

    def _resolve_marker(self, response: str) -> str:
        """Convert voice-command markers returned by process_query into
        user-visible text (the conversation manager normally does this for
        the voice path; text mode needs it here)."""
        if not response or not response.startswith("__"):
            return response
        if response.startswith("__REMINDER__:"):
            _, _, rest = response.partition(":")
            seconds_str, _, reminder_text = rest.partition(":")
            try:
                seconds = int(seconds_str)
                jarvis = self.jarvis
                mgr = jarvis.reminder_mgr if jarvis is not None else None
                if mgr:
                    return self._quiet_call(lambda: mgr.add(reminder_text, seconds))
            except ValueError:
                pass
            return "Не удалось установить напоминание."
        if response == "__REMINDER_LIST__":
            from jarvis.modules.reminder import ReminderManager

            reminders = ReminderManager.list_active()
            if reminders:
                lines = [f"«{t}» — через {s} сек" for t, s in reminders]
                return "Активные напоминания:\n" + "\n".join(lines)
            return "Нет активных напоминаний."
        if response == "__MUTE__":
            return "Хорошо, сэр. Я замолкаю."
        if response == "__UNMUTE__":
            return "Я снова слушаю, сэр."
        if response == "__DICTATE__":
            return "Режим диктовки недоступен в текстовом режиме."
        if response == "__EXIT__":
            return "Текстовая сессия продолжается; используйте кнопку Стоп."
        return ""

    # ── Per-session LLM context ────────────────────────────────────────────
    # HISTORY_FILE holds the ACTIVE session's history (clients read it at
    # construction and persist on every message). Archives live in
    # ui-history/<session>.json and are swapped when the UI switches chats,
    # so past chats never leak into new ones.

    @staticmethod
    def _history_dir() -> Any:
        from pathlib import Path

        from jarvis.modules import llm as llm_module

        d = llm_module.HISTORY_FILE.parent / "ui-history"
        d.mkdir(parents=True, exist_ok=True)
        return Path(d)

    def _all_clients(self) -> list[Any]:
        mgr = self.jarvis.llm if self.jarvis else None
        clients = getattr(mgr, "clients", None)
        if isinstance(clients, dict):
            return [c for c in clients.values() if c is not None]
        primary = getattr(mgr, "primary", None)
        return [primary] if primary is not None else []

    def _archive_current(self) -> None:
        from jarvis.modules import llm as llm_module

        if not self._current_session:
            return
        clients = self._all_clients()
        hist = clients[0].history if clients else llm_module._load_history()
        path = self._history_dir() / f"{self._current_session}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def _set_clients_history(self, hist: list[Any]) -> None:
        for client in self._all_clients():
            limit = getattr(client, "max_history", 20)
            clean = [
                m
                for m in hist
                if isinstance(m, dict) and "role" in m and "content" in m
            ]
            client.history = clean[-limit:] if len(clean) > limit else clean

    def _clear_llm_cache(self) -> None:
        """Drops the LRU answer cache — its entries belong to the chat that
        produced them; after a context switch a cached hit would replay
        another conversation's answer."""
        mgr = self.jarvis.llm if self.jarvis else None
        cache = getattr(mgr, "_cache", None)
        if cache is not None:
            cache.clear()

    def _archive_legacy_history(self) -> None:
        """Archives CLI-era history.json before the first session switch.

        The very first switch (``_current_session is None``) would otherwise
        overwrite the user's existing conversation with the target chat's
        context; park it under ui-history/_legacy-cli.json instead.
        """
        from jarvis.modules import llm as llm_module

        if self._current_session is not None:
            return
        hist = llm_module._load_history()
        if not hist:
            return
        path = self._history_dir() / "_legacy-cli.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def _switch_session(self, sid: str) -> dict[str, Any]:
        import re

        from jarvis.modules import llm as llm_module

        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", sid):
            return {"ok": False, "error": "Некорректный id сессии"}
        self._archive_legacy_history()
        self._archive_current()
        src = self._history_dir() / f"{sid}.json"
        try:
            hist = json.loads(src.read_text(encoding="utf-8")) if src.exists() else []
        except Exception:
            hist = []
        llm_module._save_history(hist if isinstance(hist, list) else [])
        self._set_clients_history(hist if isinstance(hist, list) else [])
        self._current_session = sid
        self._clear_llm_cache()
        return {"ok": True, "session": sid}

    def _delete_session(self, sid: str) -> dict[str, Any]:
        """Removes a chat's archived context; empties memory if it's active."""
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", sid):
            return {"ok": False, "error": "Некорректный id сессии"}
        path = self._history_dir() / f"{sid}.json"
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            return {"ok": False, "error": f"Не удалось удалить архив: {exc}"}
        if self._current_session == sid:
            # Active chat is gone: wipe live context so the next chat is clean.
            from jarvis.modules import llm as llm_module

            llm_module._save_history([])
            self._set_clients_history([])
            self._clear_llm_cache()
            self._current_session = None
        return {"ok": True}

    def _purge_session(self, sid: str) -> dict[str, Any]:
        """Deletes one archived chat; wipes live context if it's active."""
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", sid):
            return {"ok": False, "error": "Некорректный id сессии"}
        path = self._history_dir() / f"{sid}.json"
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            return {"ok": False, "error": f"Не удалось удалить архив: {exc}"}
        if self._current_session == sid:
            from jarvis.modules import llm as llm_module

            llm_module._save_history([])
            self._set_clients_history([])
            self._clear_llm_cache()
        return {"ok": True}

    def _purge_all_sessions(self) -> dict[str, Any]:
        """Wipes every archived chat and the live LLM context."""
        from jarvis.modules import llm as llm_module

        llm_module._save_history([])
        self._set_clients_history([])
        self._clear_llm_cache()
        removed = 0
        for path in sorted(self._history_dir().glob("*.json")):
            with contextlib.suppress(OSError):
                path.unlink()
                removed += 1
        self._current_session = None
        return {"ok": True, "removed": removed}

    # Команды, меняющие состояние моста: во время активного «message»
    # они отклоняются — иначе гонка с идущей генерацией.
    # Команда "stop" исключена: UI "Стоп" должна мгновенно прерывать генерацию.
    _MUTATING_COMMANDS = frozenset(
        {
            "start",
            "set_config_value",
            "configure",
            "switch_session",
            "delete_session",
            "purge_session",
            "purge_all_sessions",
            "clear_history",
            "set_continuous_mode",
            "save_scenario",
            "delete_scenario",
        }
    )

    def stop(self) -> dict[str, Any]:
        """Мгновенно прерывает активное сообщение, стриминг и воспроизведение."""
        self._end_message()
        self._stop_event.set()
        try:
            from jarvis.modules.tts import cancel_playback

            cancel_playback()
        except Exception:
            pass
        if self.jarvis is not None:
            if hasattr(self.jarvis, "response") and self.jarvis.response is not None:
                try:
                    self.jarvis.response.cancel_speech()
                except Exception:
                    pass
                self._quiet_call(self.jarvis.response.stop)
            self._shutdown_reminders()
        self._shutdown_voice()
        self.jarvis = None
        self.started = False
        return {"ok": True, "started": False}

    def _shutdown_voice(self) -> None:
        self._voice_enabled = False
        self._voice_stop.set()
        if self.jarvis and getattr(self.jarvis, "audio", None):
            try:
                self.jarvis.audio.stop()
            except Exception:
                pass
        if self._voice_thread is not None:
            if self._voice_thread != threading.current_thread():
                self._voice_thread.join(timeout=2.0)
            self._voice_thread = None

    def _set_voice_mode(self, enabled: bool) -> dict[str, Any]:
        if not self.started:
            start_res = self._start()
            if not start_res.get("ok"):
                return start_res

        with self._voice_lock:
            if enabled == self._voice_enabled:
                return {"ok": True, "voice_enabled": self._voice_enabled}

            if enabled:
                try:
                    if self.jarvis and getattr(self.jarvis, "audio", None):
                        self.jarvis.audio.dry_run = False
                        self.jarvis.audio.start()
                except Exception as e:
                    logger.warning("Не удалось включить аудиопоток в GUI: %s", e)
                    return {"ok": False, "error": f"Ошибка запуска микрофона: {e}"}

                self._voice_stop.clear()
                self._voice_enabled = True
                self._voice_thread = threading.Thread(
                    target=self._voice_loop,
                    name="jarvis-ui-voice-loop",
                    daemon=True,
                )
                self._voice_thread.start()
                self._emit_voice_event("listening", "Слушаю микрофон...")
                return {"ok": True, "voice_enabled": True}
            else:
                self._shutdown_voice()
                self._emit_voice_event("stopped", "Голосовой режим отключен")
                return {"ok": True, "voice_enabled": False}

    def _emit_voice_event(self, status: str, payload_data: Any = "") -> None:
        try:
            if isinstance(payload_data, dict):
                event_obj = {"status": status, **payload_data}
            else:
                event_obj = {"status": status, "text": str(payload_data)}
            payload: dict[str, Any] = {
                "ok": True,
                "voice_event": event_obj,
            }
            with self._stdout_lock:
                self._proto_out.write(self._serialize(payload) + "\n")
                self._proto_out.flush()
        except Exception:
            pass

    def _voice_loop(self):
        phrase_limit = 10
        if self.jarvis and getattr(self.jarvis, "config", None):
            phrase_limit = self.jarvis.config.get("stt", {}).get(
                "phrase_time_limit", 10
            )

        def _on_partial(pt: str):
            if pt and pt.strip() and not self._voice_stop.is_set():
                self._emit_voice_event("partial", pt.strip())

        while self._voice_enabled and not self._voice_stop.is_set():
            try:
                if not self.jarvis or not getattr(self.jarvis, "audio", None):
                    break

                if self._message_busy or self._voice_stop.is_set():
                    time.sleep(0.3)
                    continue

                # Дожидаемся окончания текущей озвучки (если была)
                if hasattr(self.jarvis, "response") and hasattr(
                    self.jarvis.response, "wait_for_speech"
                ):
                    self.jarvis.response.wait_for_speech()

                text = self.jarvis.audio.recognize(phrase_limit, on_partial=_on_partial)
                if not text or not text.strip():
                    continue

                if self._message_busy or self._voice_stop.is_set():
                    time.sleep(0.3)
                    continue

                text = text.strip()
                # Проверка wake-word если не continuous
                is_continuous = bool(
                    getattr(self.jarvis, "continuous", False) or self._continuous_mode
                )
                conv = getattr(self.jarvis, "conversation", None)
                if not is_continuous:
                    if conv:
                        detected, query = conv.detect_wake(text)
                        if not detected:
                            self._emit_voice_event(
                                "wake_word_required",
                                {
                                    "text": text,
                                    "message": "Для активации назовите «Джарвис» или включите непрерывный режим",
                                },
                            )
                            continue
                        if not query or not query.strip():
                            # Пользователь назвал только «Джарвис» — подтверждаем и ждем запрос
                            self._emit_voice_event("listening", "Слушаю вас, сэр...")
                            if hasattr(self.jarvis, "response") and hasattr(
                                self.jarvis.response, "speak"
                            ):
                                self.jarvis.response.speak("Слушаю вас, сэр.")
                                self.jarvis.response.wait_for_speech()
                            continue
                        text = query.strip()
                else:
                    if conv:
                        detected, query = conv.detect_wake(text)
                        if detected and query and query.strip():
                            text = query.strip()

                self._emit_voice_event("recognized", text)

                if not self._try_begin_message():
                    continue

                jarvis = self.jarvis
                if not jarvis or not getattr(jarvis, "response", None):
                    self._end_message()
                    continue

                try:
                    self._emit_voice_event("processing", text)

                    # Voice-path parity: проверка спецкоманд
                    if hasattr(jarvis, "commands") and hasattr(
                        jarvis.commands, "executor"
                    ):
                        parsed = jarvis.commands.executor.parse_voice_command(
                            text.lower().strip()
                        )
                        if parsed == "__MUTE__":
                            if hasattr(jarvis, "conversation"):
                                jarvis.conversation.mute()
                            self._shutdown_voice()
                            self._emit_voice_event(
                                "stopped", "Голосовой режим отключен"
                            )
                            continue
                        elif parsed == "__CONTINUOUS_ON__":
                            jarvis.continuous = True
                            self._continuous_mode = True
                            self._emit_voice_event(
                                "status", "Постоянная прослушка включена"
                            )

                    resp = jarvis.response.process_query(
                        text,
                        stream_callback=self._emit_delta,
                        tool_callback=self._emit_tool,
                        tool_result_callback=self._emit_tool_result,
                    )

                    final_resp = resp or "Готово, сэр."
                    self._emit_voice_event(
                        "finished",
                        {
                            "query": text,
                            "response": final_resp,
                            "session": self._current_session,
                        },
                    )

                    if resp and hasattr(jarvis.response, "speak"):
                        self._emit_voice_event("speaking", resp)
                        jarvis.response.speak(resp)
                        if hasattr(jarvis.response, "wait_for_speech"):
                            jarvis.response.wait_for_speech()

                        # Пауза для затухания акустического эха в комнате
                        time.sleep(0.3)

                        # Сброс буферов VAD
                        if (
                            hasattr(jarvis, "audio")
                            and jarvis.audio
                            and hasattr(jarvis.audio, "stt")
                        ):
                            stt = jarvis.audio.stt
                            if hasattr(stt, "vad_iterator") and stt.vad_iterator:
                                stt.vad_iterator.reset()
                except Exception as exc:
                    logger.error("Ошибка обработки голосовой команды: %s", exc)
                finally:
                    self._end_message()
                    if self._voice_enabled and not self._voice_stop.is_set():
                        self._emit_voice_event("listening", "Слушаю микрофон...")

            except Exception as e:
                logger.error("Ошибка в voice_loop: %s", e)
                time.sleep(1.0)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request.get("command")
        if command in self._MUTATING_COMMANDS and self._message_busy:
            return {
                "ok": False,
                "error": "Идёт обработка сообщения — повторите после ответа",
            }
        if command == "start":
            return self._start()
        if command == "status":
            return {"ok": True, "started": self.started, **self._info()}
        if command == "stop":
            return self.stop()
        if command == "configure":
            config = request.get("config", {})
            error = self._validate_config(config)
            if error:
                return {"ok": False, "error": error}
            if self.jarvis is not None:
                self._quiet_call(self.jarvis.response.stop)
                self._shutdown_reminders()
            self.jarvis = None
            self.started = False
            self._pending_config = config
            return self._start()
        if command == "switch_session":
            return self._switch_session(str(request.get("session_id", "")))
        if command == "delete_session":
            return self._delete_session(str(request.get("session_id", "")))
        if command == "purge_session":
            return self._purge_session(str(request.get("session_id", "")))
        if command == "purge_all_sessions":
            return self._purge_all_sessions()
        if command == "message":
            if not self.started:
                start_res = self._start()
                if not start_res.get("ok"):
                    return {
                        "ok": False,
                        "error": start_res.get("error", "Не удалось запустить JARVIS"),
                    }
            if self._stop_event.is_set():
                return {"ok": False, "error": "Остановлено пользователем"}
            text = str(request.get("text", "")).strip()
            if not text:
                return {"ok": False, "error": "Пустое сообщение"}
            # Keep backend context aligned with the UI chat that is sending.
            session = str(request.get("session", "") or "")
            if session and session != self._current_session:
                switch_result = self._switch_session(session)
                if not switch_result.get("ok"):
                    return switch_result
            # Voice-path parity: handle special markers first (reminders,
            # mute/dictate/exit), exactly like Jarvis._process_special does
            # before the response pipeline swallows them.
            marker = None
            if self.jarvis is not None and self.jarvis.commands is not None:
                marker = self.jarvis.commands.executor.parse_voice_command(
                    text.lower().strip()
                )
            if marker:
                return {"ok": True, "text": self._resolve_marker(marker)}
            jarvis = self.jarvis
            response = (
                self._quiet_call(
                    lambda: jarvis.response.process_query(
                        text,
                        stream_callback=self._emit_delta,
                        tool_callback=self._emit_tool,
                        tool_result_callback=self._emit_tool_result,
                    )
                )
                if jarvis is not None
                else ""
            )
            if self._stop_event.is_set():
                return {"ok": False, "error": "Остановлено пользователем"}
            response = self._resolve_marker(response)
            # Только маскировка секретов: в текстовом чате показываем ПОЛНЫЙ
            # ответ. Обрезка/markdown-чистка (sanitize_for_tts) — в
            # ResponsePipeline.speak, т.е. только когда ответ идёт голосом.
            try:
                from jarvis.prompt_builder import redact_secrets

                response = redact_secrets(response)
            except Exception:
                pass  # sanitisation must never break the reply path
            return {"ok": True, "text": response}
        if command == "list_models":
            return self._list_models(request.get("config", {}))
        if command == "get_config":
            return self._get_config()
        if command == "set_config_value":
            return self._set_config_value(
                request.get("section", ""),
                request.get("key", ""),
                request.get("value"),
            )
        if command == "get_continuous_mode":
            enabled = bool(getattr(self.jarvis, "continuous", self._continuous_mode))
            return {"ok": True, "continuous": enabled}
        if command == "set_continuous_mode":
            enabled = bool(request.get("enabled", False))
            self._continuous_mode = enabled
            if self.jarvis is not None:
                self.jarvis.continuous = enabled
            if request.get("persist", False):
                self._set_config_value("stt", "continuous", enabled)
            return {"ok": True, "continuous": enabled}
        if command == "get_voice_mode":
            return {"ok": True, "voice_enabled": self._voice_enabled}
        if command == "set_voice_mode":
            enabled = bool(request.get("enabled", False))
            return self._set_voice_mode(enabled)
        if command == "get_scenarios":
            try:
                from jarvis.modules.scenarios import ScenarioManager

                mgr = ScenarioManager()
                return {"ok": True, "scenarios": mgr.list_scenarios()}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        if command == "save_scenario":
            try:
                from jarvis.modules.scenarios import ScenarioManager

                mgr = ScenarioManager()
                sc_id = request.get("id")
                data = request.get("data")
                if not sc_id or not isinstance(data, dict):
                    return {"ok": False, "error": "id и data обязательны"}
                ok = mgr.save_scenario(str(sc_id), data)
                return {"ok": ok}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        if command == "delete_scenario":
            try:
                from jarvis.modules.scenarios import ScenarioManager

                mgr = ScenarioManager()
                sc_id = request.get("id")
                if not sc_id:
                    return {"ok": False, "error": "id обязателен"}
                ok = mgr.delete_scenario(str(sc_id))
                return {"ok": ok}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        if command == "restart":
            if self.jarvis is not None:
                self._quiet_call(self.jarvis.response.stop)
                self._shutdown_reminders()
            self.jarvis = None
            self.started = False
            self._end_message()
            return self._start()
        if command == "timers":
            return self._timers()
        if command == "clear_history":
            return self._clear_history()
        if command == "export_diagnostics":
            return self._export_diagnostics()
        return {"ok": False, "error": f"Неизвестная команда: {command}"}

    @staticmethod
    def _is_local_endpoint(endpoint: str) -> bool:
        ep = endpoint.lower()
        return any(
            x in ep
            for x in (
                "localhost",
                "127.0.0.1",
                "0.0.0.0",
                "::1",
                "ollama",
                "lmstudio",
                "local",
            )
        )

    @staticmethod
    def _validate_config(config: dict[str, Any]) -> str | None:
        if config.get("type") not in {"openai", "anthropic"}:
            return "Неподдерживаемый тип API"
        endpoint = str(config.get("endpoint") or "").strip()
        if not endpoint:
            return "Endpoint и API ключ обязательны"
        api_key = str(config.get("api_key") or "").strip()
        if not Bridge._is_local_endpoint(endpoint) and not api_key:
            return "Endpoint и API ключ обязательны"
        return None

    def _info(self) -> dict[str, Any]:
        preset = self._pending_config or {}
        info: dict[str, Any] = {
            "provider": preset.get("type", ""),
            "model": preset.get("model", ""),
            "agent_enabled": bool(preset.get("agent_enabled", True)),
            "continuous": bool(getattr(self.jarvis, "continuous", False))
            if self.jarvis
            else False,
            "voice_enabled": self._voice_enabled,
        }
        if self.jarvis is not None and self.jarvis.response is not None:
            info["agent_enabled"] = bool(
                getattr(self.jarvis.response, "agent_enabled", info["agent_enabled"])
            )
        return info

    _ALLOWED_ROOT_SECTIONS = frozenset(
        {
            "audio",
            "stt",
            "vad",
            "tts",
            "llm",
            "commands",
            "logging",
            "web_search",
            "telegram",
            "misc",
        }
    )

    def _set_config_value(self, section: str, key: str, value: Any) -> dict[str, Any]:
        """Точечная запись в config.yaml с СОХРАНЕНИЕМ комментариев (ruamel.yaml round-trip).
        Поддерживает dot-notation и произвольные типы данных."""
        import os
        from pathlib import Path
        from ruamel.yaml import YAML

        if not section:
            return {"ok": False, "error": "Секция не указана"}

        parts = [
            p.strip()
            for p in (section + "." + key if key else section).split(".")
            if p.strip()
        ]
        if not parts:
            return {"ok": False, "error": "Секция не указана"}

        root_section = parts[0]
        if root_section not in self._ALLOWED_ROOT_SECTIONS:
            return {
                "ok": False,
                "error": f"Секция {root_section} не редактируется из GUI",
            }

        path = Path(os.environ.get("JARVIS_CONFIG_PATH", "config.yaml"))
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return {"ok": False, "error": f"Конфиг {path} не найден"}

        yaml = YAML()
        yaml.preserve_quotes = True
        try:
            raw_text = path.read_text(encoding="utf-8")
            data = yaml.load(raw_text)
            if not isinstance(data, dict):
                data = {}

            cur = data
            for part in parts[:-1]:
                if part not in cur or not isinstance(cur[part], dict):
                    cur[part] = {}
                cur = cur[part]

            leaf = parts[-1]
            old_value = cur.get(leaf)

            check_key = f"{key}.{leaf}".lower().replace("-", "_")
            if (
                any(s in check_key for s in ("api_key", "token", "secret", "password"))
                and isinstance(value, str)
                and "***" in value
                and old_value
            ):
                return {"ok": True, "note": "Значение оставлено без изменений"}

            cur[leaf] = value

            # Валидируем ДО записи: битый конфиг не пишем
            from jarvis.config_schema import validate_config

            validate_config(json.loads(json.dumps(data, ensure_ascii=False)))

            mode = path.stat().st_mode
            tmp_path = path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                yaml.dump(data, f)
                f.flush()
            tmp_path.chmod(mode)
            tmp_path.replace(path)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Не удалось применить: {exc}"}

        full_key = ".".join(parts)
        return {
            "ok": True,
            "note": f"Сохранено: {full_key} = {value} (было: {old_value}). "
            "Применится после перезапуска backend.",
        }

    def _get_config(self) -> dict[str, Any]:
        """Текущие значения полного дерева конфига для отображения в настройках GUI."""
        import os

        from jarvis.config_loader import ConfigLoader

        path = os.environ.get("JARVIS_CONFIG_PATH", "config.yaml")
        try:
            cfg = ConfigLoader(path).load()
        except SystemExit:
            return {"ok": False, "error": f"Конфиг {path} невалиден (см. stderr)"}
        except Exception as exc:  # noqa: BLE001 — протокол не должен рваться
            return {"ok": False, "error": str(exc)}

        def _mask_secrets(obj: Any) -> Any:
            if isinstance(obj, dict):
                res = {}
                for k, v in obj.items():
                    if (
                        any(
                            s in k.lower()
                            for s in ("api_key", "token", "secret", "password")
                        )
                        and isinstance(v, str)
                        and v
                    ):
                        res[k] = v[:4] + "***" if len(v) > 4 else "***"
                    else:
                        res[k] = _mask_secrets(v)
                return res
            elif isinstance(obj, list):
                return [_mask_secrets(item) for item in obj]
            return obj

        return {
            "ok": True,
            "config": _mask_secrets(cfg),
        }

    @staticmethod
    def _group_models(ids: list[str]) -> list[dict[str, Any]]:
        groups: dict[str, list[str]] = {}
        for model_id in ids:
            group = model_id.split("/", 1)[0] if "/" in model_id else "other"
            groups.setdefault(group, []).append(model_id)
        return [
            {"provider": group, "models": sorted(models)}
            for group, models in sorted(groups.items())
        ]

    def _list_models(self, config: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_config(config)
        if error:
            return {"ok": False, "error": error}
        api_type: str = config["type"]
        endpoint: str = config["endpoint"].rstrip("/")
        api_key: str = str(config.get("api_key") or "").strip()
        url = f"{endpoint}/models"
        headers: dict[str, str] = {}
        if api_type == "openai":
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        else:
            if api_key:
                headers["x-api-key"] = api_key
            headers["anthropic-version"] = ANTHROPIC_VERSION
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return {"ok": False, "error": f"Не удалось получить модели: {exc}"}
        raw = payload.get("data") if isinstance(payload, dict) else payload
        ids: list[str] = []
        for item in raw or []:
            model_id = item.get("id") if isinstance(item, dict) else item
            if isinstance(model_id, str):
                ids.append(model_id)
        if not ids:
            return {"ok": False, "error": "Список моделей пуст"}
        return {"ok": True, "groups": self._group_models(sorted(set(ids)))}

    @staticmethod
    def _timers() -> dict[str, Any]:
        from jarvis.modules.reminder import ReminderManager

        try:
            active = ReminderManager.list_active()
        except Exception as exc:
            return {"ok": False, "error": f"Таймеры недоступны: {exc}"}
        # list_active() returns (text, seconds_left) tuples.
        timers = [
            {"id": str(index), "text": text, "left": f"{seconds} с"}
            for index, (text, seconds) in enumerate(active)
        ]
        return {"ok": True, "timers": timers}

    def _clear_history(self) -> dict[str, Any]:
        from jarvis.modules import llm as llm_module

        save = getattr(llm_module, "_save_history", None)
        if save is None:
            return {"ok": False, "error": "Функция истории не найдена"}
        save([])
        # Live clients keep an in-memory copy; reset it too or the next
        # request would resurrect the "deleted" context from memory.
        self._set_clients_history([])
        return {"ok": True}

    def _export_diagnostics(self) -> dict[str, Any]:
        """Build a sanitized diagnostics zip (PR-OBS-1 backend, PR-UI-OBS-1 wiring).

        Read-only w.r.t. bridge state, so it stays available while a
        "message" generation is in flight (not in _MUTATING_COMMANDS).
        """
        try:
            from jarvis.modules.diagnostics import generate_diagnostics_bundle

            bundle = generate_diagnostics_bundle()
        except ImportError as exc:
            return {"ok": False, "error": f"Модуль диагностики недоступен: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"Не удалось сформировать отчёт: {exc}"}
        return {"ok": True, "path": str(bundle)}


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(errors="replace")
        except Exception:
            pass
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    bridge = Bridge()
    _worker_thread: threading.Thread | None = None
    for line in sys.stdin:
        if not line.strip():
            continue
        if len(line) > 10 * 1024 * 1024:
            bridge._write_response({"ok": False, "error": "payload too large"})
            continue
        try:
            request = json.loads(line)
        except Exception as exc:
            bridge._write_response({"ok": False, "error": f"bad request: {exc}"})
            continue

        if not isinstance(request, dict):
            bridge._write_response(
                {"ok": False, "error": "bad request: expected JSON object"}
            )
            continue

        rid = request.get("id")
        if request.get("command") == "message":
            # Длинный запрос — в отдельный поток: короткие команды
            # (timers/status/get_config) обслуживаются, пока генерация идёт.
            if not bridge._try_begin_message():
                bridge._write_response(
                    {
                        "ok": False,
                        "id": rid,
                        "error": "Уже обрабатывается сообщение",
                    }
                )
                continue

            def work(req: dict[str, Any] = request, rid: Any = rid) -> None:
                # BaseException, а не Exception: ConfigLoader зовёт sys.exit(1)
                # на кривом конфиге — SystemExit не должен молча убивать поток
                # (иначе _end_message не вызовется и busy-флаг зависнет).
                bridge._current_id = rid
                result: dict[str, Any] = {"ok": False, "error": "внутренняя ошибка"}
                stop_beat = threading.Event()

                def beat() -> None:
                    # Heartbeat: сбрасывает 180-секундный стрим-таймаут Rust'а,
                    # пока генерация жива (не-стримящая итерация молчит)
                    while not stop_beat.wait(20):
                        try:
                            bridge._emit_delta("")
                        except Exception:
                            break

                beat_thread = threading.Thread(target=beat, daemon=True)
                beat_thread.start()
                try:
                    result = bridge.handle(req)
                except BaseException as exc:  # noqa: BLE001
                    result = {"ok": False, "error": str(exc) or type(exc).__name__}
                finally:
                    stop_beat.set()
                    bridge._current_id = None
                    if not isinstance(result, dict):
                        result = {"ok": False, "error": "внутренняя ошибка"}
                    result["id"] = rid
                    bridge._write_response(result)
                    bridge._end_message()

            try:
                t = threading.Thread(
                    target=work, name="jarvis-bridge-message", daemon=True
                )
                t.start()
                _worker_thread = t
            except Exception as exc:  # noqa: BLE001
                bridge._write_response({"ok": False, "id": rid, "error": str(exc)})
                bridge._end_message()
            continue

        try:
            result = bridge.handle(request)
        except BaseException as exc:  # Keep protocol alive after one failed request.
            result = {"ok": False, "error": str(exc) or type(exc).__name__}
        if not isinstance(result, dict):
            result = {"ok": False, "error": "внутренняя ошибка"}
        if rid:
            result["id"] = rid
        bridge._write_response(result)

    # EOF: Rust закрыл stdin (stop/перезапуск). Дождёмся рабочего потока,
    # чтобы его finally-блоки успели убить дочерние процессы (bash_agent killpg).
    if _worker_thread is not None and _worker_thread.is_alive():
        _worker_thread.join(timeout=5)


if __name__ == "__main__":
    main()
