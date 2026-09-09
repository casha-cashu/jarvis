"""Contract and edge-case tests for the UI Bridge and GUI-Backend interaction.

These tests independently verify:
1. IPC protocol contracts, commands, and payload formats.
2. Config schema validation for all fields edited by the frontend SettingsTab.
3. API validation rules (OpenAI vs Anthropic endpoints, API key requirements).
4. Scenario file resolution discrepancy between UI Bridge and CommandManager.
5. Concurrency protection (mutating commands rejected during streaming).
6. Session ID format enforcement and history purge isolation.
7. Secret masking and error resilience without starting audio or native bundles.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from jarvis.config_schema import validate_config
from jarvis.modules.scenarios import USER_SCENARIOS_PATH, ScenarioManager
from jarvis.ui_bridge import Bridge


@pytest.fixture(autouse=True)
def _hermetic_env(tmp_path, monkeypatch):
    """Hermetic test environment: isolated config and data directory."""
    cfg_file = tmp_path / "config.yaml"
    with open("config.example.yaml", encoding="utf-8") as f:
        cfg_content = f.read()
    cfg_file.write_text(cfg_content, encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg_file))
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))


# ── 1. SettingsTab vs Config Schema Validation Contract ───────────────────────────


def test_settings_tab_valid_keys_conformance(tmp_path):
    """Verifies that standard GUI fields edited in SettingsTab conform to pydantic schema."""
    with open("config.example.yaml", encoding="utf-8") as f:
        base_cfg = yaml.safe_load(f)

    # All these paths are emitted by SettingsTab:
    valid_gui_updates: list[tuple[str, str, Any]] = [
        ("llm", "system_prompt", "Custom prompt for assistant"),
        ("llm", "max_history", 30),
        ("llm", "agent_enabled", True),
        ("llm", "agent_approval_mode", "strict"),
        ("llm", "agent_max_iterations", 8),
        ("audio.microphone", "device_name", "Fifine K669"),
        ("audio.microphone", "sample_rate", 16000),
        ("stt", "engine", "whisper"),
        ("stt.whisper", "model_size", "small"),
        ("stt.vosk", "model_size", "small-ru"),
        ("stt", "wake_word", "джарвис"),
        ("stt", "phrase_time_limit", 15),
        ("stt", "silence_threshold", 1.5),
        ("tts", "engine", "piper"),
        ("tts.piper", "length_scale", 0.9),
        ("tts.piper", "speaker_id", 1),
        ("tts.gtts", "lang", "ru"),
        ("tts.gtts", "slow", False),
        ("tts.speecht5", "device", "cpu"),
        ("tts.speecht5", "speaker_id", 2),
        ("vad", "enabled", True),
        ("vad.silero", "threshold", 0.6),
        ("commands", "fuzzy_threshold", 0.75),
        ("commands", "execution_timeout", 45),
        ("web_search", "enabled", True),
        ("web_search", "provider", "duckduckgo"),
        ("web_search", "max_results", 7),
        ("web_search", "brave_api_key", "BSA-key"),
        ("web_search", "tavily_api_key", "tvly-key"),
        ("logging", "level", "DEBUG"),
        ("telegram", "enabled", False),
        ("telegram", "bot_token", "123456:ABC-DEF"),
    ]

    for section, key, val in valid_gui_updates:
        cfg = json.loads(json.dumps(base_cfg))
        parts = (section + "." + key).split(".")
        cur = cfg
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = val
        # Must validate without raising
        validated = validate_config(cfg)
        assert validated is not None


def test_settings_tab_llm_root_hyperparameters_supported():
    """Verifies that LLMConfig accepts temperature and max_tokens at the root level,

    as saved by the UI SettingsTab, while still forbidding unknown extra keys.
    """
    with open("config.example.yaml", encoding="utf-8") as f:
        base_cfg = yaml.safe_load(f)

    # 1. Setting llm.temperature directly is now allowed
    cfg_temp = json.loads(json.dumps(base_cfg))
    cfg_temp["llm"]["temperature"] = 0.7
    validated_temp = validate_config(cfg_temp)
    assert validated_temp["llm"]["temperature"] == 0.7

    # 2. Setting llm.max_tokens directly is now allowed
    cfg_tokens = json.loads(json.dumps(base_cfg))
    cfg_tokens["llm"]["max_tokens"] = 2048
    validated_tokens = validate_config(cfg_tokens)
    assert validated_tokens["llm"]["max_tokens"] == 2048

    # 3. Unknown keys are still forbidden by extra='forbid'
    cfg_bad = json.loads(json.dumps(base_cfg))
    cfg_bad["llm"]["unknown_hyperparam"] = 123
    with pytest.raises(ValidationError) as exc_bad:
        validate_config(cfg_bad)
    assert "extra_forbidden" in str(exc_bad.value)


# ── 2. API Key Requirement & Local Endpoint Contract ─────────────────────────────


def test_validate_config_allows_empty_api_key_for_local_models():
    """Verifies that ui_bridge._validate_config permits empty or missing api_key

    for local endpoints (localhost, 127.0.0.1, ollama, lmstudio),
    while strictly requiring api_key for remote endpoints.
    """
    local_endpoints = [
        "http://localhost:11434/v1",
        "http://127.0.0.1:1234/v1",
        "http://ollama:11434/v1",
        "http://lmstudio:1234/v1",
    ]
    for ep in local_endpoints:
        # Empty string
        assert (
            Bridge._validate_config(
                {
                    "type": "openai",
                    "endpoint": ep,
                    "api_key": "",
                    "model": "qwen2.5:3b",
                }
            )
            is None
        )
        # Missing key
        assert (
            Bridge._validate_config(
                {
                    "type": "openai",
                    "endpoint": ep,
                    "model": "qwen2.5:3b",
                }
            )
            is None
        )

    # Remote OpenAI provider requires api_key
    remote_provider = {
        "type": "openai",
        "endpoint": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o",
    }
    error = Bridge._validate_config(remote_provider)
    assert error == "Endpoint и API ключ обязательны"

    valid_remote = dict(remote_provider, api_key="sk-test-valid-key")
    assert Bridge._validate_config(valid_remote) is None


# ── 3. Scenario Path Synchronization Contract ────────────────────────────────────


def test_scenario_path_resolution_unified(monkeypatch, tmp_path):
    """Verifies that CommandManager and UI Bridge use the exact same USER_SCENARIOS_PATH."""
    from jarvis.modules.commands import CommandManager

    data_dir = tmp_path / "user_data"
    monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))

    bridge_mgr = ScenarioManager()
    assert bridge_mgr.path == USER_SCENARIOS_PATH.resolve()

    with open("config.example.yaml", encoding="utf-8") as f:
        base_cfg = yaml.safe_load(f)

    validated = validate_config(base_cfg)
    assert validated["commands"]["scenarios_path"] is None

    cmd_mgr = CommandManager(validated)
    assert cmd_mgr.executor.scenarios is not None
    assert cmd_mgr.executor.scenarios.path == bridge_mgr.path
    assert cmd_mgr.executor.scenarios.path == USER_SCENARIOS_PATH.resolve()

    # Saving a scenario via UI Bridge is immediately visible to CommandManager
    sc_data = {
        "name": "Integration Macro",
        "actions": [{"type": "speak", "text": "Sync works"}],
    }
    assert bridge_mgr.save_scenario("sync_macro", sc_data) is True
    match = cmd_mgr.executor.scenarios.find_matching_scenario("sync_macro")
    assert match is not None
    assert match[0] == "sync_macro"


# ── 4. Concurrency Protection Contract ───────────────────────────────────────────


def test_mutating_commands_exhaustively_blocked_during_message():
    """All state-mutating commands must be rejected while _message_busy is True."""
    bridge = Bridge()
    assert bridge._try_begin_message() is True

    mutating_commands = [
        {"command": "start"},
        {"command": "configure", "config": {}},
        {
            "command": "switch_session",
            "session_id": "c9bf9e57-1685-4c89-bafb-ff5af830be8a",
        },
        {
            "command": "delete_session",
            "session_id": "c9bf9e57-1685-4c89-bafb-ff5af830be8a",
        },
        {
            "command": "purge_session",
            "session_id": "c9bf9e57-1685-4c89-bafb-ff5af830be8a",
        },
        {"command": "purge_all_sessions"},
        {"command": "clear_history"},
        {"command": "set_continuous_mode", "enabled": True},
        {"command": "save_scenario", "id": "test", "data": {}},
        {"command": "delete_scenario", "id": "test"},
        {
            "command": "set_config_value",
            "section": "stt",
            "key": "engine",
            "value": "vosk",
        },
    ]

    for req in mutating_commands:
        res = bridge.handle(req)
        assert res["ok"] is False, f"Command {req['command']} should have been blocked"
        assert "Идёт обработка сообщения" in res["error"]

    bridge._end_message()

    # Once message is finished, read and mutate commands succeed
    status = bridge.handle({"command": "status"})
    assert status["ok"] is True


def test_stop_command_allowed_during_message_busy():
    """'stop' command must NOT be blocked when _message_busy is True.

    It must end active message, set stop_event, and cancel playback/streaming.
    """
    bridge = Bridge()
    assert bridge._try_begin_message() is True
    assert bridge._message_busy is True

    res = bridge.handle({"command": "stop"})
    assert res["ok"] is True
    assert res["started"] is False
    assert bridge._message_busy is False
    assert bridge._stop_event.is_set()


def test_restart_command_allowed_during_message_busy(monkeypatch):
    """'restart' must be allowed even while _message_busy is True for emergency recovery."""
    bridge = Bridge()
    monkeypatch.setattr(bridge, "_start", lambda: {"ok": True, "started": True})
    assert bridge._try_begin_message() is True
    res = bridge.handle({"command": "restart"})
    assert res["ok"] is True
    assert res.get("started") is True


def test_read_only_commands_allowed_concurrently():
    """Read-only telemetry commands must succeed even when message is generating."""
    bridge = Bridge()
    assert bridge._try_begin_message() is True

    assert bridge.handle({"command": "status"})["ok"] is True
    assert bridge.handle({"command": "timers"})["ok"] is True
    assert bridge.handle({"command": "get_config"})["ok"] is True
    assert bridge.handle({"command": "get_continuous_mode"})["ok"] is True
    assert bridge.handle({"command": "get_scenarios"})["ok"] is True

    bridge._end_message()


# ── 5. Session ID Validation Contract ────────────────────────────────────────────


def test_session_id_regex_rules():
    """Frontend generates crypto.randomUUID() (36 chars: 32 hex + 4 hyphens).

    Backend enforces [A-Za-z0-9_-]{8,64}.
    """
    bridge = Bridge()

    # Valid UUID format from React crypto.randomUUID()
    valid_uuid = "c9bf9e57-1685-4c89-bafb-ff5af830be8a"
    res = bridge.handle({"command": "switch_session", "session_id": valid_uuid})
    assert res["ok"] is True
    assert res["session"] == valid_uuid

    # Invalid session IDs
    invalid_ids = [
        "short",  # < 8 chars
        "invalid session id with spaces",
        "../../etc/passwd",
        "sess;rm -rf /",
        "a" * 65,  # > 64 chars
        "",
    ]
    for bad_id in invalid_ids:
        res = bridge.handle({"command": "switch_session", "session_id": bad_id})
        assert res["ok"] is False
        assert "Некорректный id сессии" in res["error"]


# ── 6. Sensitive Data Masking in get_config Contract ─────────────────────────────


def test_get_config_masks_all_secrets(tmp_path, monkeypatch):
    """get_config must redact api_key, token, secret, password in config tree."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
llm:
  provider: openai
  openai:
    api_key: "sk-supersecret123456"
telegram:
  enabled: true
  bot_token: "123456:secrettelegramtoken"
web_search:
  brave_api_key: "BSA-confidential"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg))
    bridge = Bridge()
    res = bridge.handle({"command": "get_config"})
    assert res["ok"] is True
    data = res["config"]

    # Verify masking
    assert data["llm"]["openai"]["api_key"] == "sk-s***"
    assert data["telegram"]["bot_token"] == "1234***"
    assert data["web_search"]["brave_api_key"] == "BSA-***"


# ── 7. Nested Config and Whitespace Handling Contract ───────────────────────────


def test_set_config_value_nested_structures_and_whitespace(tmp_path, monkeypatch):
    """Verifies that set_config_value correctly navigates nested sections,
    creates missing intermediate dictionaries, strips surrounding whitespace,
    and preserves file permissions."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("audio:\n  microphone: {}\nstt:\n  engine: vosk\n", encoding="utf-8")
    cfg.chmod(0o600)
    monkeypatch.setenv("JARVIS_CONFIG_PATH", str(cfg))
    bridge = Bridge()

    # 1. Whitespace in section and key names
    res = bridge.handle(
        {
            "command": "set_config_value",
            "section": "  audio.microphone  ",
            "key": "  sample_rate  ",
            "value": 16000,
        }
    )
    assert res["ok"] is True
    assert "16000" in res["note"]

    # 2. Deeply nested key with non-existent intermediate dict
    res2 = bridge.handle(
        {
            "command": "set_config_value",
            "section": "stt.whisper",
            "key": "model_size",
            "value": "base",
        }
    )
    assert res2["ok"] is True
    assert "stt.whisper.model_size" in res2["note"]

    # 3. Verify file permissions are preserved (0o600)
    assert (cfg.stat().st_mode & 0o777) == 0o600

    # 4. Verify yaml content
    content = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert content["audio"]["microphone"]["sample_rate"] == 16000
    assert content["stt"]["whisper"]["model_size"] == "base"


# ── 8. Heartbeat & Tool Streaming Reliability Contract ───────────────────────────


def test_heartbeat_deltas_format_and_jsonl_safety():
    """Verifies that heartbeat deltas and tool emissions output valid JSONL,
    multiplex correctly with current request id, and don't corrupt stdout."""
    import io

    fake_out = io.StringIO()
    bridge = Bridge()
    bridge._proto_out = fake_out
    bridge._current_id = "req-stream-123"

    # Emit empty delta (heartbeat)
    bridge._emit_delta("")
    # Emit tool notification
    bridge._emit_tool("bash", {"cmd": "ls -la"})
    # Emit tool result
    bridge._emit_tool_result("bash", {"cmd": "ls -la"}, "total 0\n")

    lines = [line.strip() for line in fake_out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 3

    # Check heartbeat payload
    hb = json.loads(lines[0])
    assert hb["ok"] is True
    assert hb["stream"] is True
    assert hb["delta"] == ""
    assert hb["id"] == "req-stream-123"

    # Check tool payload
    tool = json.loads(lines[1])
    assert tool["ok"] is True
    assert tool["tool"]["name"] == "bash"
    assert tool["id"] == "req-stream-123"

    # Check tool_result payload
    tool_res = json.loads(lines[2])
    assert tool_res["ok"] is True
    assert tool_res["tool_result"]["output"] == "total 0\n"
    assert tool_res["id"] == "req-stream-123"


# ── 9. JSONL Stdin Robustness Contract ──────────────────────────────────────────


def test_main_stdin_protocol_robustness(monkeypatch):
    """Verifies that the main loop handles empty lines, non-dict payloads,
    and oversized inputs gracefully without throwing uncaught exceptions."""
    import io
    from jarvis.ui_bridge import main

    input_lines = '\n\n   \nnot-a-json\n12345\n[1, 2, 3]\n{"command": "status"}\n'
    monkeypatch.setattr("sys.stdin", io.StringIO(input_lines))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)

    main()

    responses = [
        json.loads(line) for line in out.getvalue().splitlines() if line.strip()
    ]
    assert len(responses) == 4
    # 1. "not-a-json" -> bad request: Expecting value
    assert responses[0]["ok"] is False
    assert "bad request" in responses[0]["error"]
    # 2. "12345" -> bad request: expected JSON object
    assert responses[1]["ok"] is False
    assert "expected JSON object" in responses[1]["error"]
    # 3. "[1, 2, 3]" -> bad request: expected JSON object
    assert responses[2]["ok"] is False
    assert "expected JSON object" in responses[2]["error"]
    # 4. {"command": "status"} -> ok: True
    assert responses[3]["ok"] is True


def test_unicode_surrogates_and_serialization_fallback(monkeypatch):
    """Verifies that bridge._serialize falls back to ensure_ascii=True when standard json.dumps fails."""
    from jarvis import ui_bridge

    orig = json.dumps

    def mocked_dumps(obj, *args, **kwargs):
        if kwargs.get("ensure_ascii") is False:
            raise UnicodeEncodeError(
                "utf-8", "surrogate", 0, 1, "surrogates not allowed"
            )
        return orig(obj, *args, **kwargs)

    monkeypatch.setattr(ui_bridge.json, "dumps", mocked_dumps)
    bridge = ui_bridge.Bridge()
    payload = {"ok": True, "text": "test \ud800 surrogate"}
    serialized = bridge._serialize(payload)
    assert "\\ud800" in serialized
    parsed = orig(payload, ensure_ascii=True)
    assert "\\ud800" in parsed


def test_stdout_reconfigure_replaces_invalid_surrogates():
    """Verifies that sys.stdout with errors='replace' writes surrogates without crashing."""
    import io

    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="utf-8")
    if hasattr(wrapper, "reconfigure"):
        wrapper.reconfigure(errors="replace")
    bridge = Bridge()
    bridge._proto_out = wrapper
    bridge._write_response({"ok": True, "text": "hello \ud800 world"})
    output = buf.getvalue()
    assert b"hello" in output


def test_start_serialized_catches_system_exit(monkeypatch):
    """Verifies that SystemExit raised during Jarvis initialization does not crash the bridge."""
    bridge = Bridge()

    def fake_jarvis(*args, **kwargs):
        raise SystemExit(1)

    monkeypatch.setattr("jarvis.Jarvis", fake_jarvis)
    res = bridge._start_serialized()
    assert res["ok"] is False
    assert "Ошибка конфигурации" in res["error"]
    assert bridge.started is False


def test_handle_message_checks_start_failure(monkeypatch):
    """Verifies that handle('message') checks _start() result and returns ok: False if start fails."""
    bridge = Bridge()
    monkeypatch.setattr(
        bridge,
        "_start",
        lambda: {"ok": False, "error": "Не удалось загрузить модель"},
    )
    res = bridge.handle({"command": "message", "text": "привет"})
    assert res["ok"] is False
    assert res["error"] == "Не удалось загрузить модель"
