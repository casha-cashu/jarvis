"""Tests for PR-OBS-1: Diagnostics report module and jarvis bugreport CLI."""

from __future__ import annotations

import json
import zipfile

from jarvis.modules.diagnostics import (
    create_bugreport,
    get_system_info,
    get_history_metadata,
)


class TestDiagnosticsModule:
    def test_get_system_info(self):
        info = get_system_info()
        assert "jarvis_version" in info
        assert "python_version" in info
        assert "os" in info
        assert "platform" in info

    def test_get_history_metadata_missing_db(self, tmp_path):
        meta = get_history_metadata(tmp_path / "nonexistent.db")
        assert meta["exists"] is False
        assert meta["sessions_count"] == 0

    def test_get_history_metadata_existing_db(self, tmp_path):
        from jarvis.modules import history_db

        db_path = tmp_path / "hist.db"
        conn = history_db.get_connection(db_path)
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('s1', 'T', 1, 1)"
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', 'user', 'secret text', 1)"
        )
        conn.commit()
        conn.close()

        meta = get_history_metadata(db_path)
        assert meta["exists"] is True
        assert meta["sessions_count"] == 1
        assert meta["messages_count"] == 1
        assert meta["file_size"] > 0
        # Crucial security assertion: NO raw message contents in metadata!
        assert "secret text" not in json.dumps(meta)

    def test_create_bugreport_creates_valid_zip_with_redacted_secrets(self, tmp_path):
        # Setup fake config with sensitive secrets
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "llm:\n  openai:\n    api_key: 'sk-SUPERSECRET123456'\n"
            "telegram:\n  bot_token: '123456:SECRET_BOT_TOKEN'\n",
            encoding="utf-8",
        )

        # Setup fake log with sensitive secrets
        log_file = tmp_path / "jarvis.log"
        log_file.write_text(
            "2026-09-12 12:00:00 INFO Initializing\n"
            "2026-09-12 12:00:01 DEBUG Auth token: sk-SUPERSECRET123456\n",
            encoding="utf-8",
        )

        output_dir = tmp_path / "diagnostics_out"
        zip_path = create_bugreport(
            config_path=str(config_file),
            log_path=str(log_file),
            output_dir=str(output_dir),
        )

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            assert "system_info.json" in namelist
            assert "config_redacted.yaml" in namelist
            assert "recent_logs.txt" in namelist
            assert "history_metadata.json" in namelist

            config_content = zf.read("config_redacted.yaml").decode("utf-8")
            assert "sk-SUPERSECRET123456" not in config_content
            assert "[REDACTED]" in config_content

            log_content = zf.read("recent_logs.txt").decode("utf-8")
            assert "sk-SUPERSECRET123456" not in log_content
            assert "[REDACTED]" in log_content

    def test_cli_cmd_bugreport(self, tmp_path, capsys):
        from jarvis.cli import cmd_bugreport
        from argparse import Namespace

        out_dir = tmp_path / "cli_diag"
        args = Namespace(output=str(out_dir), config=None)

        cmd_bugreport(args)
        captured = capsys.readouterr()
        assert "отчет" in captured.out.lower() or "bugreport" in captured.out.lower()
        assert str(out_dir) in captured.out
