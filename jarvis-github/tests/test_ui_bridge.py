import json

from jarvis.ui_bridge import Bridge


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
