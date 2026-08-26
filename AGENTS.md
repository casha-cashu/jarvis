# JARVIS — agent guide

Russian-language voice assistant for Linux/macOS. Detects DE/WM (i3 / Sway /
Hyprland / KDE / GNOME / macOS), transcribes (Vosk / faster-whisper) with
Silero VAD, routes to commands or LLM (Ollama / Kiro / Anthropic /
OpenRouter), speaks back via TTS (Piper / gTTS / SpeechT5).

## Workspace layout (single repo since v2.5.0+)

One repository = one working directory:

```
jarvis-py/                ← repo root (git remote → casha-cashu/jarvis)
├── jarvis/               # Python package (backend)
├── tests/                # pytest suite
├── data/ docker/ docs?   # assets & infra
├── jarvis-ui/            # GUI (Tauri 2 + React 19 + TS)
│   └── src-tauri/        # Rust bridge (spawn ./venv/bin/python)
├── venv/                 # shared venv (Python 3.14, relocated from jarvis-new)
├── config.yaml           # personal, gitignored (template: config.example.yaml)
├── .env                  # secrets, gitignored
└── AGENTS.md HANDOFF.md  # agent instructions / state (HANDOFF gitignored)
```

- Run backend tests: `PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q`
- GUI dev: `cd jarvis-ui && npm run tauri dev` (Rust bridge spawns `./venv/bin/python jarvis/ui_bridge.py`)
- Lint/types: ruff + mypy installed in venv; gate before done:
  `./venv/bin/ruff check jarvis/ tests/ && ./venv/bin/ruff format --check jarvis/ui_bridge.py`
- Release = plain `git push origin main --tags` from root (no more mirror sync).
- Old dirs `jarvis-claude/ jarvis-new/ jarvis-github/` are DELETED; history
  lives in this single .git.

## Architecture (new / `jarvis-claude` & `jarvis-github`)

`Jarvis` (`jarvis/__init__.py`, ~374 lines) is a thin orchestrator. Real work
lives in:

- `jarvis/config_loader.py` — yaml load + `${VAR}` expansion (warns on
  missing) + pydantic validation
- `jarvis/audio_pipeline.py` — STT/VAD lifecycle, skips model load when
  `dry_run=True`
- `jarvis/response_pipeline.py` — commands → LLM → TTS routing
- `jarvis/conversation_manager.py` — wake word, mute, multi-turn state
- `jarvis/lifecycle.py` — SIGINT/SIGTERM + ordered shutdown
- `jarvis/_env.py` — `sanitized_env()` allowlist for all subprocess calls
- `jarvis/modules/nlu.py` — **NLU**: TF-IDF + LogisticRegression intent
  classifier (trained at startup from `data/commands.json` + `data/apps.json`,
  cacheable via `JARVIS_NLU_CACHE`) + regex slot extractor
  (`app` / `search` / `workspace` / `volume_amount`). `IntentRouter.parse()`
  returns `{raw, intent, intent_confidence, slots}`. Replaces steps 2–3
  (fuzzy/pattern) of the old CommandExecutor pipeline; old path kept as
  fallback. **Depends on `scikit-learn`** (installed in shared venv).
- `jarvis/modules/bash_agent.py` — **LLM-driven automation** with 3-layer
  approval: hardline blocklist (`rm -rf /`, `mkfs`, `dd of=/dev/`, fork
  bombs, etc.) → dangerous-pattern detector (~20 patterns: `curl|sh`,
  `git push -f`, `iptables -F`, `kill -9 -1`, etc.) → approval gate
  (`auto` / `strict` / `yolo`). Tools: `bash` / `read` / `write` (write
  blocks `/etc`, `/usr`, `/boot`, `/sys`, `/proc`, `/dev`). All commands
  pass through `sanitized_env()` and `subprocess.run(timeout=...)`.
- `jarvis/modules/` — STT (`stt.py`, `stt_whisper.py`), TTS (`tts.py`),
  VAD (`vad.py`), LLM (`llm.py`), commands (`commands.py`), reminders,
  dictation
- `jarvis/adapters/` — one per platform: `i3`, `sway`, `hyprland`, `kde`,
  `gnome`, `macos`

`Jarvis._load_config` is kept as a thin delegating method because
`tests/conftest.py` patches it.

## Hard rules

- **No `shell=True`** anywhere in `jarvis/`. Adapter command strings go
  through `shlex.split` and `subprocess.Popen(env=sanitized_env())`. If a
  command needs runtime expansion (timestamp, slurp geometry), pass a
  callable as `cmd` — `CommandExecutor._run` invokes it.
- **No API keys in `os.environ` leaks to subprocesses.** API keys flow as
  kwargs into LLM clients via `config.yaml` → `provider_config` →
  `LLMManager`. `cli_helpers` must NOT write to `os.environ`.
- **Every `subprocess.*` call passes `env=sanitized_env()`** (from
  `jarvis/_env.py`).
- **`SESSION.md` and real API keys never get committed** — they are in
  `.gitignore`; keep it that way.

## Commands

All commands assume you are **inside** the package dir (`jarvis-claude/` for
day-to-day work; `jarvis-github/` only for releases) — there is no top-level
venv at the workspace root.

- Activate the shared venv first (one-time; it lives in `jarvis-new/`):
  `source ../jarvis-new/venv/bin/activate`
- Tests: `make test` (== `python -m pytest tests/ -v`). Needs full deps
  installed in the venv — they are in `jarvis-new/venv` already.
- Coverage: `make test-cov`.
- Lint/format/types: `pre-commit run --all-files` — ruff + ruff-format +
  mypy (mypy excludes `venv/`, `build/`, `tests/`; rules in
  `.pre-commit-config.yaml`). NOTE: `pre-commit` / `ruff` / `mypy` are
  **not** installed in the shared venv — `pip install pre-commit ruff mypy`
  before first run, or run in Docker.
- Single test: `python -m pytest tests/test_env.py -v`; single marker:
  `python -m pytest -m "not slow and not integration"`.
- **Don't run `pytest tests/` without markers** — `tests/integration/`
  opens real audio/display devices and will hang. Always combine with
  `-m "not slow and not integration"` for unit suites.
- Docker unit tests (CI uses these; install everything): `make docker-test-arch`
  / `docker-test-debian` / `docker-test-fedora`.
- Integration: `make docker-integration-i3` / `docker-integration-sway` —
  Sway needs `--privileged`, i3 uses `--cap-add=SYS_PTRACE --security-opt
  seccomp=unconfined`.
- Run app: `jarvis run` (after venv active). App run is meaningful anywhere
  with the venv; the `.env` with real API keys now lives in `jarvis-claude/`
  (copied from `jarvis-new/`). App model loads are skipped with `--dry-run`.
- Dry run: `jarvis run --dry-run` — skips STT/TTS/VAD model loads.

There is no `opencode.json` at the workspace root. Per-package OpenCode
config lives in `jarvis-new/.opencode/` only (and points at the OLD tree).

## Python / test gotchas

- Python 3.10–3.12 is the sweet spot. On 3.13/3.14: no `vosk` wheel; `pyaudio`
  needs `brew install portaudio` (macOS); `audioop` removed (`audioop-lts`
  shim in `requirements.txt` / `pyproject.toml`, gated on
  `python_version >= '3.13'`).
  - **Exception**: the `jarvis-new/venv` was hand-built and does have working
    `vosk 0.3.45` on Python 3.14. Tests pass there (verified 622 passed,
    2 skipped). New venvs on 3.14 should not expect vosk to install from PyPI.
- `jarvis/__init__.py` **eagerly imports STT/TTS/LLM at module load**, so a
  bare interpreter missing those deps will fail to import. On the shared
    `jarvis-new/venv` (where full deps are installed) this is not an issue.
  Outside that venv, two ways past it:
  1. Use Docker (`make docker-test-arch` etc.) — CI relies on these and they
     install everything.
  2. Stub heavy deps before import — pattern used in
     `tests/test_audio_modules.py`:

     ```python
     import sys, types
     for n in ['vosk','torch','faster_whisper','silero_vad','pyaudio',
               'audioop','numpy','anthropic','requests','gtts','yaml']:
         sys.modules.setdefault(n, types.ModuleType(n))
     ```
- Integration tests are marked `integration`, `i3`, `sway`, `x11`, `wayland`;
  slow tests are marked `slow`. See `pyproject.toml [tool.pytest.ini_options]`.
- `tests/conftest.py` patches `Jarvis._load_config` and references a
  `config.test.yaml` at the package root — keep that fixture updated if you
  move config files.
- `clang`-style markers exist; CI macOS job runs `-m "not slow"`.

## Pitfalls when editing

- `_add_platform_commands` builds the command table at `__init__` time. For
  time-sensitive commands (timestamps, interactive geometry via `slurp`),
  pass the **method reference** (not the call result) — `_run` invokes
  callable values at execute time.
- Screenshot adapters: `i3.py`, `gnome.py`, `macos.py`, `sway.py` resolve
  `~` and `datetime.now()` in Python. `kde.py` and `hyprland.py` use tools
  (spectacle / grimblast) that own their own naming — leave those alone.
- `ReminderManager.timers` is mutated from multiple threads. Take
  `self._lock` around any `append` / iteration / clear.
- **LLM history persists to `~/.local/share/jarvis/history.json`** via
  `jarvis/modules/llm.HISTORY_FILE` (overridable via `JARVIS_HISTORY_FILE`
  env var). All LLM clients (Kiro/Anthropic/OpenRouter/Ollama) share one
  file, so switching providers preserves the conversation. History clamps
  to `max_history` per `config.yaml::llm.max_history`. `clear_history()`
  writes back an empty list atomically (temp+rename).
- `input_text` in `base.py` still uses shell-style `wtype || xdotool` in its
  returned string; effectively dead (live dictation goes through
  `jarvis/modules/dictation.py:_type_text`). Two adapter tests assert its
  return type — watch them if you touch it.
- LLM default `provider: ollama` (local, no keys). Kiro key comes from
  `${KIRO_API_KEY}` env var; OpenRouter from `${OPENROUTER_API_KEY}`.
  Missing env var → warning + empty substitution (see `config_loader.py`).
- **`CommandExecutor._run` blocks for `commands.execution_timeout`** (sec,
  default 30) then sends SIGTERM (2s grace) → SIGKILL. Previously it was
  fire-and-forget `Popen` which leaked zombies on interactive commands.
- The `LLMClient` base class is now `ABC` — `chat()` is `@abstractmethod`.
  Subclasses must override it. Don't try to instantiate `LLMClient` raw.

## Release / sync flow

Mirror `jarvis-claude/` → `jarvis-github/` (excluding `venv`, `.env`,
`SESSION.md`), bump version in `pyproject.toml`, then `git add/commit/push/tag`
inside `jarvis-github/`. `jarvis-github/` is the only tree with a `.git` dir
(`main` branch, remote `git@github.com:casha-cashu/jarvis.git`).

⚠ **`rsync --delete` from `jarvis-claude/` to `jarvis-github/` destroys
`.git`** — always exclude `.git` (e.g. `rsync -av --delete --exclude='.git'
--exclude='venv' --exclude='.env' --exclude='SESSION.md' jarvis-claude/
jarvis-github/`) or re-init after sync.

Push uses HTTPS + `GITHUB_TOKEN` (set in user's `~/.zshenv`), not SSH:

```
git -c credential.helper='!f() { echo "username=casha-cashu"; \
  echo "password=$GITHUB_TOKEN"; }; f' push origin main --tags
```

GitHub Release (not just the tag) is created via the API:

```
curl -sS -X POST -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/casha-cashu/jarvis/releases \
  -d '{"tag_name":"vX.Y.Z","name":"vX.Y.Z","body":"...","draft":false,"prerelease":false}'
```

Releases so far: **v2.1.0** (config cleanup, execution_timeout, persist LLM
history, ABC refactor), **v2.2.0** (NLU intent classifier + bash-agent with
approval gate). Legacy `Claude-0001` branch was in the old lost repo; current
repo starts fresh at v2.1.0.
