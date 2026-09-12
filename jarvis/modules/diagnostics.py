"""Diagnostics module for generating sanitized bug reports."""

from __future__ import annotations

import json
import logging
import os
import platform
import stat
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from jarvis.prompt_builder import redact_secrets

logger = logging.getLogger(__name__)


def get_system_info() -> Dict[str, Any]:
    """Gathers general operating system, Python, and hardware environment info."""
    try:
        from importlib.metadata import version

        jarvis_ver = version("jarvis-voice-assistant")
    except Exception:
        jarvis_ver = "development"

    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or "unknown"
    )
    session_type = os.environ.get("XDG_SESSION_TYPE") or (
        "wayland"
        if os.environ.get("WAYLAND_DISPLAY")
        else "x11"
        if os.environ.get("DISPLAY")
        else "headless"
    )

    return {
        "jarvis_version": jarvis_ver,
        "python_version": sys.version,
        "os": platform.system(),
        "os_release": platform.release(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "desktop": desktop,
        "session_type": session_type,
        "timestamp": datetime.now().isoformat(),
    }


def get_history_metadata(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Inspects history.db metadata (size, permissions, counts) without exposing any message content."""
    from jarvis.modules import history_db

    p = db_path or history_db.get_db_path()
    p = Path(p)

    if not p.exists():
        return {
            "exists": False,
            "path": str(p),
            "file_size": 0,
            "sessions_count": 0,
            "messages_count": 0,
        }

    try:
        st = p.stat()
        file_size = st.st_size
        file_mode = oct(stat.S_IMODE(st.st_mode))
    except Exception:
        file_size = 0
        file_mode = "unknown"

    sessions_count = 0
    messages_count = 0
    try:
        conn = history_db.get_connection(p)
        cur = conn.execute("SELECT COUNT(*) FROM sessions")
        sessions_count = int(cur.fetchone()[0])
        cur = conn.execute("SELECT COUNT(*) FROM messages")
        messages_count = int(cur.fetchone()[0])
        conn.close()
    except Exception as exc:
        logger.warning("Failed to query history db for diagnostics: %s", exc)

    return {
        "exists": True,
        "path": str(p),
        "file_size": file_size,
        "file_mode": file_mode,
        "sessions_count": sessions_count,
        "messages_count": messages_count,
    }


def create_bugreport(
    config_path: Optional[str] = None,
    log_path: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Path:
    """Creates a sanitized .zip diagnostics bundle for bug reports.

    All credentials and secrets in config and logs are automatically stripped.
    """
    out_dir = Path(
        output_dir or os.path.expanduser("~/.local/share/jarvis/diagnostics")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_dir, 0o700)
    except OSError:
        pass

    timestamp_str = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = out_dir / f"bugreport-{timestamp_str}.zip"

    # 1. System Info
    sys_info = get_system_info()

    # 2. Config (redacted)
    conf_path = Path(config_path or "config.yaml")
    redacted_config = ""
    if conf_path.exists():
        try:
            raw_conf = conf_path.read_text(encoding="utf-8")
            redacted_config = redact_secrets(raw_conf)
        except Exception as e:
            redacted_config = f"# Error reading config: {e}\n"
    else:
        redacted_config = "# config.yaml not found\n"

    # 3. Recent logs (last 300 lines, redacted)
    l_path = Path(log_path or "logs/jarvis.log")
    recent_logs = ""
    if l_path.exists():
        try:
            raw_logs = l_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail_logs = "\n".join(raw_logs[-300:])
            recent_logs = redact_secrets(tail_logs)
        except Exception as e:
            recent_logs = f"# Error reading log: {e}\n"
    else:
        recent_logs = "# logs/jarvis.log not found\n"

    # 4. History metadata
    hist_meta = get_history_metadata()

    # 5. Doctor summary
    doctor_text = ""
    try:
        from jarvis.doctor import run_checks

        cfg_arg = str(conf_path) if conf_path and conf_path.exists() else "config.yaml"
        checks = run_checks(cfg_arg)
        lines = [
            f"[{c.get('status')}] {c.get('name')}: {c.get('detail')}" for c in checks
        ]
        doctor_text = "\n".join(lines) + "\n"
    except Exception as e:
        doctor_text = f"Doctor check unavailable: {e}\n"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "system_info.json", json.dumps(sys_info, indent=2, ensure_ascii=False)
        )
        zf.writestr("config_redacted.yaml", redacted_config)
        zf.writestr("recent_logs.txt", recent_logs)
        zf.writestr(
            "history_metadata.json", json.dumps(hist_meta, indent=2, ensure_ascii=False)
        )
        zf.writestr("doctor_summary.txt", doctor_text)

    try:
        os.chmod(zip_path, 0o600)
    except OSError:
        pass

    return zip_path


# Alias for compatibility with PR-UI-OBS-1
generate_diagnostics_bundle = create_bugreport
