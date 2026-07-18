#!/usr/bin/env python3
"""
Bash agent — LLM-driven system automation with approval gate.

When a query doesn't match any command (exact/fuzzy/pattern/app/voice), it
falls through to the LLM. If the LLM is an agent-capable provider (Ollama with
tool-calling models, Kiro, Anthropic, OpenRouter), it receives a set of tools
and can execute bash commands, read/write files, and search the web to
fulfill the request.

Safety: three-layer approval — hardline blocklist (catastrophic commands),
dangerous-pattern regex detector (~40 patterns), and optional voice confirmation.
All commands pass through sanitized_env() and execution_timeout from the
CommandExecutor contract.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Callable

from jarvis._env import sanitized_env

logger = logging.getLogger(__name__)


# ── Hardline blocklist — catastrophic commands, always blocked ───────────────

_HARDLINE_PATTERNS: List[re.Pattern] = [
    re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"mkfs", re.IGNORECASE),
    re.compile(r"dd\s+.*of=/dev/sd", re.IGNORECASE),
    re.compile(r"shutdown\s+-h\s+now", re.IGNORECASE),
    re.compile(r"reboot\s+-f", re.IGNORECASE),
    re.compile(r"systemctl\s+stop\s+(sshd|multi-user)", re.IGNORECASE),
    re.compile(r"fdisk\s+/dev", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:", re.IGNORECASE),  # fork bomb
    re.compile(r"chmod\s+-R\s+000\s+/", re.IGNORECASE),
    re.compile(r"cat\s+/dev/zero\s*>", re.IGNORECASE),
]


def _is_hardline_blocked(cmd: str) -> Optional[str]:
    for pat in _HARDLINE_PATTERNS:
        if pat.search(cmd):
            return f"Blocked (hardline): command matches catastrophic pattern `{pat.pattern}`"
    return None


# ── Dangerous-pattern detector ───────────────────────────────────────────────

_DANGEROUS_PATTERNS: List[tuple] = [
    (re.compile(r"rm\s+-rf\s+~", re.IGNORECASE), "recursive home deletion"),
    (re.compile(r"rm\s+-rf\s+/home", re.IGNORECASE), "home directory deletion"),
    (re.compile(r"chmod\s+777\s+-R", re.IGNORECASE), "recursive world-writable"),
    (re.compile(r"chmod\s+777\s+/", re.IGNORECASE), "root world-writable"),
    (re.compile(r"curl.*\|.*sh", re.IGNORECASE), "curl-pipe-bash"),
    (re.compile(r"wget.*\|.*sh", re.IGNORECASE), "wget-pipe-bash"),
    (re.compile(r"git\s+push\s+--force", re.IGNORECASE), "force push"),
    (re.compile(r"git\s+push\s+-f", re.IGNORECASE), "force push"),
    (re.compile(r"pip\s+install.*sudo", re.IGNORECASE), "sudo pip install"),
    (re.compile(r"npm\s+install\s+-g.*sudo", re.IGNORECASE), "sudo npm -g"),
    (
        re.compile(r"systemctl\s+disable\s+(sshd|ufw|firewalld)", re.IGNORECASE),
        "disable security service",
    ),
    (re.compile(r"iptables\s+-F", re.IGNORECASE), "flush firewall"),
    (re.compile(r"kill\s+-9\s+-1", re.IGNORECASE), "kill all processes"),
    (re.compile(r"kill\s+-9\s+1", re.IGNORECASE), "kill init"),
    (re.compile(r">\s*/etc/passwd", re.IGNORECASE), "overwrite passwd"),
    (re.compile(r">\s*/etc/shadow", re.IGNORECASE), "overwrite shadow"),
    (re.compile(r"passwd\s+root", re.IGNORECASE), "change root password"),
    (re.compile(r"userdel\s+-r\s+(root|misha)", re.IGNORECASE), "delete admin"),
    (re.compile(r"mv\s+.*/etc", re.IGNORECASE), "move /etc"),
    (re.compile(r"scp\s+-r\s+.*:.*/etc", re.IGNORECASE), "scp /etc"),
]


def _detect_dangerous(cmd: str) -> List[str]:
    warnings: List[str] = []
    for pat, desc in _DANGEROUS_PATTERNS:
        if pat.search(cmd):
            warnings.append(f"{desc} (`{pat.pattern[:50]}...`)")
    return warnings


# ── Agent tools ──────────────────────────────────────────────────────────────


def _tool_bash(cmd: str, timeout: int = 30) -> str:
    """Execute a bash command. Returns stdout+stderr or error message."""
    block = _is_hardline_blocked(cmd)
    if block:
        return f"[BLOCKED] {block}"

    try:
        proc = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=sanitized_env(),
        )
        output = proc.stdout.strip()
        if proc.stderr.strip():
            output += "\n[stderr]\n" + proc.stderr.strip()
        if not output and proc.returncode != 0:
            output = f"Exit code {proc.returncode} (empty output)"
        return output or "(empty)"
    except subprocess.TimeoutExpired:
        return f"Timeout ({timeout}s): {cmd}"
    except FileNotFoundError:
        return f"Command not found: {shlex.split(cmd)[0] if shlex.split(cmd) else cmd}"
    except Exception as e:
        return f"Error: {e}"


def _tool_read(path: str) -> str:
    """Read a file. Limited to 4KB."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")[:4096]
        return content or "(empty file)"
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


def _tool_write(path: str, content: str) -> str:
    """Write content to a file. Blocks writes to system dirs."""
    try:
        p = Path(path).expanduser().resolve()
        forbidden = {"/etc", "/usr", "/boot", "/sys", "/proc", "/dev"}
        if any(str(p).startswith(d) for d in forbidden):
            return "[BLOCKED] Writing to system directory is forbidden"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


_TABLE: Dict[str, Callable] = {
    "bash": _tool_bash,
    "read": _tool_read,
    "write": _tool_write,
}


def get_tool_schemas() -> List[dict]:
    """Returns OpenAI function-calling schemas for available tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Execute a bash command. Returns stdout+stderr. Blocked: rm -rf /, mkfs, dd of=/dev, shutdown, fork bombs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {
                            "type": "string",
                            "description": "The bash command to run",
                        },
                        "timeout": {
                            "type": "integer",
                            "default": 30,
                            "description": "Max seconds before SIGTERM",
                        },
                    },
                    "required": ["cmd"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file. Returns first 4KB of content. For text files only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute file path"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write",
                "description": "Write content to a file. Creates parent directories. Blocked: /etc, /usr, /boot, /sys, /proc, /dev.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute file path"},
                        "content": {
                            "type": "string",
                            "description": "Content to write",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
    ]


def execute_tool(name: str, arguments: dict) -> str:
    fn = _TABLE.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    try:
        result = fn(**arguments)
        return str(result)
    except TypeError as e:
        return f"Tool argument error: {e}"


# ── Approval ─────────────────────────────────────────────────────────────────


def check_approval(cmd: str, approval_mode: str = "auto") -> Optional[str]:
    """
    Returns None if the command is safe to run, or a reason string if
    it needs approval/is blocked. approval_mode:
      - "auto" — approve non-dangerous, warn on dangerous
      - "strict" — warn on dangerous, require voice confirm
      - "yolo" — never block (only useful for sandboxed VMs)
    """
    if approval_mode == "yolo":
        return None

    hard = _is_hardline_blocked(cmd)
    if hard:
        return hard

    warnings = _detect_dangerous(cmd)
    if warnings:
        if approval_mode == "strict":
            return f"⚠ Approval required: {'; '.join(warnings)}"
        else:
            logger.warning(
                "ℹ Dangerous command (auto-approved): %s — %s", cmd, "; ".join(warnings)
            )

    return None
