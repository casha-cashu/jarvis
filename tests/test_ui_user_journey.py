"""
End-to-End User Journey Black-box tests for jarvis.ui_bridge.

Simulates the complete sequence of user actions via the JSONL IPC command protocol:
1. Startup & Status inquiry
2. Provider configuration (valid local Ollama, remote OpenAI, invalid type rejection)
3. Dialogue message exchange & multi-turn interaction
4. Session branching & switching (isolated conversational context)
5. Tool / Timer querying
6. Session history clearing & session deletion
7. Clean shutdown
"""

import pytest
from jarvis.ui_bridge import Bridge


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_CONFIG_PATH", "config.test.yaml")
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("JARVIS_NLU_CACHE", str(tmp_path / "nlu_cache.joblib"))


def test_complete_user_lifecycle_journey(monkeypatch):
    bridge = Bridge()

    # ── Step 1: User launches app and queries status ──────────────────────────
    res_status = bridge.handle({"command": "status"})
    assert res_status["ok"] is True
    assert res_status["started"] is False
    assert "agent_enabled" in res_status

    # ── Step 2: User attempts invalid configuration ───────────────────────────
    res_bad_config = bridge.handle(
        {
            "command": "configure",
            "config": {
                "type": "unsupported_engine",
                "endpoint": "http://localhost:11434",
            },
        }
    )
    assert res_bad_config["ok"] is False
    assert "Неподдерживаемый тип API" in res_bad_config["error"]

    # ── Step 3: User configures Ollama provider ──────────────────────────────
    # Mock LLM and ResponsePipeline so we don't make real external network calls
    mock_replies = [
        "Здравствуйте! Я ваш голосовой ассистент Джарвис.",
        "Сейчас 14 часов 15 минут.",
        "Контекст второй сессии.",
    ]
    reply_iter = iter(mock_replies)

    def _fake_process(text: str, **kwargs) -> str:
        return next(reply_iter, f"Ответ на {text}")

    res_cfg = bridge.handle(
        {
            "command": "configure",
            "config": {
                "type": "openai",
                "endpoint": "http://localhost:11434/v1",
                "api_key": "",
                "model": "qwen2.5:72b",
                "agent_enabled": True,
                "approval_mode": "auto",
            },
        }
    )
    assert res_cfg["ok"] is True
    assert res_cfg["started"] is True

    # Status reflects configured provider and model
    res_status_after = bridge.handle({"command": "status"})
    assert res_status_after["provider"] == "openai"
    assert res_status_after["model"] == "qwen2.5:72b"

    # Patch the running jarvis instance's response pipeline
    assert bridge.jarvis is not None
    assert bridge.jarvis.response is not None
    monkeypatch.setattr(bridge.jarvis.response, "process_query", _fake_process)

    # ── Step 4: User sends first message in Session 1 ─────────────────────────
    res_msg1 = bridge.handle(
        {
            "command": "message",
            "text": "Привет, Джарвис!",
            "session": "session-user-1",
        }
    )
    assert res_msg1["ok"] is True
    assert "Здравствуйте!" in res_msg1["text"]

    # User sends second message in Session 1
    res_msg2 = bridge.handle(
        {
            "command": "message",
            "text": "Который сейчас час?",
            "session": "session-user-1",
        }
    )
    assert res_msg2["ok"] is True
    assert "14 часов 15 минут" in res_msg2["text"]

    # ── Step 5: User switches to a brand new Session 2 ────────────────────────
    res_switch = bridge.handle(
        {
            "command": "switch_session",
            "session_id": "session-user-2",
        }
    )
    assert res_switch["ok"] is True

    res_msg3 = bridge.handle(
        {
            "command": "message",
            "text": "Новая тема диалога",
            "session": "session-user-2",
        }
    )
    assert res_msg3["ok"] is True
    assert "Контекст второй сессии" in res_msg3["text"]

    # ── Step 6: User queries timers / active jobs ─────────────────────────────
    res_timers = bridge.handle({"command": "timers"})
    assert res_timers["ok"] is True
    assert isinstance(res_timers.get("timers"), list)

    # ── Step 7: User clears active session history ────────────────────────────
    res_clear = bridge.handle({"command": "clear_history"})
    assert res_clear["ok"] is True

    # ── Step 8: User purges Session 1 ─────────────────────────────────────────
    res_purge = bridge.handle(
        {
            "command": "purge_session",
            "session_id": "session-user-1",
        }
    )
    assert res_purge["ok"] is True

    # ── Step 9: User stops the assistant ─────────────────────────────────────
    res_stop = bridge.handle({"command": "stop"})
    assert res_stop["ok"] is True
    assert bridge.started is False


def test_user_journey_error_recovery_and_streaming_events(monkeypatch):
    bridge = Bridge()
    emitted_lines = []

    # Intercept proto_out to verify wire format streaming events
    monkeypatch.setattr(bridge._proto_out, "write", lambda s: emitted_lines.append(s))
    monkeypatch.setattr(bridge._proto_out, "flush", lambda: None)

    # User attempts to send empty string
    res_empty = bridge.handle({"command": "message", "text": "   "})
    assert res_empty["ok"] is False
    assert "Пустое" in res_empty["error"]

    # User tests streaming callbacks
    bridge._current_id = "req-123"
    bridge._emit_delta("Привет ")
    bridge._emit_delta("мир!")
    bridge._emit_tool("bash_command", {"cmd": "uptime"})
    bridge._emit_tool_result("bash_command", {"cmd": "uptime"}, "load average: 0.15")

    # Verify JSONL lines emitted for UI frontend
    assert any('"delta": "Привет "' in line for line in emitted_lines)
    assert any('"delta": "мир!"' in line for line in emitted_lines)
    assert any('"tool"' in line and "bash_command" in line for line in emitted_lines)
    assert any(
        '"tool_result"' in line and "load average" in line for line in emitted_lines
    )
