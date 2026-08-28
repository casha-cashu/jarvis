import json
import time
from collections import OrderedDict
from types import SimpleNamespace

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
    monkeypatch.setattr(
        reminder_mod, "REMINDERS_FILE", tmp_path / "reminders.json"
    )
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

    result = bridge.handle({"command": "switch_session", "id": "aaaaaaaa"})
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

    assert bridge.handle({"command": "delete_session", "id": "aaaaaaaa"}) == {"ok": True}
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
    assert bridge.handle({"command": "switch_session", "id": "aaaaaaaa"})["ok"]

    archived = isolated_history.parent / "ui-history" / "_legacy-cli.json"
    assert archived.exists()
    assert json.loads(archived.read_text(encoding="utf-8")) == legacy
    # Живая история переключилась на новый (пустой) чат — но не раньше архива.
    assert json.loads(isolated_history.read_text(encoding="utf-8")) == []
    assert bridge._current_session == "aaaaaaaa"

    # Повторный switch архивирует уже под id сессии, legacy не перезаписывает.
    follow_up = [{"role": "user", "content": "aaa chat"}]
    isolated_history.write_text(json.dumps(follow_up), encoding="utf-8")
    assert bridge.handle({"command": "switch_session", "id": "bbbbbbbb"})["ok"]
    assert json.loads(
        (isolated_history.parent / "ui-history" / "aaaaaaaa.json").read_text(
            encoding="utf-8"
        )
    ) == follow_up
    assert json.loads(archived.read_text(encoding="utf-8")) == legacy


# ──────────────────────────────────────────────
# 4. purge_session: удаляет только свой архив; активный — чистит контекст
# ──────────────────────────────────────────────


def test_purge_session_deletes_only_own_archive(isolated_history):
    keep = _write_archive(isolated_history, "aaaaaaaa", [{"role": "user", "content": "a"}])
    gone = _write_archive(isolated_history, "bbbbbbbb", [{"role": "user", "content": "b"}])

    bridge = Bridge()
    assert bridge.handle({"command": "purge_session", "id": "bbbbbbbb"}) == {"ok": True}
    assert not gone.exists()
    assert keep.exists()


def test_purge_session_on_active_wipes_context_and_cache(isolated_history):
    _write_archive(isolated_history, "aaaaaaaa", [{"role": "user", "content": "a"}])
    isolated_history.write_text(json.dumps([{"role": "user", "content": "live"}]), encoding="utf-8")

    bridge = Bridge()
    client = _attach_llm(bridge)
    client.history = [{"role": "user", "content": "live"}]
    bridge.jarvis.llm._cache["0:x"] = "y"
    bridge._current_session = "aaaaaaaa"

    assert bridge.handle({"command": "purge_session", "id": "aaaaaaaa"}) == {"ok": True}
    assert not (
        isolated_history.parent / "ui-history" / "aaaaaaaa.json"
    ).exists()
    assert json.loads(isolated_history.read_text(encoding="utf-8")) == []
    assert client.history == []
    assert not bridge.jarvis.llm._cache


def test_purge_session_rejects_invalid_id(isolated_history):
    bridge = Bridge()
    result = bridge.handle({"command": "purge_session", "id": "abc"})
    assert result["ok"] is False
    assert "Некорректный" in result["error"]


# ──────────────────────────────────────────────
# 5. purge_all_sessions: чистит архивы + живой контекст + кэш
# ──────────────────────────────────────────────


def test_purge_all_sessions_wipes_everything(isolated_history):
    _write_archive(isolated_history, "aaaaaaaa", [{"role": "user", "content": "a"}])
    _write_archive(isolated_history, "bbbbbbbb", [{"role": "user", "content": "b"}])
    _write_archive(isolated_history, "_legacy-cli", [{"role": "user", "content": "old"}])
    isolated_history.write_text(json.dumps([{"role": "user", "content": "live"}]), encoding="utf-8")

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
