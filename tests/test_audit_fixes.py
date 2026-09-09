"""Тесты для 8 дефектов безопасности и надежности по отчету аудита (Wave 6)."""

import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jarvis.modules.bash_agent import (
    _STARTUP_FILE_BASENAMES,
    _SENSITIVE_READ_BASENAMES,
    _SENSITIVE_READ_PARTS,
    _detect_dangerous,
    _is_hardline_blocked,
    _is_sensitive_read,
    _rm_recursive_targets,
    _touches_startup_file,
    _tool_read,
    _tool_write,
)
from jarvis.prompt_builder import redact_secrets


# ─────────────────────────────────────────────────────────────────────────────
# 1. SEC-CRIT-1: bash_agent rm -r without force hardline block & dangerous pattern
# ─────────────────────────────────────────────────────────────────────────────


class TestSecCrit1RmRecursive:
    """SEC-CRIT-1: rm -r / and rm -r ~ must be caught in hardline without requiring -f."""

    def test_rm_recursive_targets_extracts_without_force(self):
        targets = _rm_recursive_targets("rm -r /")
        assert "/" in targets

        targets_home = _rm_recursive_targets("rm -r ~")
        assert "~" in targets_home

        targets_long = _rm_recursive_targets("rm --recursive /var")
        assert "/var" in targets_long

    def test_rm_r_root_and_home_hardline_blocked(self):
        assert _is_hardline_blocked("rm -r /") is not None
        assert _is_hardline_blocked("rm -r ~") is not None
        assert _is_hardline_blocked("rm --recursive /") is not None
        assert _is_hardline_blocked("rm -r $HOME") is not None
        assert _is_hardline_blocked("rm -r /*") is not None

    def test_rm_recursive_dangerous_pattern(self):
        # Non-catastrophic recursive deletion must still trigger dangerous pattern
        w1 = _detect_dangerous("rm -r /tmp/test_dir")
        assert any("recursive rm" in x for x in w1)

        w2 = _detect_dangerous("rm --recursive /tmp/test_dir")
        assert any("recursive rm" in x for x in w2)

        w3 = _detect_dangerous("rm -R /tmp/test_dir")
        assert any("recursive rm" in x for x in w3)


# ─────────────────────────────────────────────────────────────────────────────
# 2. SEC-CRIT-2: bash_agent startup files and sensitive write patterns
# ─────────────────────────────────────────────────────────────────────────────


class TestSecCrit2StartupFiles:
    """SEC-CRIT-2: Add startup files and config.fish to startup basenames & write patterns."""

    @pytest.mark.parametrize(
        "filename",
        [
            ".zshenv",
            ".zlogin",
            ".bash_login",
            ".bash_aliases",
            ".xinitrc",
            "config.fish",
        ],
    )
    def test_startup_basenames_present(self, filename):
        assert filename in _STARTUP_FILE_BASENAMES

    @pytest.mark.parametrize(
        "cmd",
        [
            "touch ~/.zshenv",
            "echo evil > ~/.zlogin",
            "cat payload >> ~/.bash_login",
            "sed -i 's/a/b/' ~/.bash_aliases",
            "cp backdoor ~/.xinitrc",
            "tee ~/.config/fish/config.fish",
        ],
    )
    def test_startup_files_touch_detected(self, cmd):
        assert _touches_startup_file(cmd) is True
        w = _detect_dangerous(cmd)
        assert any("shell-startup file touched" in x for x in w)

    @pytest.mark.parametrize(
        "path",
        [
            "~/.zshenv",
            "/home/user/.zlogin",
            "~/.bash_login",
            "~/.bash_aliases",
            "/home/user/.xinitrc",
            "~/.config/fish/config.fish",
            "~/.config/fish/functions/fish_prompt.fish",
        ],
    )
    def test_tool_write_blocked_on_new_sensitive_targets(self, path):
        result = _tool_write(path, "evil payload")
        assert "[BLOCKED]" in result


# ─────────────────────────────────────────────────────────────────────────────
# 3. SEC-MAJ-1: bash_agent sensitive read basenames and parts
# ─────────────────────────────────────────────────────────────────────────────


class TestSecMaj1SensitiveReads:
    """SEC-MAJ-1: .netrc, .bash_history, .zsh_history, .docker/config.json, .kube/config."""

    @pytest.mark.parametrize(
        "basename",
        [
            ".netrc",
            ".bash_history",
            ".zsh_history",
        ],
    )
    def test_read_basenames_present(self, basename):
        assert basename in _SENSITIVE_READ_BASENAMES

    @pytest.mark.parametrize(
        "part",
        [
            ".docker/config.json",
            ".kube/config",
        ],
    )
    def test_read_parts_present(self, part):
        assert part in _SENSITIVE_READ_PARTS

    @pytest.mark.parametrize(
        "path",
        [
            "~/.netrc",
            "/home/user/.bash_history",
            "~/.zsh_history",
            "~/.docker/config.json",
            "/home/user/.kube/config",
        ],
    )
    def test_is_sensitive_read_and_blocked(self, path):
        assert _is_sensitive_read(path) is True
        result = _tool_read(path)
        assert "[BLOCKED]" in result


# ─────────────────────────────────────────────────────────────────────────────
# 4. SEC-MAJ-2: prompt_builder redact_secrets with spaces, comments, JSON, YAML
# ─────────────────────────────────────────────────────────────────────────────


class TestSecMaj2RedactSecrets:
    """SEC-MAJ-2: secrets with spaces, trailing comments, JSON/YAML pairs."""

    def test_env_secrets_with_spaces_and_comments(self):
        # Value with spaces
        s1 = 'MY_API_KEY="my secret token with spaces"'
        r1 = redact_secrets(s1)
        assert "[REDACTED]" in r1
        assert "my secret token with spaces" not in r1

        # Unquoted with spaces and comment
        s2 = "DB_PASSWORD=secret password 123 # dev database"
        r2 = redact_secrets(s2)
        assert "[REDACTED]" in r2
        assert "secret password 123" not in r2

        # Quoted with trailing comment
        s3 = 'SECRET_TOKEN="abc123xyz" # keep private'
        r3 = redact_secrets(s3)
        assert "[REDACTED]" in r3
        assert "abc123xyz" not in r3

    def test_json_and_yaml_pairs(self):
        # JSON pairs
        j1 = '{"api_key": "sk-test-secret-12345", "user": "test"}'
        rj1 = redact_secrets(j1)
        assert "sk-test-secret-12345" not in rj1
        assert '"api_key": "[REDACTED]"' in rj1
        assert '"user": "test"' in rj1

        # Single quoted JSON/dict
        j2 = "{'access_token': 'secret-token-value', 'role': 'admin'}"
        rj2 = redact_secrets(j2)
        assert "secret-token-value" not in rj2
        assert "'access_token': '[REDACTED]'" in rj2

        # YAML pairs with double quotes
        y1 = 'api_key: "very-secret-token"\nother_setting: true'
        ry1 = redact_secrets(y1)
        assert "very-secret-token" not in ry1
        assert 'api_key: "[REDACTED]"' in ry1

        # YAML pair with single quotes
        y2 = "access_token: 'another-secret-token'"
        ry2 = redact_secrets(y2)
        assert "another-secret-token" not in ry2
        assert "access_token: '[REDACTED]'" in ry2

        # YAML unquoted with comment
        y3 = "api_key: secret-value-here # production key"
        ry3 = redact_secrets(y3)
        assert "secret-value-here" not in ry3
        assert "[REDACTED]" in ry3


# ─────────────────────────────────────────────────────────────────────────────
# 5. SEC-MAJ-3: 0o600 permissions on history DB and JSON files
# ─────────────────────────────────────────────────────────────────────────────


class TestSecMaj3Permissions:
    """SEC-MAJ-3: 0o600 on history.db, llm history file, and ui_bridge history."""

    def test_history_db_connection_chmod_0600(self, tmp_path):
        from jarvis.modules import history_db

        db_path = tmp_path / "test_history.db"
        conn = history_db.get_connection(db_path)
        try:
            assert db_path.exists()
            mode = stat.S_IMODE(db_path.stat().st_mode)
            assert mode == 0o600
        finally:
            conn.close()

    def test_llm_save_history_raw_chmod_0600(self, tmp_path, monkeypatch):
        from jarvis.modules import llm

        test_history_file = tmp_path / "history.json"
        monkeypatch.setattr(llm, "HISTORY_FILE", test_history_file)

        sample_hist = [{"role": "user", "content": "hello"}]
        llm._save_history_raw(sample_hist)

        assert test_history_file.exists()
        mode = stat.S_IMODE(test_history_file.stat().st_mode)
        assert mode == 0o600

    def test_ui_bridge_archive_history_chmod_0600(self, tmp_path, monkeypatch):
        from jarvis.ui_bridge import Bridge

        bridge = Bridge()
        hist_dir = tmp_path / "ui-history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(bridge, "_history_dir", lambda: hist_dir)
        bridge._current_session = "test_session_123"

        # Mock clients and llm_module history
        with patch(
            "jarvis.modules.llm._load_history",
            return_value=[{"role": "user", "content": "hi"}],
        ):
            bridge._archive_current()

        target_file = hist_dir / "test_session_123.json"
        assert target_file.exists()
        mode = stat.S_IMODE(target_file.stat().st_mode)
        assert mode == 0o600

        # Legacy archive
        bridge._current_session = None
        with patch(
            "jarvis.modules.llm._load_history",
            return_value=[{"role": "user", "content": "legacy"}],
        ):
            bridge._archive_legacy_history()

        legacy_file = hist_dir / "_legacy-cli.json"
        assert legacy_file.exists()
        legacy_mode = stat.S_IMODE(legacy_file.stat().st_mode)
        assert legacy_mode == 0o600


# ─────────────────────────────────────────────────────────────────────────────
# 6. CONC-MAJ-1: ui_bridge _shutdown_voice thread join & cleanup
# ─────────────────────────────────────────────────────────────────────────────


class TestConcMaj1ShutdownVoice:
    """CONC-MAJ-1: _shutdown_voice joins thread with timeout and clears reference."""

    def test_shutdown_voice_joins_and_clears_thread(self):
        from jarvis.ui_bridge import Bridge

        bridge = Bridge()
        mock_thread = MagicMock()
        bridge._voice_thread = mock_thread

        bridge._shutdown_voice()

        mock_thread.join.assert_called_once_with(timeout=2.0)
        assert bridge._voice_thread is None

    def test_shutdown_voice_handles_none_thread(self):
        from jarvis.ui_bridge import Bridge

        bridge = Bridge()
        bridge._voice_thread = None

        bridge._shutdown_voice()
        assert bridge._voice_thread is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. LEAK-MAJ-1: StatusTab cancelled flag in voice-event listener
# ─────────────────────────────────────────────────────────────────────────────


class TestLeakMaj1StatusTab:
    """LEAK-MAJ-1: Verify StatusTab.tsx contains the cancelled flag pattern."""

    def test_status_tab_implements_cancelled_flag(self):
        status_tab_path = (
            Path(__file__).parent.parent
            / "jarvis-ui"
            / "src"
            / "tabs"
            / "StatusTab.tsx"
        )
        content = status_tab_path.read_text(encoding="utf-8")

        assert "cancelled" in content
        assert "unlisten" in content


# ─────────────────────────────────────────────────────────────────────────────
# 8. COMPAT-MAJ-1: afplay in tts and open on macOS in commands web_search
# ─────────────────────────────────────────────────────────────────────────────


class TestCompatMaj1TtsAndCommands:
    """COMPAT-MAJ-1: afplay fallback in tts, macOS 'open' in commands _web_search."""

    def test_tts_player_commands_contains_afplay(self):
        from jarvis.modules.tts import _player_commands

        cmds = _player_commands("test.wav")
        assert ["afplay", "test.wav"] in cmds

    def test_commands_web_search_darwin_vs_linux(self, tmp_path):
        from jarvis.modules.commands import CommandExecutor

        cmd_file = tmp_path / "cmd.json"
        cmd_file.write_text('{"commands": {}}', encoding="utf-8")
        app_file = tmp_path / "apps.json"
        app_file.write_text('{"apps": {}}', encoding="utf-8")
        executor = CommandExecutor(commands_file=cmd_file, apps_file=app_file)
        with patch.object(executor, "_run") as mock_run:
            with patch.object(sys, "platform", "darwin"):
                executor._web_search("test query")
                mock_run.assert_called_once()
                args, _ = mock_run.call_args
                assert args[0].startswith("open ")
                assert "test+query" in args[0]

        with patch.object(executor, "_run") as mock_run:
            with patch.object(sys, "platform", "linux"):
                executor._web_search("test query")
                mock_run.assert_called_once()
                args, _ = mock_run.call_args
                assert args[0].startswith("xdg-open ")
                assert "test+query" in args[0]
