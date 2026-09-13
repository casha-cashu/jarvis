# JARVIS — agent guide

Russian voice assistant for Linux/macOS. DE/WM adapters (`i3`/`sway`/`hyprland`/`kde`/`gnome`/`macos`),
STT (Vosk / faster-whisper) + Silero VAD, commands-or-LLM routing (Ollama / OpenAI / Anthropic / OpenRouter), TTS (Piper / gTTS / SpeechT5).

## Layout

- `jarvis/` — Python backend (`cli.py` entry, `jarvis.cli:main`). `Jarvis` in `jarvis/__init__.py` is a thin orchestrator only.
- `jarvis/modules/` — `config_loader`, `audio_pipeline` (STT/VAD), `response_pipeline` (commands→LLM→TTS), `conversation_manager` (wake/mute/multi-turn), `lifecycle`, `nlu`, `bash_agent`, `commands`, `llm`, `reminder`, `dictation`, STT/TTS/VAD.
- `jarvis/adapters/` — one per platform. `jarvis/ui_bridge.py` — stdin/stdout JSON bridge spawned by the Tauri UI.
- `tests/` (+ `tests/integration/`), `data/commands.json` + `data/apps.json` (NLU training data), `docker/`, `jarvis-ui/` (Tauri 2 + React 19), `dist/arch/PKGBUILD`.
- `venv/` is the shared venv. `config.yaml` + `.env` are personal and gitignored (templates: `config.example.yaml`, `.env.example`). `HANDOFF.md` is gitignored session state — read it for in-progress context, never commit it.

## Commands (repo root)

- Unit tests: `PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q` (`make test` is the same with system `python3`; prefer the venv binary).
- Single test: `PYTHONPATH=. ./venv/bin/python -m pytest tests/test_env.py -v`.
- **Never run bare `pytest tests/`** — `tests/integration/` opens real audio/display devices and hangs. macOS CI uses the same `-m "not slow and not integration"` filter.
- Gate before done: `./venv/bin/ruff check jarvis/ tests/ && ./venv/bin/ruff format --check jarvis/ tests/ && ./venv/bin/python -m mypy jarvis/ && cargo check --manifest-path jarvis-ui/src-tauri/Cargo.toml` (mypy scope is `jarvis/` only — pre-commit excludes `tests/`/`venv/`/`build/`).
- Frontend: `cd jarvis-ui && npm run build` (tsc+vite) + `npm run lint` (oxlint) + `npm run test` (vitest).
- Docker unit tests (install everything; what CI runs): `make docker-test-arch` / `docker-test-debian` / `docker-test-fedora`.
- Docker integration: `make docker-integration-i3` (runs with `--cap-add=SYS_PTRACE --cap-add=SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined`) / `make docker-integration-sway` (needs `--privileged`).
- Run: `source venv/bin/activate && jarvis run`; `jarvis run --dry-run` skips STT/TTS/VAD model loads. `jarvis doctor` dumps env/config/audio/models/LLM state — ask for its output when debugging user reports. GUI dev: `cd jarvis-ui && npm run tauri dev`.

## Architecture

- `config_loader.py` — YAML load + `${VAR}` expansion (missing var → warning + empty string) + pydantic validation (`config_schema.py`).
- `audio_pipeline.py` — STT/VAD lifecycle; `dry_run=True` skips model loads.
- `response_pipeline.py` — commands → LLM → TTS routing. `conversation_manager.py` — wake word, mute, multi-turn. `lifecycle.py` — SIGINT/SIGTERM + ordered shutdown.
- `modules/nlu.py` — `IntentRouter.parse()` → `{raw, intent, intent_confidence, slots}`; TF-IDF + LogisticRegression trained at startup from `data/*.json`, cacheable via `JARVIS_NLU_CACHE` (cache dir `0700`, files `0600`). Old fuzzy/pattern path in `commands.py` is fallback only.
- `modules/bash_agent.py` — LLM automation with 3 layers: hardline blocklist → dangerous-pattern detector → approval gate (`auto`/`strict`/`yolo`). Tools `bash`/`read`/`write` (write blocks `/etc` `/usr` `/boot` `/sys` `/proc` `/dev`).
- `modules/llm.py` — all providers share one history file (`HISTORY_FILE`, default `~/.local/share/jarvis/history.json`, override `JARVIS_HISTORY_FILE`), clamped to `llm.max_history`; `clear_history()` is atomic temp+rename. `LLMClient` is `ABC` with abstract `chat()` — never instantiate raw.
- `modules/commands.py` — `CommandExecutor._run`: `cmd` may be a string or a **callable returning str** (evaluated at execute time); blocks for `commands.execution_timeout` (default 30s), then SIGTERM → SIGKILL after 2s grace.

## Hard rules

- **No `shell=True`** in `jarvis/`. Adapter command strings go through `shlex.split` + `subprocess.*(env=sanitized_env())`.
- **Every `subprocess.*` passes `env=sanitized_env()`** (`jarvis/_env.py` allowlist). API keys flow as kwargs via `config.yaml` → `provider_config` → `LLMManager`; never put them in `os.environ` (`cli_helpers` must not write there either).
- **CI: never swallow the tested command's exit code** (`|| true`, `set +e`, pipes without `pipefail`, skip-on-empty are for cleanup/best-effort daemons only). Any binary used by tests/entrypoints must be installed in that image. macOS `test.yml` needs `set -o pipefail` before `pytest … | tail`.
- **Docker: manifests before sources** — `COPY pyproject/requirements` + install first, then `COPY . .`; torch always CPU (`--index-url …/whl/cpu`), PyPI default pulls a CUDA bundle.
- Never commit secrets or session state: `.env`, `config.yaml`, `SESSION.md`, `HANDOFF.md` are gitignored — keep them that way.

## Python / test gotchas

- `requires-python >=3.10`; sweet spot 3.10–3.12 (macOS CI pins 3.11). `vosk` wheels exist only for ≤3.12 — install via `pip install -e ".[vosk]"`; on 3.13+ STT falls back to whisper and `audioop-lts` shim kicks in (`python_version >= '3.13'`). This repo's venv happens to have a working `vosk 0.3.45` on 3.14 — new venvs should not expect that.
- Importing `jarvis` needs heavy deps (`sklearn`/`anthropic` imported at module level in `nlu.py`/`llm.py`). Without them, either use Docker or stub before import (pattern in `tests/test_audio_modules.py`: `sys.modules.setdefault(n, ModuleType(n))` for `vosk torch faster_whisper silero_vad pyaudio audioop numpy anthropic requests gtts yaml`).
- Markers (`pyproject.toml`): `slow`, `integration`, `i3`, `sway`, `x11`, `wayland`, `ollama`, `llm`.
- `tests/conftest.py` isolates every test via `JARVIS_DATA_DIR` / `JARVIS_HISTORY_FILE` / `JARVIS_NLU_CACHE` / `JARVIS_CONFIG_PATH` (points at `config.test.yaml`) and patches `llm.HISTORY_FILE` / `nlu.CACHE_DIR`. `jarvis_instance` fixture patches `Jarvis._load_config` — keep that method a thin hook. `check_sanitized_env` fixture asserts no secret leaks into subprocess env.

## Editing pitfalls

- Time-sensitive / interactive commands (timestamps, `slurp` geometry): pass the **method reference** as `cmd`, never the call result — `_run` invokes callables at execute time (see screenshot commands in `commands.py`).
- Screenshots: `i3`/`gnome`/`macos`/`sway` adapters resolve `~` + `datetime.now()` in Python; `kde` (spectacle) and `hyprland` (grimblast) own their naming — leave those alone.
- `ReminderManager.timers` is touched from multiple threads — hold `self._lock` around append/iterate/clear.
- `adapters/base.py::input_text` picks `wtype` (Wayland) vs `xdotool type` (X11) by session — never a `||` fallback chain (`_run` splits via shlex, so shell operators would become literal argv). Live dictation bypasses it (`modules/dictation.py::_type_text` pipes raw text to `wtype -`); adapter tests pin `input_text` output, so update them together.
- LLM default provider is `ollama` (local, no keys; allowed: `ollama`/`openai`/`openrouter`/`anthropic` per `config_schema.py` — Kiro was removed). API keys (`${OPENAI_API_KEY}`, `${ANTHROPIC_API_KEY}`, `${OPENROUTER_API_KEY}`) expand via `config_loader`, never `os.environ`.
- `lifecycle.py` must tolerate `signal.signal` raising `(ValueError, OSError)` when called off-main-thread (`telegram_bot`, `ui_bridge`).

## Release (all versions move together)

- Bump together: `pyproject.toml` + `jarvis-ui/package.json` + `jarvis-ui/src-tauri/tauri.conf.json` + `jarvis-ui/src-tauri/Cargo.toml` + `dist/arch/PKGBUILD` (currently all `2.8.0`). Tag and push from root: `git push origin main --tags`. `release.yml` (on `v*`) builds the PyInstaller sidecar + deb/rpm/AppImage on ubuntu-22.04 (portable glibc — Arch's is too new) and dmg on macOS; Arch pkg is a local repack (`cd dist/arch && makepkg -f`).
- **Every release also bumps the site**: versions appear as both `vX.Y.Z` and `X.Y.Z` in `docs/` (`*.html`/`*.txt`/`*.js`, excluding `docs/site/`) plus `FALLBACK_VERSION` in `site/lib/github-release.ts` and the `buildFallback()` version in `site/lib/use-release.ts`, then commit `docs/ site/`.

## Skills

Domain workflows live in `.opencode/skills/` + `.agents/skills/` (`opencode.jsonc: skills.paths`). Load via the `skill` tool when the task matches: `jarvis-architecture-rules` (repo conventions — load first for arch changes), `adapter-pattern` (platform adapters), `bash-agent-safety` (tool execution/approval), `stt-tts-pipeline` (audio), `nlu-intent-classifier`, `llm-providers`, `prompt-builder`, plus `systematic-debugging`, `tdd-regression`, `technical-reviewer`, `verification-before-completion`, `subagent-orchestration`.
