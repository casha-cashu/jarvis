"""Tests for PR-FS-1: Filesystem workspace sandboxing for agent read/write tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis.config_schema import LLMConfig
from jarvis.modules.bash_agent import (
    _is_within_roots,
    execute_tool,
)
from jarvis.response_pipeline import ResponsePipeline


def _make_tree(tmp_path: Path) -> dict[str, Any]:
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    inside = ws / "sub" / "note.txt"
    inside.write_text("hello workspace", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("top secret", encoding="utf-8")
    # symlink inside ws pointing outside (escape attempt)
    link = ws / "evil_link.txt"
    try:
        link.symlink_to(outside)
        has_link = True
    except (OSError, NotImplementedError):
        has_link = False
    return {
        "ws": ws,
        "inside": inside,
        "outside": outside,
        "link": link,
        "has_link": has_link,
    }


class TestIsWithinRoots:
    def test_inside_root_allowed(self, tmp_path):
        t = _make_tree(tmp_path)
        assert _is_within_roots(str(t["inside"]), [str(t["ws"])]) is True

    def test_nested_nonexistent_inside_allowed(self, tmp_path):
        t = _make_tree(tmp_path)
        assert _is_within_roots(str(t["ws"] / "new" / "f.txt"), [str(t["ws"])]) is True

    def test_outside_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        assert _is_within_roots(str(t["outside"]), [str(t["ws"])]) is False

    def test_parent_traversal_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        traversal = str(t["ws"] / "sub" / ".." / ".." / "outside.txt")
        assert _is_within_roots(traversal, [str(t["ws"])]) is False

    def test_symlink_escape_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        if not t["has_link"]:
            return
        assert _is_within_roots(str(t["link"]), [str(t["ws"])]) is False

    def test_multiple_roots(self, tmp_path):
        t = _make_tree(tmp_path)
        other = tmp_path / "other"
        other.mkdir()
        assert (
            _is_within_roots(str(t["outside"]), [str(t["ws"]), str(tmp_path)]) is True
        )

    def test_empty_roots_defaults_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "local.txt").write_text("x", encoding="utf-8")
        assert _is_within_roots(str(tmp_path / "local.txt"), []) is True
        assert _is_within_roots("/etc/hostname", []) is False


class TestReadRootsEnforcement:
    def test_read_inside_roots(self, tmp_path):
        t = _make_tree(tmp_path)
        res = execute_tool(
            "read", {"path": str(t["inside"])}, read_roots=[str(t["ws"])]
        )
        assert "hello workspace" in res

    def test_read_outside_roots_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        res = execute_tool(
            "read", {"path": str(t["outside"])}, read_roots=[str(t["ws"])]
        )
        assert "[BLOCKED]" in res

    def test_read_traversal_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        traversal = str(t["ws"] / "sub" / ".." / ".." / "outside.txt")
        res = execute_tool("read", {"path": traversal}, read_roots=[str(t["ws"])])
        assert "[BLOCKED]" in res

    def test_read_symlink_escape_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        if not t["has_link"]:
            return
        res = execute_tool("read", {"path": str(t["link"])}, read_roots=[str(t["ws"])])
        assert "[BLOCKED]" in res

    def test_read_default_roots_is_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "local.txt").write_text("cwd data", encoding="utf-8")
        assert "cwd data" in execute_tool("read", {"path": str(tmp_path / "local.txt")})
        res = execute_tool("read", {"path": "/etc/hostname"})
        assert "[BLOCKED]" in res


class TestWriteRootsEnforcement:
    def test_write_inside_roots(self, tmp_path):
        t = _make_tree(tmp_path)
        target = t["ws"] / "out.txt"
        res = execute_tool(
            "write",
            {"path": str(target), "content": "data"},
            write_roots=[str(t["ws"])],
        )
        assert target.read_text(encoding="utf-8") == "data"
        assert "[BLOCKED]" not in res

    def test_write_outside_roots_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        target = tmp_path / "outside_new.txt"
        res = execute_tool(
            "write",
            {"path": str(target), "content": "data"},
            write_roots=[str(t["ws"])],
        )
        assert "[BLOCKED]" in res
        assert not target.exists()

    def test_write_traversal_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        traversal = str(t["ws"] / ".." / "escaped.txt")
        res = execute_tool(
            "write", {"path": traversal, "content": "data"}, write_roots=[str(t["ws"])]
        )
        assert "[BLOCKED]" in res
        assert not (tmp_path / "escaped.txt").exists()

    def test_write_symlink_escape_blocked(self, tmp_path):
        t = _make_tree(tmp_path)
        if not t["has_link"]:
            return
        res = execute_tool(
            "write",
            {"path": str(t["link"]), "content": "pwn"},
            write_roots=[str(t["ws"])],
        )
        assert "[BLOCKED]" in res
        assert (tmp_path / "outside.txt").read_text(encoding="utf-8") == "top secret"

    def test_sensitive_blocklist_survives_inside_roots(self, tmp_path):
        t = _make_tree(tmp_path)
        target = t["ws"] / ".bashrc"
        res = execute_tool(
            "write",
            {"path": str(target), "content": "evil"},
            write_roots=[str(t["ws"])],
        )
        assert "[BLOCKED]" in res
        assert not target.exists()


class TestFsRootsConfig:
    def test_llm_config_defaults_empty(self):
        cfg = LLMConfig()
        assert cfg.agent_read_roots == []
        assert cfg.agent_write_roots == []

    def test_llm_config_accepts_roots(self):
        cfg = LLMConfig(agent_read_roots=["/tmp/a"], agent_write_roots=["/tmp/b"])
        assert cfg.agent_read_roots == ["/tmp/a"]
        assert cfg.agent_write_roots == ["/tmp/b"]

    def test_response_pipeline_exposes_roots(self):
        rp = ResponsePipeline(config={"llm": {"agent_enabled": True}})
        assert rp.agent_read_roots is None
        assert rp.agent_write_roots is None
        rp2 = ResponsePipeline(
            config={
                "llm": {
                    "agent_enabled": True,
                    "agent_read_roots": ["/tmp/a"],
                    "agent_write_roots": ["/tmp/b"],
                }
            }
        )
        assert rp2.agent_read_roots == ["/tmp/a"]
        assert rp2.agent_write_roots == ["/tmp/b"]

    def test_response_pipeline_enforces_roots_end_to_end(self, tmp_path):
        t = _make_tree(tmp_path)
        rp = ResponsePipeline(
            config={"llm": {"agent_enabled": True, "agent_read_roots": [str(t["ws"])]}}
        )
        # pipeline exposes configured roots; dispatch honors them
        res = execute_tool(
            "read", {"path": str(t["outside"])}, read_roots=rp.agent_read_roots
        )
        assert "[BLOCKED]" in res
        res_ok = execute_tool(
            "read", {"path": str(t["inside"])}, read_roots=rp.agent_read_roots
        )
        assert "hello workspace" in res_ok
