import json
import time
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import pytest

import jarvis as jarvis_pkg
import jarvis.modules.llm as llm_mod
import jarvis.modules.reminder as reminder_mod
from jarvis.ui_bridge import Bridge


@pytest.fixture(autouse=True)
def _hermetic_config(monkeypatch):
    """Bridge must never depend on a developer's personal config.yaml."""
    monkeypatch.setenv("JARVIS_CONFIG_PATH", "config.test.yaml")


def test_bridge_status_and_unknown_command():
    bridge = Bridge()
    result = bridge.handle({"command": "status"})
    assert result["ok"] is True
    assert result["started"] is False
    assert result["agent_enabled"] is True  # default until a preset says otherwise
    unknown = bridge.handle({"command": "unknown"})
    assert unknown["ok"] is False


def test_bridge_rejects_empty_message():
    bridge = Bridge()
    result = bridge.handle({"command": "message", "text": "  "})
    assert result["ok"] is False
    assert "Пустое" in result["error"]


def test_bridge_protocol_result_is_json():
    result = Bridge().handle({"command": "status"})
    assert json.dumps(result, ensure_ascii=False)


def test_bridge_validate_config():
    ok = {"type": "openai", "endpoint": "https://x/v1", "api_key": "k"}
    bad_type = dict(ok, type="grpc")
    no_key = {"type": "openai", "endpoint": "https://x/v1"}
    assert Bridge._validate_config(ok) is None
    assert Bridge._validate_config(bad_type) is not None
    assert Bridge._validate_config(no_key) is not None


def test_bridge_group_models_by_provider():
    groups = Bridge._group_models(
        ["deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash", "gpt-4o-mini"]
    )
    by_provider = {g["provider"]: g["models"] for g in groups}
    assert by_provider["deepseek"] == [
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro",
    ]
    assert by_provider["other"] == ["gpt-4o-mini"]


def test_bridge_list_models_requires_valid_config():
    result = Bridge().handle({"command": "list_models", "config": {}})
    assert result["ok"] is False


# ──────────────────────────────────────────────
# Изоляция персиста истории: llm.HISTORY_FILE (и ui-history/ рядом)
# переносится в tmp_path, чтобы тесты не трогали ~/.local/share/jarvis.
# ──────────────────────────────────────────────


@pytest.fixture
def isolated_history(tmp_path, monkeypatch):
    hist = tmp_path / "data" / "history.json"
    monkeypatch.setattr(llm_mod, "HISTORY_FILE", hist)
    return hist


def _write_archive(hist, sid, messages):
    d = hist.parent / "ui-history"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sid}.json"
    path.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    return path


VALID_PRESET = {"type": "openai", "endpoint": "https://x/v1", "api_key": "k"}


def _fake_jarvis_factory():
    def factory(**_kwargs):
        response = SimpleNamespace(
            start=lambda: None,
            stop=lambda: None,
            agent_enabled=True,
            agent_approval_mode="auto",
            tts=None,
            llm=None,
            commands=None,
            platform=None,
        )
        return SimpleNamespace(
            config={"llm": {}},
            response=response,
            tts=None,
            commands=None,
            platform=None,
            reminder_mgr=None,
        )

    return factory


def _attach_llm(bridge):
    client = SimpleNamespace(history=[], max_history=20)
    bridge.jarvis = SimpleNamespace(
        llm=SimpleNamespace(
            clients={"openai": client},
            primary=client,
            _cache=OrderedDict(),
        )
    )
    return client


# ──────────────────────────────────────────────
# 1. Restart не оставляет живых старых ReminderManager'ов
# ──────────────────────────────────────────────


def test_reconfigure_shuts_down_previous_reminder_manager(monkeypatch):
    created = []

    class FakeMgr:
        def __init__(self, on_trigger=None):
            self.on_trigger = on_trigger
            self.shutdowns = 0
            created.append(self)

        def shutdown(self):
            self.shutdowns += 1

    monkeypatch.setattr(jarvis_pkg, "Jarvis", _fake_jarvis_factory())
    monkeypatch.setattr(reminder_mod, "ReminderManager", FakeMgr)

    bridge = Bridge()
    assert bridge.handle({"command": "configure", "config": dict(VALID_PRESET)})["ok"]
    assert len(created) == 1
    assert bridge.handle({"command": "configure", "config": dict(VALID_PRESET)})["ok"]
    assert len(created) == 2
    # Старый менеджер погашен ровно один раз — его таймеры не задвоятся.
    assert created[0].shutdowns == 1
    assert created[1].shutdowns == 0
    assert bridge.jarvis.reminder_mgr is created[1]


def test_reconfigure_keeps_single_live_timer_per_reminder(monkeypatch, tmp_path):
    monkeypatch.setattr(reminder_mod, "REMINDERS_FILE", tmp_path / "reminders.json")
    reminder_mod._save_reminders(
        [
            {
                "text": "живое напоминание",
                "time": time.time() + 120,
                "created": time.time(),
            }
        ]
    )
    monkeypatch.setattr(jarvis_pkg, "Jarvis", _fake_jarvis_factory())

    bridge = Bridge()
    assert bridge.handle({"command": "configure", "config": dict(VALID_PRESET)})["ok"]
    first_mgr = bridge.jarvis.reminder_mgr
    assert len(first_mgr.timers) == 1

    assert bridge.handle({"command": "configure", "config": dict(VALID_PRESET)})["ok"]
    second_mgr = bridge.jarvis.reminder_mgr
    assert second_mgr is not first_mgr
    # После рестарта живёт ровно ОДИН Timer на напоминание: старые отменены.
    assert first_mgr.timers == []
    assert len(second_mgr.timers) == 1
    assert all(t.is_alive() for t in second_mgr.timers)
    # Напоминание пережило shutdown (сохранено для будущих запусков).
    texts = [t for t, _ in reminder_mod.ReminderManager.list_active()]
    assert texts == ["живое напоминание"]


def test_stop_shuts_down_reminder_manager():
    calls = []
    mgr = SimpleNamespace(shutdown=lambda: calls.append(1))
    bridge = Bridge()
    bridge.started = True
    bridge.jarvis = SimpleNamespace(
        response=SimpleNamespace(stop=lambda: None), reminder_mgr=mgr
    )
    assert bridge.handle({"command": "stop"})["ok"]
    assert calls == [1]
    assert bridge.jarvis is None
    assert bridge.started is False


# ──────────────────────────────────────────────
# 2. Смена чата сбрасывает LRU-кэш LLM
# ──────────────────────────────────────────────


def test_switch_session_clears_llm_cache(isolated_history):
    _write_archive(
        isolated_history,
        "aaaaaaaa",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}],
    )
    bridge = Bridge()
    client = _attach_llm(bridge)
    bridge.jarvis.llm._cache["0:продолжай"] = "чужой ответ"

    result = bridge.handle(
        {"command": "switch_session", "id": "r17", "session_id": "aaaaaaaa"}
    )
    assert result == {"ok": True, "session": "aaaaaaaa"}
    assert not bridge.jarvis.llm._cache
    assert client.history[-1]["content"] == "yo"
    assert json.loads(isolated_history.read_text(encoding="utf-8"))[-1] == {
        "role": "assistant",
        "content": "yo",
    }


def test_delete_active_session_clears_llm_cache(isolated_history):
    bridge = Bridge()
    client = _attach_llm(bridge)
    client.history = [{"role": "user", "content": "x"}]
    bridge.jarvis.llm._cache["0:q"] = "a"
    bridge._current_session = "aaaaaaaa"

    assert bridge.handle(
        {"command": "delete_session", "id": "r18", "session_id": "aaaaaaaa"}
    ) == {"ok": True}
    assert not bridge.jarvis.llm._cache
    assert client.history == []


# ──────────────────────────────────────────────
# 3. Первый switch архивирует legacy-историю CLI вместо затирания
# ──────────────────────────────────────────────


def test_first_switch_archives_legacy_history(isolated_history):
    legacy = [{"role": "user", "content": "legacy-cli talk"}]
    isolated_history.parent.mkdir(parents=True, exist_ok=True)
    isolated_history.write_text(json.dumps(legacy), encoding="utf-8")

    bridge = Bridge()
    assert bridge.handle(
        {"command": "switch_session", "id": "r17", "session_id": "aaaaaaaa"}
    )["ok"]

    archived = isolated_history.parent / "ui-history" / "_legacy-cli.json"
    assert archived.exists()
    assert json.loads(archived.read_text(encoding="utf-8")) == legacy
    # Живая история переключилась на новый (пустой) чат — но не раньше архива.
    assert json.loads(isolated_history.read_text(encoding="utf-8")) == []
    assert bridge._current_session == "aaaaaaaa"

    # Повторный switch архивирует уже под id сессии, legacy не перезаписывает.
    follow_up = [{"role": "user", "content": "aaa chat"}]
    isolated_history.write_text(json.dumps(follow_up), encoding="utf-8")
    assert bridge.handle(
        {"command": "switch_session", "id": "r26", "session_id": "bbbbbbbb"}
    )["ok"]
    assert (
        json.loads(
            (isolated_history.parent / "ui-history" / "aaaaaaaa.json").read_text(
                encoding="utf-8"
            )
        )
        == follow_up
    )
    assert json.loads(archived.read_text(encoding="utf-8")) == legacy


# ──────────────────────────────────────────────
# 4. purge_session: удаляет только свой архив; активный — чистит контекст
# ──────────────────────────────────────────────


def test_purge_session_deletes_only_own_archive(isolated_history):
    keep = _write_archive(
        isolated_history, "aaaaaaaa", [{"role": "user", "content": "a"}]
    )
    gone = _write_archive(
        isolated_history, "bbbbbbbb", [{"role": "user", "content": "b"}]
    )

    bridge = Bridge()
    assert bridge.handle(
        {"command": "purge_session", "id": "r27", "session_id": "bbbbbbbb"}
    ) == {"ok": True}
    assert not gone.exists()
    assert keep.exists()


def test_purge_session_on_active_wipes_context_and_cache(isolated_history):
    _write_archive(isolated_history, "aaaaaaaa", [{"role": "user", "content": "a"}])
    isolated_history.write_text(
        json.dumps([{"role": "user", "content": "live"}]), encoding="utf-8"
    )

    bridge = Bridge()
    client = _attach_llm(bridge)
    client.history = [{"role": "user", "content": "live"}]
    bridge.jarvis.llm._cache["0:x"] = "y"
    bridge._current_session = "aaaaaaaa"

    assert bridge.handle(
        {"command": "purge_session", "id": "r19", "session_id": "aaaaaaaa"}
    ) == {"ok": True}
    assert not (isolated_history.parent / "ui-history" / "aaaaaaaa.json").exists()
    assert json.loads(isolated_history.read_text(encoding="utf-8")) == []
    assert client.history == []
    assert not bridge.jarvis.llm._cache


def test_purge_session_rejects_invalid_id(isolated_history):
    bridge = Bridge()
    result = bridge.handle(
        {"command": "purge_session", "id": "r28", "session_id": "abc"}
    )
    assert result["ok"] is False
    assert "Некорректный" in result["error"]


# ──────────────────────────────────────────────
# 5. purge_all_sessions: чистит архивы + живой контекст + кэш
# ──────────────────────────────────────────────


def test_purge_all_sessions_wipes_everything(isolated_history):
    _write_archive(isolated_history, "aaaaaaaa", [{"role": "user", "content": "a"}])
    _write_archive(isolated_history, "bbbbbbbb", [{"role": "user", "content": "b"}])
    _write_archive(
        isolated_history, "_legacy-cli", [{"role": "user", "content": "old"}]
    )
    isolated_history.write_text(
        json.dumps([{"role": "user", "content": "live"}]), encoding="utf-8"
    )

    bridge = Bridge()
    client = _attach_llm(bridge)
    client.history = [{"role": "user", "content": "live"}]
    bridge.jarvis.llm._cache["0:x"] = "y"
    bridge._current_session = "aaaaaaaa"

    result = bridge.handle({"command": "purge_all_sessions"})
    assert result["ok"] is True
    assert result["removed"] == 3
    ui_dir = isolated_history.parent / "ui-history"
    assert list(ui_dir.glob("*.json")) == []
    assert json.loads(isolated_history.read_text(encoding="utf-8")) == []
    assert client.history == []
    assert not bridge.jarvis.llm._cache
    assert bridge._current_session is None


def test_purge_all_sessions_without_start(isolated_history):
    """Работает и до start: jarvis/llm отсутствуют, но диски чистятся."""
    _write_archive(isolated_history, "cccccccc", [{"role": "user", "content": "c"}])
    bridge = Bridge()
    result = bridge.handle({"command": "purge_all_sessions"})
    assert result == {"ok": True, "removed": 1}
    assert bridge._current_session is None


# ──────────────────────────────────────────────
# Полный текст в чате: sanitize_for_tts — только в голосовом пути
# ──────────────────────────────────────────────


def test_chat_message_full_text_not_truncated(monkeypatch):
    """Текстовый чат отдаёт ПОЛНЫЙ ответ LLM (без «Рассказать подробнее?»),
    но секреты маскируются. Решение владельца 2026-08-28: обрезка — только
    когда запрос шёл голосом (ResponsePipeline.speak)."""

    def factory(**_kwargs):
        def process_query(
            text, stream_callback=None, tool_callback=None, tool_result_callback=None
        ):
            if stream_callback:
                stream_callback("часть1 ")
            return "часть1 " + "часть2 " * 200 + " sk-abcdef1234567890abcdef12"

        response = SimpleNamespace(
            start=lambda: None,
            stop=lambda: None,
            agent_enabled=True,
            agent_approval_mode="auto",
            tts=None,
            llm=None,
            commands=None,
            platform=None,
            process_query=process_query,
        )
        return SimpleNamespace(
            config={"llm": {}},
            response=response,
            tts=None,
            commands=None,
            platform=None,
            reminder_mgr=None,
        )

    monkeypatch.setattr(jarvis_pkg, "Jarvis", factory)
    bridge = Bridge()
    assert bridge.handle({"command": "configure", "config": dict(VALID_PRESET)})["ok"]
    result = bridge.handle({"command": "message", "text": "расскажи подробно"})
    assert result["ok"]
    text = result["text"]
    assert text.count("часть2") == 200
    assert "Рассказать подробнее" not in text
    assert "[REDACTED]" in text


# ──────────────────────────────────────────────
# Мультиплексирование: message в отдельном потоке
# ──────────────────────────────────────────────


def test_mutating_command_rejected_while_message_busy():
    """configure/switch_session/clear_history при активном message
    отклоняются — иначе гонка с идущей генерацией."""
    bridge = Bridge()
    assert bridge._try_begin_message()
    for cmd in ("configure", "switch_session", "clear_history", "purge_all_sessions"):
        result = bridge.handle({"command": cmd, "id": "r20", "session_id": "aaaaaaaa"})
        assert result["ok"] is False
        assert "повторите после" in result["error"]
    bridge._end_message()
    # после завершения — снова доступны (switch_session ok: нет busy-ошибки)
    result = bridge.handle(
        {"command": "switch_session", "id": "r17", "session_id": "aaaaaaaa"}
    )
    assert result["ok"] is True
    assert "повторите после" not in (result.get("error") or "")


def test_status_and_timers_allowed_while_message_busy():
    """Read-only команды во время message работают (ради них и затевалось)."""
    bridge = Bridge()
    assert bridge._try_begin_message()
    status = bridge.handle({"command": "status"})
    assert status["ok"] is True
    timers = bridge.handle({"command": "timers"})
    assert timers["ok"] is True


def test_mux_id_does_not_collide_with_session_id():
    """P0-регрессия: Rust кладёт mux-id в поле "id" — сессия должна
    приходить в отдельном поле session_id, иначе switch/purge молча
    отваливались по 'Некорректный id сессии'."""
    result = Bridge().handle(
        {"command": "switch_session", "id": "r17", "session_id": "aaaaaaaa"}
    )
    assert result["ok"] is True
    assert result["session"] == "aaaaaaaa"


def test_set_config_value_roundtrip_preserves_comments(tmp_path, monkeypatch):
    """set_config_value пишет значение в config.yaml, СОХРАНЯЯ комментарии
    (ruamel round-trip), и не ломает forbid-схему."""

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        '# мой комментарий\nstt:\n  engine: "vosk"  # быстрый\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg))
    bridge = Bridge()
    result = bridge.handle(
        {
            "command": "set_config_value",
            "section": "stt",
            "key": "engine",
            "value": "whisper",
        }
    )
    assert result["ok"] is True
    text = cfg.read_text(encoding="utf-8")
    assert "whisper" in text
    assert "# мой комментарий" in text  # комментарии выжили
    assert "# быстрый" in text


def test_set_config_value_whitelist():
    """Произвольные корневые секции из GUI писать нельзя."""
    bridge = Bridge()
    result = bridge.handle(
        {
            "command": "set_config_value",
            "section": "unauthorized_section",
            "key": "field",
            "value": "evil",
        }
    )
    assert result["ok"] is False
    assert "не редактируется" in result["error"]


def test_set_config_value_rejects_schema_break(tmp_path, monkeypatch):
    """Значение, ломающее forbid-схему, не пишется в файл."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("stt:\n  engine: vosk\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg))
    bridge = Bridge()
    result = bridge.handle(
        {
            "command": "set_config_value",
            "section": "stt",
            "key": "engine",
            "value": 12345,
        }
    )
    assert result["ok"] is False
    assert cfg.read_text(encoding="utf-8") == "stt:\n  engine: vosk\n"


def test_set_config_value_dot_notation(tmp_path, monkeypatch):
    """Поддержка вложенных ключей dot-notation."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "stt:\n  whisper:\n    model_size: tiny\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg))
    bridge = Bridge()
    result = bridge.handle(
        {
            "command": "set_config_value",
            "section": "stt",
            "key": "whisper.model_size",
            "value": "base",
        }
    )
    assert result["ok"] is True
    assert "base" in cfg.read_text(encoding="utf-8")


def test_continuous_mode_commands():
    bridge = Bridge()
    # Initially false
    res = bridge.handle({"command": "get_continuous_mode"})
    assert res["ok"] is True
    assert res["continuous"] is False

    # Set true
    res = bridge.handle({"command": "set_continuous_mode", "enabled": True})
    assert res["ok"] is True
    assert res["continuous"] is True

    # Check again
    res = bridge.handle({"command": "get_continuous_mode"})
    assert res["continuous"] is True


def test_scenario_bridge_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    bridge = Bridge()

    # Get scenarios
    res = bridge.handle({"command": "get_scenarios"})
    assert res["ok"] is True

    # Save scenario
    res = bridge.handle(
        {
            "command": "save_scenario",
            "id": "macro_1",
            "data": {
                "name": "Macro 1",
                "actions": [{"type": "speak", "text": "Hello"}],
            },
        }
    )
    assert res["ok"] is True

    # Delete scenario
    res = bridge.handle({"command": "delete_scenario", "id": "macro_1"})
    assert res["ok"] is True


def test_bridge_streaming_and_tool_emits():
    import io

    bridge = Bridge()
    stream_out = io.StringIO()
    bridge._proto_out = stream_out
    bridge._current_id = "msg-123"

    # Emit delta
    bridge._emit_delta("привет ")
    # Emit tool
    bridge._emit_tool("bash", {"cmd": "ls"})
    # Emit tool result
    bridge._emit_tool_result("bash", {"cmd": "ls"}, "file1\nfile2")

    lines = [json.loads(line) for line in stream_out.getvalue().strip().split("\n")]
    assert len(lines) == 3

    assert lines[0] == {"ok": True, "stream": True, "delta": "привет ", "id": "msg-123"}
    assert lines[1] == {
        "ok": True,
        "tool": {"name": "bash", "args": {"cmd": "ls"}},
        "id": "msg-123",
    }
    assert lines[2] == {
        "ok": True,
        "tool_result": {
            "name": "bash",
            "args": {"cmd": "ls"},
            "output": "file1\nfile2",
        },
        "id": "msg-123",
    }


def test_bridge_local_endpoint_without_api_key():
    # Local endpoint should validate without api_key
    local_cfg = {
        "type": "openai",
        "endpoint": "http://localhost:11434/v1",
        "model": "qwen2.5:3b",
    }
    assert Bridge._validate_config(local_cfg) is None
    assert Bridge._is_local_endpoint("http://localhost:11434/v1") is True
    assert Bridge._is_local_endpoint("http://127.0.0.1:1234/v1") is True
    assert Bridge._is_local_endpoint("http://lmstudio.local/v1") is True
    assert Bridge._is_local_endpoint("https://api.openai.com/v1") is False


def test_bridge_get_config_masks_secrets(tmp_path, monkeypatch):
    import yaml

    cfg_data = {
        "llm": {
            "provider": "openai",
            "openai": {
                "api_key": "sk-1234567890abcdef",
                "model": "gpt-4o",
            },
        },
        "telegram": {
            "bot_token": "secret_bot_token_value",
        },
    }
    cfg_file = tmp_path / "mask_test_config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_file))

    bridge = Bridge()
    res = bridge.handle({"command": "get_config"})
    assert res["ok"] is True
    masked_llm_key = res["config"]["llm"]["openai"]["api_key"]
    assert masked_llm_key.startswith("sk-1")
    assert "***" in masked_llm_key
    assert "sk-1234567890abcdef" not in masked_llm_key

    masked_token = res["config"]["telegram"]["bot_token"]
    assert "***" in masked_token
    assert "secret_bot_token_value" not in masked_token


def test_set_config_value_preserves_masked_secrets(tmp_path, monkeypatch):
    """If key contains api_key/token/secret/password and new value has '***',
    existing non-empty secret must not be overwritten."""
    import yaml

    cfg_data = {
        "llm": {
            "provider": "openai",
            "provider_config": {
                "openai": {
                    "api_key": "sk-real-secret-12345",
                    "model": "gpt-4o",
                },
            },
        },
        "telegram": {
            "token": "real_telegram_token",
        },
    }
    cfg_file = tmp_path / "secret_test_config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_file))

    bridge = Bridge()
    res = bridge.handle(
        {
            "command": "set_config_value",
            "section": "llm.provider_config.openai",
            "key": "api_key",
            "value": "sk-r***",
        }
    )
    assert res["ok"] is True
    assert res.get("note") == "Значение оставлено без изменений"

    # Verify original secret was preserved on disk
    updated = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert (
        updated["llm"]["provider_config"]["openai"]["api_key"] == "sk-real-secret-12345"
    )

    # Also test for telegram token
    res_tg = bridge.handle(
        {
            "command": "set_config_value",
            "section": "telegram",
            "key": "token",
            "value": "***",
        }
    )
    assert res_tg["ok"] is True
    assert res_tg.get("note") == "Значение оставлено без изменений"
    updated_tg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert updated_tg["telegram"]["token"] == "real_telegram_token"


def test_restart_allowed_while_message_busy(monkeypatch):
    """'restart' must always be allowed even when _message_busy is True for emergency recovery."""
    bridge = Bridge()
    monkeypatch.setattr(bridge, "_start", lambda: {"ok": True, "started": True})
    assert bridge._try_begin_message() is True
    assert bridge._message_busy is True

    res = bridge.handle({"command": "restart"})
    assert res["ok"] is True
    assert res.get("started") is True
    assert bridge._message_busy is False


def _stub_diagnostics(monkeypatch, func):
    """Inject a fake jarvis.modules.diagnostics module (PR-OBS-1 backend)."""
    import sys
    import types

    stub = types.ModuleType("jarvis.modules.diagnostics")
    setattr(stub, "generate_diagnostics_bundle", func)
    monkeypatch.setitem(sys.modules, "jarvis.modules.diagnostics", stub)


class TestExportDiagnostics:
    def test_export_diagnostics_ok(self, monkeypatch, tmp_path):
        bundle = tmp_path / "jarvis-diagnostics-2026.zip"
        bundle.write_bytes(b"PK fake")
        _stub_diagnostics(monkeypatch, lambda: bundle)
        res = Bridge().handle({"command": "export_diagnostics"})
        assert res["ok"] is True
        assert res["path"] == str(bundle)

    def test_export_diagnostics_generator_error(self, monkeypatch):
        def _boom():
            raise RuntimeError("zip failed")

        _stub_diagnostics(monkeypatch, _boom)
        res = Bridge().handle({"command": "export_diagnostics"})
        assert res["ok"] is False
        assert "zip failed" in res["error"]

    def test_export_diagnostics_module_missing(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "jarvis.modules.diagnostics", None)
        res = Bridge().handle({"command": "export_diagnostics"})
        assert res["ok"] is False
        assert "error" in res

    def test_export_diagnostics_allowed_while_message_busy(self, monkeypatch, tmp_path):
        """Read-only report must not be blocked by an active generation."""
        bundle = tmp_path / "jarvis-diagnostics-2026.zip"
        bundle.write_bytes(b"PK fake")
        _stub_diagnostics(monkeypatch, lambda: bundle)
        bridge = Bridge()
        assert bridge._try_begin_message() is True
        res = bridge.handle({"command": "export_diagnostics"})
        assert res["ok"] is True
        assert res["path"] == str(bundle)


class TestVoiceAudioLevel:
    def test_voice_loop_passes_on_level_and_emits_event(self):
        bridge = Bridge()
        events: list[tuple[str, Any]] = []
        bridge._emit_voice_event = lambda status, payload_data="": events.append(
            (status, payload_data)
        )

        captured_kwargs: dict[str, Any] = {}

        class DummyAudio:
            def recognize(self, phrase_limit, on_partial=None, on_level=None):
                captured_kwargs["on_level"] = on_level
                if on_level:
                    on_level(0.65)
                bridge._voice_stop.set()
                return "привет"

        dummy_jarvis = SimpleNamespace(
            audio=DummyAudio(),
            config={"stt": {"phrase_time_limit": 5}},
            continuous=True,
            conversation=None,
            response=None,
        )
        bridge.jarvis = dummy_jarvis
        bridge._voice_enabled = True

        bridge._voice_loop()

        assert "on_level" in captured_kwargs
        assert captured_kwargs["on_level"] is not None
        level_events = [e for e in events if e[0] == "audio_level"]
        assert len(level_events) >= 1
        assert level_events[0][1]["level"] == 0.65

    def test_voice_loop_clamps_audio_level(self):
        bridge = Bridge()
        events: list[tuple[str, Any]] = []
        bridge._emit_voice_event = lambda status, payload_data="": events.append(
            (status, payload_data)
        )

        class DummyAudio:
            def recognize(self, phrase_limit, on_partial=None, on_level=None):
                if on_level:
                    on_level(-0.5)
                    time.sleep(0.06)
                    on_level(2.5)
                bridge._voice_stop.set()
                return None

        dummy_jarvis = SimpleNamespace(
            audio=DummyAudio(),
            config={},
            continuous=True,
            conversation=None,
            response=None,
        )
        bridge.jarvis = dummy_jarvis
        bridge._voice_enabled = True

        bridge._voice_loop()

        level_events = [e for e in events if e[0] == "audio_level"]
        assert len(level_events) == 2
        assert level_events[0][1]["level"] == 0.0
        assert level_events[1][1]["level"] == 1.0

    def test_voice_loop_handles_legacy_recognize_type_error(self):
        bridge = Bridge()

        class LegacyAudio:
            def recognize(self, phrase_limit, on_partial=None):
                bridge._voice_stop.set()
                return "тест"

        dummy_jarvis = SimpleNamespace(
            audio=LegacyAudio(),
            config={},
            continuous=True,
            conversation=None,
            response=None,
        )
        bridge.jarvis = dummy_jarvis
        bridge._voice_enabled = True

        # Should not raise TypeError
        bridge._voice_loop()
