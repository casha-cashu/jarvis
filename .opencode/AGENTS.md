# JARVIS-PY Workspace — Agent Guide

## Overview

This workspace contains three trees of the same Russian-language voice assistant
project. See `jarvis-claude/CLAUDE.md` for the authoritative architecture
documentation.

| Dir | Role | Architecture | Git |
|---|---|---|---|
| `jarvis-claude/` | **active dev tree** | modular pipelines (post-refactor) | no |
| `jarvis-new/` | legacy dev tree | pre-P2 monolith | no |
| `jarvis-github/` | public GitHub mirror | matches `jarvis-claude` | yes (`main` branch) |

Active development: `jarvis-claude/`. Releases: mirror to `jarvis-github/`, commit/push/tag there.

## Thinking Protocol

Before executing any non-trivial action (file edit, bash command, code
generation), reason through the task in a `<thinking>` block:

1. What is the intent of the action?
2. What files are affected? Are there side effects?
3. What is the safest path to achieve the goal?
4. Are there existing patterns in the codebase to follow?

Do not skip this step for edits, deletions, or multi-step operations.

## Self-Healing Loop (max 3 attempts)

When editing code, follow this verification cycle:

```
Edit → Lint/Typecheck → Test → (fix if needed) → repeat max 3x
```

1. After each edit to `jarvis-claude/` or `jarvis-github/`, run:
   `cd jarvis-claude && source ../jarvis-new/venv/bin/activate`
   then `python -m pytest tests/ -m "not slow and not integration" -q --ignore=tests/integration`
2. If lint is available: `pre-commit run --files <changed_files>` (requires
   `pre-commit` installed; not in shared venv by default).
3. If tests fail, read the error, fix, and retry — up to 3 attempts.
4. After 3 failed attempts, stop and report the failure to the user.

## Guardrails

- **No full-file rewrites** unless explicitly requested. Use targeted edits.
- **No unverified dependencies.** Check `requirements.txt` / `pyproject.toml`
  before importing new libraries. If a package isn't installed, ask the user.
- **No `shell=True`** in any Python code (see `jarvis-claude/AGENTS.md`).
- **No API keys in `os.environ`** leaked to subprocesses. Use
  `sanitized_env()` from `jarvis/_env.py`.
- **No `SESSION.md` or real API keys committed** — they're gitignored.
- **No `rsync --delete`** from `jarvis-claude/` to `jarvis-github/` without
  excluding `.git`, `venv`, `.env`, `SESSION.md`, `__pycache__`, `*.pyc`,
  `.pytest_cache`, `.ruff_cache`, `*.joblib`.

## Commands

All work assumes you are inside `jarvis-claude/` (active dev) unless doing a
release (then `jarvis-github/`).

```bash
# Activate shared venv (lives in jarvis-new/)
source ../jarvis-new/venv/bin/activate

# Run unit tests (NEVER run without markers — integration tests open real devices)
python -m pytest tests/ -m "not slow and not integration" -q --ignore=tests/integration

# Single test file
python -m pytest tests/test_env.py -v

# Lint/format/types (requires pre-commit/ruff/mypy installed separately)
pre-commit run --all-files

# Run app (dry-run skips STT/TTS/VAD model loads)
jarvis run --dry-run
```

## MCP Servers

This workspace configures four MCP servers in `opencode.jsonc`:

- **Git** — `uvx mcp-server-git` on `jarvis-github/` repo. Read/search/operate
  on Git history.
- **Memory** — `@modelcontextprotocol/server-memory`. Knowledge graph for
  persistent agent memory across sessions. Stored at
  `docs/knowledge-base/memory.json`.
- **Filesystem** — `@modelcontextprotocol/server-filesystem`. Secure file
  access to workspace + knowledge base.
- **Obsidian** — `obsidian-mcp-server` on `docs/knowledge-base/` vault.
  Read/write/search notes.

## Knowledge Base

`docs/knowledge-base/` is an Obsidian-compatible vault:

- `adrs/` — Architecture Decision Records (one file per decision)
- `tech-stack/` — Core technology specs (Python, Vosk, Piper, Ollama, etc.)
- `decisions/` — Rationale for non-architectural choices
- `tasks/` — Dynamic task tracking ( ephemeral, not committed )
- `templates/` — Note templates (ADR, tech-stack, task)

## Skills

Project-specific skills live in `.opencode/skills/`:

| Skill | When to use |
|---|---|
| `stt-tts-pipeline` | Editing audio_pipeline.py, STT/TTS/VAD modules |
| `nlu-intent-classifier` | Editing nlu.py, intent routing, slot extraction |
| `bash-agent-safety` | Editing bash_agent.py, approval gate, tool execution |
| `adapter-pattern` | Creating/editing platform adapters (i3/sway/hyprland/kde/gnome/macos) |
| `llm-providers` | Editing LLM clients (Ollama/OpenAI/Anthropic/OpenRouter), chat_with_tools |
