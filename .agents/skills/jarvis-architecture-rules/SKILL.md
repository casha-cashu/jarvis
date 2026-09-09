---
name: jarvis-architecture-rules
description: >-
  Core architectural conventions, execution guidelines, security rules, and testing requirements for the JARVIS voice assistant repository.
  Use when modifying core architecture, adapters, audio pipeline, or configuration schemas.
---

# JARVIS Architecture & Engineering Rules

## 1. Repository Layout (Single Repo Root)

```
jarvis-py/                ← repo root
├── jarvis/               # Python package (backend)
│   ├── adapters/         # Platform adapters (i3, Sway, Hyprland, KDE, GNOME, macOS)
│   ├── modules/          # Core modules (nlu, bash_agent, llm, commands, vad, stt, tts, scenarios, reminder)
│   ├── audio_pipeline.py # Audio/VAD lifecycle
│   ├── response_pipeline.py # Commands -> LLM -> TTS
│   ├── conversation_manager.py # Wake word, mute, multi-turn state
│   ├── config_loader.py  # YAML loader + ${VAR} expansion + pydantic validation
│   ├── config_schema.py  # Pydantic models for configuration
│   ├── ui_bridge.py      # Stdin/stdout JSONL bridge to Tauri UI
│   └── _env.py           # sanitized_env() allowlist for subprocesses
├── tests/                # Hermetic pytest suite
├── jarvis-ui/            # Desktop GUI (Tauri 2 + React 19 + TypeScript + Vite)
│   ├── src-tauri/        # Rust bridge (spawns Python backend)
│   └── src/              # React frontend (tabs, components, hooks, api)
├── .agents/skills/       # Agent skills & runbooks
├── config.example.yaml   # Config template
└── AGENTS.md HANDOFF.md  # Agent instructions and session handoff state
```

---

## 2. Hard Security & Execution Rules

- **No `shell=True` Anywhere**:
  - Always split command strings via `shlex.split()`.
  - Pass command arguments as lists to `subprocess.run()` or `subprocess.Popen()`.
- **Environment Isolation (`sanitized_env`)**:
  - Every `subprocess.*` call MUST pass `env=sanitized_env()` from `jarvis._env`.
  - Never allow API keys (`OPENROUTER_API_KEY`, `KIRO_API_KEY`) to leak to child processes.
- **Process Timeouts**:
  - All command executions must have explicit timeouts (default 30s) followed by SIGTERM (2s grace) and SIGKILL.
  - Never spawn fire-and-forget `subprocess.Popen()` without tracking and cleanup.
- **Thread Safety**:
  - `ReminderManager.timers` and shared state must be protected by threading locks during mutation or iteration.
- **Testing Guardrails**:
  - NEVER execute bare `pytest` without markers. Always run:
    ```bash
    PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q
    ```
  - Audio and display hardware must be mocked in unit tests.

---

## 3. Fast Verification Commands

- **Backend tests**: `PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q`
- **Frontend tests**: `cd jarvis-ui && npm test -- --run`
- **Python Lint**: `./venv/bin/ruff check jarvis/ tests/`
- **Frontend Lint**: `cd jarvis-ui && npm run lint`
- **Rust check**: `cargo check --manifest-path jarvis-ui/src-tauri/Cargo.toml`
