"""Тесты для jarvis.prompt_builder — промпт, TTS-sanitize, redact, truncate."""

import pytest

from jarvis.prompt_builder import (
    agent_query_prefix,
    compose_system_prompt,
    redact_secrets,
    sanitize_for_tts,
    truncate_tool_output,
)


class TestComposeSystemPrompt:
    def test_base_only(self):
        assert compose_system_prompt("База", False) == "База"

    def test_base_with_tools(self):
        result = compose_system_prompt("База", True, tools_prompt="Инструменты")
        assert result == "База\n\nИнструменты"

    def test_tools_omitted_when_disabled(self):
        result = compose_system_prompt("База", False, tools_prompt="Инструменты")
        assert "Инструменты" not in result

    def test_platform_substitution(self):
        result = compose_system_prompt(
            "Система: {platform}", True, platform_str="linux/arch (Hyprland)"
        )
        assert "linux/arch (Hyprland)" in result
        assert "{platform}" not in result

    def test_empty_inputs(self):
        assert compose_system_prompt(None, False) == ""
        assert compose_system_prompt("", True, tools_prompt=None) == ""


class TestAgentQueryPrefix:
    def test_disabled_passthrough(self):
        assert agent_query_prefix("погода", "ollama", enabled=False) == "погода"

    def test_ollama_prefixed(self):
        result = agent_query_prefix("погода", "ollama", enabled=True)
        assert result.startswith("При необходимости используй tool сразу.")
        assert result.endswith("погода")

    def test_non_ollama_not_prefixed(self):
        assert agent_query_prefix("погода", "openai", enabled=True) == "погода"


class TestSanitizeForTts:
    def test_short_text_passthrough(self):
        text = "Привет, чем могу помочь?"
        assert sanitize_for_tts(text) == text

    def test_strips_code_fences(self):
        result = sanitize_for_tts("```\nls -la\n```")
        assert "```" not in result
        assert "ls -la" in result

    def test_strips_headers_and_bullets(self):
        result = sanitize_for_tts("# Заголовок\n- пункт один")
        assert "#" not in result
        assert "- " not in result
        assert "Заголовок" in result and "пункт один" in result

    def test_strips_emoji(self):
        result = sanitize_for_tts("Привет 🙂 мир")
        assert "🙂" not in result
        assert "Привет" in result and "мир" in result

    def test_long_text_cut_at_sentence(self):
        text = "Первое короткое. " + "Второе предложение заметно длиннее. " * 8
        assert len(text) > 220
        result = sanitize_for_tts(text)
        assert len(result) < len(text)
        assert result.endswith("Рассказать подробнее?")

    def test_hard_truncate_marker(self):
        text = "а" * 500
        result = sanitize_for_tts(text)
        assert len(result) <= 405
        assert result.endswith("…")


class TestRedactSecretsEnvSuffixes:
    """Находка аудита: расширение списка суффиксов секретных env-строк."""

    @pytest.mark.parametrize(
        "line",
        [
            "API_KEY=abcd1234",
            "SECRET_TOKEN=tok123456",
            "DB_PASSWORD=hunter2",
            "PG_PASSWD=pw123",
            "DB_PASSPHRASE=s3cret",  # новый суффикс PASSPHRASE
            "SUDO_ASKPASS=/usr/bin/helper",  # новый суффикс ASKPASS
            "APP_AUTH=basic123",  # новый суффикс AUTH
            "AWS_CREDENTIALS=default",  # новый суффикс CREDENTIALS?
            "export KIRO_API_KEY=sk1234567890",
            'MY_SECRET="quoted-value"',
        ],
    )
    def test_value_redacted(self, line):
        redacted = redact_secrets(line)
        assert "[REDACTED]" in redacted
        assert line.split("=", 1)[1].strip('"') not in redacted

    @pytest.mark.parametrize(
        "line",
        [
            "PATH=/usr/local/bin:/usr/bin",
            "HOME=/home/misha",
            "SHELL=/bin/zsh",
            "EDITOR=vim",
        ],
    )
    def test_benign_env_lines_survive(self, line):
        assert redact_secrets(line) == line


class TestRedactSecretsPatterns:
    def test_api_key_pattern(self):
        assert "[REDACTED]" in redact_secrets("key: sk-abcdefghijklmnop12")

    def test_github_pat(self):
        token = "ghp_" + "A1b2C3d4" * 5
        assert "[REDACTED]" in redact_secrets(f"token {token}")

    def test_db_url_creds(self):
        result = redact_secrets("postgres://admin:hunter2@db.local/prod")
        assert "hunter2" not in result

    def test_generic_url_creds_keep_host(self):
        result = redact_secrets("see https://admin:hunter2@example.com/path")
        assert "hunter2" not in result
        assert "example.com" in result


class TestTruncateToolOutput:
    def test_short_passthrough(self):
        assert truncate_tool_output("abc") == "abc"

    def test_empty(self):
        assert truncate_tool_output("") == ""

    def test_long_head_and_tail(self):
        out = truncate_tool_output("H" * 800 + "M" * 500 + "T" * 200)
        assert "[TRUNCATED]" in out
        assert out.startswith("H" * 10)
        assert out.endswith("T" * 10)
