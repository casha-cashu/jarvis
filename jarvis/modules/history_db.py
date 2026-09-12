"""SQLite-based storage for dialog history and sessions.

Replaces flat JSON files and FileLock with an ACID-compliant, concurrent
SQLite database using Write-Ahead Logging (WAL) mode.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(
    os.environ.get("JARVIS_HISTORY_DB")
    or os.path.expanduser("~/.local/share/jarvis/history.db")
)


def get_db_path() -> Path:
    env_path = os.environ.get("JARVIS_HISTORY_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def ensure_db_file_permissions(db_path: Path | str) -> None:
    """Ensures the SQLite database file and its WAL/SHM companion files are set to 0600 mode."""
    p_str = str(db_path)
    if p_str == ":memory:":
        return
    base_path = Path(p_str)
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{base_path}{suffix}")
        if target.exists():
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if str(path) != ":memory:":
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    _init_schema(conn)
    ensure_db_file_permissions(path)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);"
        )


def _migrate_from_json_if_needed(conn: sqlite3.Connection, json_path: Path) -> None:
    """Imports legacy history.json if the database is newly created and empty."""
    try:
        cur = conn.execute("SELECT COUNT(*) FROM messages")
        if cur.fetchone()[0] > 0:
            return

        if not json_path.exists():
            return

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list) and data:
            now = time.time()
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    ("default", "Default Session", now, now),
                )
                for item in data:
                    if isinstance(item, dict) and "role" in item and "content" in item:
                        conn.execute(
                            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                            ("default", item["role"], item["content"], now),
                        )
            logger.info("Migrated %d messages from %s to SQLite", len(data), json_path)
    except Exception as exc:
        logger.warning("Failed to migrate legacy history.json: %s", exc)


def load_history(
    session_id: str = "default",
    limit: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> List[Dict[str, str]]:
    """Loads chat messages for session_id. Format: [{'role': '...', 'content': '...'}]"""
    path = db_path or get_db_path()
    try:
        conn = get_connection(path)
        # Check legacy migration on first read
        legacy_json = Path(
            os.environ.get("JARVIS_HISTORY_FILE")
            or os.path.expanduser("~/.local/share/jarvis/history.json")
        )
        _migrate_from_json_if_needed(conn, legacy_json)

        query = (
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC"
        )
        params: list[Any] = [session_id]
        if limit and limit > 0:
            query = (
                "SELECT role, content FROM ("
                "SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC"
            )
            params.append(limit)

        cur = conn.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    except Exception as exc:
        logger.warning("Failed to load history from SQLite: %s", exc)
        return []


def save_history(
    history: List[Dict[str, str]],
    session_id: str = "default",
    db_path: Optional[Path] = None,
) -> None:
    """Atomically replaces the full message history for session_id."""
    path = db_path or get_db_path()
    try:
        conn = get_connection(path)
        now = time.time()
        with conn:
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at = ?",
                (session_id, session_id, now, now, now),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            for item in history:
                if isinstance(item, dict) and "role" in item and "content" in item:
                    conn.execute(
                        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                        (session_id, item["role"], item["content"], now),
                    )
        conn.close()
    except Exception as exc:
        logger.warning("Failed to save history to SQLite: %s", exc)


def append_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Appends a single message to a session and updates timestamp."""
    path = db_path or get_db_path()
    try:
        conn = get_connection(path)
        now = time.time()
        meta_str = json.dumps(metadata, ensure_ascii=False) if metadata else None
        with conn:
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at = ?",
                (session_id, session_id, now, now, now),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, now, meta_str),
            )
        conn.close()
    except Exception as exc:
        logger.warning("Failed to append message to SQLite: %s", exc)


def clear_history(session_id: str = "default", db_path: Optional[Path] = None) -> None:
    """Clears all messages for a given session."""
    path = db_path or get_db_path()
    try:
        conn = get_connection(path)
        with conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (time.time(), session_id),
            )
        conn.close()
    except Exception as exc:
        logger.warning("Failed to clear history in SQLite: %s", exc)


def list_sessions(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Returns metadata for all available sessions."""
    path = db_path or get_db_path()
    try:
        conn = get_connection(path)
        cur = conn.execute(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) as message_count
            FROM sessions s
            LEFT JOIN messages m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "message_count": r["message_count"],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Failed to list sessions from SQLite: %s", exc)
        return []


def delete_session(session_id: str, db_path: Optional[Path] = None) -> bool:
    """Deletes a session and all its messages."""
    path = db_path or get_db_path()
    try:
        conn = get_connection(path)
        with conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.close()
        return True
    except Exception as exc:
        logger.warning("Failed to delete session %s from SQLite: %s", session_id, exc)
        return False


def purge_all_sessions(db_path: Optional[Path] = None) -> int:
    """Deletes all sessions and messages. Returns number of purged sessions."""
    path = db_path or get_db_path()
    try:
        conn = get_connection(path)
        with conn:
            cur = conn.execute("DELETE FROM sessions")
            count = cur.rowcount
            conn.execute("DELETE FROM messages")
        conn.close()
        return max(0, count)
    except Exception as exc:
        logger.warning("Failed to purge all sessions from SQLite: %s", exc)
        return 0
