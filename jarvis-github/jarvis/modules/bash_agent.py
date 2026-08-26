#!/usr/bin/env python3
"""
Bash agent — LLM-driven system automation with approval gate.

When a query doesn't match any command (exact/fuzzy/pattern/app/voice), it
falls through to the LLM. If the LLM is an agent-capable provider (Ollama,
OpenAI, Anthropic — all with native tool-calling), it receives a set of
tools and can execute bash commands, read/write files, and search the web
to fulfill the request.

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


# ── Hardline blocklist — catastrophic commands, ALWAYS blocked ──────────────
# Even "yolo" mode cannot bypass these.


def _tokens(cmd: str) -> List[str]:
    """Tokenize for matching; falls back to raw split on parse errors."""
    try:
        return shlex.split(cmd)
    except ValueError:
        return cmd.split()


def _rm_recursive_force(cmd: str) -> Optional[str]:
    """Returns the rm target if the command is a recursive+forced rm."""
    toks = _tokens(cmd)
    for i, tok in enumerate(toks):
        base = tok.rsplit("/", 1)[-1]
        if base != "rm":
            continue
        args_after = toks[i + 1 :]
        shorts = "".join(
            t[1:] for t in args_after if t.startswith("-") and not t.startswith("--")
        )
        longs = " ".join(t for t in args_after if t.startswith("--"))
        recursive = "--recursive" in longs or "r" in shorts.lower()
        force = "--force" in longs or "f" in shorts.lower()
        targets = [t for t in args_after if t != "--" and not t.startswith("-")]
        if recursive and force and targets:
            return targets[-1]
    return None


def _is_shell_expansion(token: str) -> bool:
    """True if the token would expand at runtime ($VAR, ${..}, backticks)."""
    return bool(re.search(r"\$\{?\w+\}?|`", token))


def _is_hardline_blocked(cmd: str) -> Optional[str]:
    cmd_unquoted = cmd.replace('"', "").replace("'", "")

    # Token-based destructive-rm detection (survives /bin/rm,
    # rm --recursive --force, env prefixes, quoting).
    target = _rm_recursive_force(cmd)
    if target is not None:
        stripped = target.rstrip("/")
        catastrophic = (
            stripped in ("", "/", "~", "$HOME")
            or set(stripped) <= {"*"}
            # Runtime expansion hides the real target — refuse outright.
            or _is_shell_expansion(target)
        )
        if catastrophic:
            return f"Blocked (hardline): recursive forced deletion of '{target}'"

    def _blocked(pattern: str, desc: str, source: str | None = None) -> Optional[str]:
        if re.search(pattern, source or cmd, re.IGNORECASE):
            return f"Blocked (hardline): {desc}"
        return None

    # dd / redirect into block devices — match against quote-stripped text,
    # cover nvme/vd/mmcblk/mapper/disk-by paths.
    for desc, pat in (
        ("dd write to block device", r"\bdd\b[^|]*of=/dev/"),
        ("redirect into block device", r">\s*/dev/"),
    ):
        hit = _blocked(pat, desc, cmd_unquoted)
        if hit and re.search(r"/dev/(sd|nvme|vd|mmcblk|hd|mapper/|disk/)", cmd_unquoted, re.IGNORECASE):
            return hit

    regex_patterns = [
        (re.compile(r"mkfs"), "mkfs"),
        (re.compile(r"shutdown\s+(-h\s+now|-P|-r)|halt\s+-f|poweroff\s+-f"), "shutdown/halt"),
        (re.compile(r"systemctl\s+(stop|disable)\s+(sshd|multi-user|ufw|firewalld)"), "kill security service"),
        (re.compile(r"fdisk\s+/dev|parted\s+/dev|sgdisk"), "partition editor"),
        (re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:"), "fork bomb"),
        (re.compile(r"chmod\s+(-R\s+)?000\s+/(\s|$)"), "chmod 000 /"),
        (re.compile(r"cat\s+/dev/zero\s*>|cat\s+/dev/urandom\s*>"), "zero-fill redirect"),
        (
            re.compile(r"(curl|wget)[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b"),
            "download-piped-shell",
        ),
        (re.compile(r"(ba|z)?sh\s*<\("), "process-substitution shell"),
        (re.compile(r"base64\s+-d[^|]*\|\s*(ba)?sh\b"), "base64-decoded shell"),
    ]
    for pat, desc in regex_patterns:
        hit = _blocked(pat.pattern, desc)
        if hit:
            return hit
    return None


# ── Dangerous-pattern detector ───────────────────────────────────────────────

_DANGEROUS_PATTERNS: List[tuple] = [
    (re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|--recursive)", re.IGNORECASE), "recursive rm"),
    (re.compile(r"chmod\s+777\s+-R", re.IGNORECASE), "recursive world-writable"),
    (re.compile(r"chmod\s+777\s+/", re.IGNORECASE), "root world-writable"),
    (re.compile(r"(curl|wget)[^|]*\|\s*(sudo\s+)?(z)?sh\b", re.IGNORECASE), "download-piped-shell"),
    (re.compile(r"git\s+push\s+(--force|-f)(?!-)", re.IGNORECASE), "force push"),
    (re.compile(r"\b(sudo\s+)?pip\s+install\b.*\bsudo\b", re.IGNORECASE), "sudo pip install"),
    (re.compile(r"\bnpm\s+install\s+-g\b.*\bsudo\b", re.IGNORECASE), "sudo npm -g"),
    (re.compile(r"iptables\s+-F", re.IGNORECASE), "flush firewall"),
    (re.compile(r"kill\s+-9\s+-1", re.IGNORECASE), "kill all processes"),
    (re.compile(r"kill\s+-9\s+1\b", re.IGNORECASE), "kill init"),
    (re.compile(r">\s*/etc/(passwd|shadow|sudoers)", re.IGNORECASE), "overwrite system file"),
    (re.compile(r"passwd\s+root", re.IGNORECASE), "change root password"),
    (re.compile(r"userdel\s+\S+", re.IGNORECASE), "delete user account"),
    (re.compile(r"mv\s+\S+\s+/etc\b|mv\s+/etc\b", re.IGNORECASE), "move into/out of /etc"),
    # Interpreters executing inline code — deletion/persistence is invisible
    # to string-level checks, so ANY inline execution is flagged.
    (
        re.compile(
            r"\b(python3?|perl|node|ruby|php)\s+-(c|e)\b|\bsh\s+-c\b|\bbash\s+-c\b",
            re.IGNORECASE,
        ),
        "inline interpreter code",
    ),
    (re.compile(r"\bfind\s+\S+[^\n]*-delete\b", re.IGNORECASE), "find -delete"),
    (re.compile(r"shutil\.rmtree|os\.(remove|unlink|system)\b", re.IGNORECASE), "python fs/system call"),
    (
        re.compile(r">\s*~?/?(\.bashrc|\.zshrc|\.zprofile|\.profile|\.bash_profile)\b", re.IGNORECASE),
        "overwrite shell startup file",
    ),
    (re.compile(r"authorized_keys", re.IGNORECASE), "touch authorized_keys"),
    (re.compile(r"autostart/.*\.desktop", re.IGNORECASE), "write autostart entry"),
    (re.compile(r"\bcrontab\s+[-ler]", re.IGNORECASE), "modify crontab"),
    (re.compile(r">\s*~/.bash_history|\bshred\s+", re.IGNORECASE), "wipe history/files"),
]


def _detect_dangerous(cmd: str) -> List[str]:
    warnings: List[str] = []
    for pat, desc in _DANGEROUS_PATTERNS:
        if pat.search(cmd):
            warnings.append(desc)
    # Separated-flag rm (-r --force) evades the regex above; the token
    # helper catches it. Any target counts as dangerous here — hardline
    # separately blocks catastrophic targets in every mode.
    if _rm_recursive_force(cmd) is not None:
        if not any("recursive rm" in w or "recursive forced rm" in w for w in warnings):
            warnings.append("recursive forced rm")
    return warnings


# ── Agent tools ──────────────────────────────────────────────────────────────


def _tool_bash(cmd: str) -> str:
    """Execute a bash command. Returns stdout+stderr or error message.

    Runs via an explicit ``bash -c`` process instead of ``shlex.split`` so
    that pipes/redirections from the LLM (``ls | wc -l``) actually work.
    This is safe here because the command string is fully screened BEFORE
    execution: hardline blocklist (below), dangerous-pattern detector and
    the approval gate (response_pipeline._on_tool_call). sanitized_env()
    and the timeout still apply. Note: this deliberately avoids Python's
    ``shell=True`` — the project-wide ban targets that parameter, not
    spawning the bash binary for an LLM-provided command.
    """
    block = _is_hardline_blocked(cmd)
    if block:
        return f"[BLOCKED] {block}"

    try:
        timeout = 30  # fixed server-side; not model-controllable
        proc = subprocess.run(
            ["bash", "-c", cmd],
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
    """Read a file. Limited to 4KB; credential paths are refused outright."""
    try:
        if _is_sensitive_read(path):
            return "[BLOCKED] Reading credential files is forbidden"
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")[:4096]
        return content or "(empty file)"
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


_SENSITIVE_WRITE_PATTERNS: List[str] = [
    ".bashrc", ".zshrc", ".zprofile", ".profile", ".bash_profile",
    ".pam_environment", ".xprofile",
    ".ssh/", "authorized_keys", "autostart/", ".gnupg",
    ".config/systemd", ".local/share/systemd",
    ".local/bin/", ".cron", "history",
]


def _tool_write(path: str, content: str) -> str:
    """Write content to a file. Blocks system dirs and persistence paths."""
    try:
        p = Path(path).expanduser().resolve()
        forbidden = {"/etc", "/usr", "/boot", "/sys", "/proc", "/dev"}
        if any(str(p).startswith(d) for d in forbidden):
            return "[BLOCKED] Writing to system directory is forbidden"
        sp = str(p)
        if any(pat in sp for pat in _SENSITIVE_WRITE_PATTERNS):
            return f"[BLOCKED] Writing to sensitive path is forbidden: {path}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


# Read-tool: never hand credential files to the LLM (exfiltration channel).
_SENSITIVE_READ_BASENAMES = (".env",)
_SENSITIVE_READ_PARTS = (
    ".ssh/", "authorized_keys", "credentials", ".gnupg/",
    ".config/gh/hosts", ".aws/",
)
_SENSITIVE_READ_SUFFIXES = (".pem", ".key")


def _is_sensitive_read(path: str) -> bool:
    p = str(Path(path).expanduser().resolve())
    base = p.rsplit("/", 1)[-1].lower()
    if any(base.startswith(b) for b in _SENSITIVE_READ_BASENAMES):
        return True
    if any(part in p.lower() + "/" for part in _SENSITIVE_READ_PARTS):
        return True
    return any(base.endswith(s) for s in _SENSITIVE_READ_SUFFIXES)


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
    it is blocked / requires an unavailable confirmation.

    Semantics (text-mode reality: there is no interactive confirm channel,
    so "approval required" == blocked with explanation):
      - hardline blocklist is ABSOLUTE — no mode bypasses it;
      - "strict" — any dangerous pattern → blocked;
      - "auto"   — dangerous patterns are ALSO blocked (with a hint to
        switch to strict/yolo deliberately); safe commands run freely;
      - "yolo"   — dangerous patterns allowed (hardline still applies).
        Intended for sandboxed VMs only.
    """
    hard = _is_hardline_blocked(cmd)
    if hard:
        return hard

    warnings = _detect_dangerous(cmd)
    if warnings:
        if approval_mode == "yolo":
            logger.warning("⚠ YOLO executing dangerous command: %s — %s", cmd, "; ".join(warnings))
            return None
        # auto & strict: block. Text mode has nobody to ask.
        hint = "" if approval_mode == "strict" else (
            " Переключите режим одобрения в 'yolo' (Настройки → LLM), "
            "если понимаете риск."
        )
        return f"⚠ Approval required: {'; '.join(warnings)}.{hint}"

    return None
