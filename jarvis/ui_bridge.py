"""Line-delimited JSON bridge between the Tauri UI and JARVIS.

The bridge keeps stdout machine-readable: diagnostics belong on stderr.
Commands: start, stop, status, configure, message, list_models, timers,
clear_history, switch_session, delete_session, purge_session,
purge_all_sessions.
"""

from __future__ import annotations

import contextlib
import json
import sys
from typing import TYPE_CHECKING, Any, Callable, TypeVar

import requests

if TYPE_CHECKING:
    from jarvis import Jarvis
    from jarvis.modules.reminder import ReminderManager

T = TypeVar("T")

ANTHROPIC_VERSION = "2023-06-01"


class Bridge:
    def __init__(self) -> None:
        self.jarvis: Jarvis | None = None
        self.started = False
        self._pending_config: dict[str, Any] | None = None
        self._current_session: str | None = None
        # Real protocol stdout, captured before any contextlib redirect.
        self._proto_out = sys.stdout

    def _emit_delta(self, delta: str) -> None:
        """Streams one chunk as a JSONL line; Rust forwards it to the UI."""
        try:
            self._proto_out.write(
                json.dumps(
                    {"ok": True, "stream": True, "delta": delta}, ensure_ascii=False
                )
                + "\n"
            )
            self._proto_out.flush()
        except Exception:
            pass  # UI stream loss must never kill generation

    def _emit_tool(self, name: str, args: dict) -> None:
        """Notifies the UI that a tool is about to execute."""
        try:
            self._proto_out.write(
                json.dumps(
                    {"ok": True, "tool": {"name": name, "args": args}},
                    ensure_ascii=False,
                )
                + "\n"
            )
            self._proto_out.flush()
        except Exception:
            pass

    def _emit_tool_result(self, name: str, args: dict, result: str) -> None:
        """Notifies the UI of a finished tool execution (output truncated)."""
        try:
            self._proto_out.write(
                json.dumps(
                    {
                        "ok": True,
                        "tool_result": {
                            "name": name,
                            "args": args,
                            "output": str(result)[:2000],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
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
        provider_config["api_key"] = preset["api_key"]
        provider_config["model"] = preset.get("model") or provider_config.get("model")
        provider_config["base_url"] = preset["endpoint"]
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
        if self.started:
            return {"ok": True, "started": True}

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
            on_trigger=lambda text: print(f"⏰ НАПОМИНАНИЕ: {text}", file=sys.stderr)
        )
        self.jarvis.reminder_mgr = reminder_mgr
        self.started = True
        return {"ok": True, "started": True}

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

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request.get("command")
        if command == "start":
            return self._start()
        if command == "status":
            return {"ok": True, "started": self.started, **self._info()}
        if command == "stop":
            if self.jarvis is not None:
                self._quiet_call(self.jarvis.response.stop)
                self._shutdown_reminders()
            self.jarvis = None
            self.started = False
            return {"ok": True, "started": False}
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
            return self._switch_session(str(request.get("id", "")))
        if command == "delete_session":
            return self._delete_session(str(request.get("id", "")))
        if command == "purge_session":
            return self._purge_session(str(request.get("id", "")))
        if command == "purge_all_sessions":
            return self._purge_all_sessions()
        if command == "message":
            if not self.started:
                self._start()
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
        if command == "timers":
            return self._timers()
        if command == "clear_history":
            return self._clear_history()
        return {"ok": False, "error": f"Неизвестная команда: {command}"}

    @staticmethod
    def _validate_config(config: dict[str, Any]) -> str | None:
        if config.get("type") not in {"openai", "anthropic"}:
            return "Неподдерживаемый тип API"
        if not config.get("endpoint") or not config.get("api_key"):
            return "Endpoint и API ключ обязательны"
        return None

    def _info(self) -> dict[str, Any]:
        preset = self._pending_config or {}
        info: dict[str, Any] = {
            "provider": preset.get("type", ""),
            "model": preset.get("model", ""),
            "agent_enabled": bool(preset.get("agent_enabled", True)),
        }
        if self.jarvis is not None and self.jarvis.response is not None:
            info["agent_enabled"] = bool(
                getattr(self.jarvis.response, "agent_enabled", info["agent_enabled"])
            )
        return info

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
        api_key: str = config["api_key"]
        url = f"{endpoint}/models"
        headers: dict[str, str] = {}
        if api_type == "openai":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
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


def main() -> None:
    bridge = Bridge()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = bridge.handle(request)
        except Exception as exc:  # Keep protocol alive after one failed request.
            result = {"ok": False, "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
