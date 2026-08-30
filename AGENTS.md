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
├── venv/                 # shared venv (Python 3.14)
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

## Architecture

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

- **CI/infra: код возврата тестируемого не глотается.** `|| true`,
  `set +e`, пайпы без `pipefail`, skip-on-empty — только для cleanup,
  best-effort демонов и косметики. Команда, которую CI проверяет,
  обязана ронять джобу. Любой бинарь, вызываемый тестами/энтрипоинтами,
  должен быть установлен в соответствующем образе (класс бага: pgrep/
  pactl/xrandr отсутствовали в контейнерах, а `--timeout` — в deps).
- **docker: зависимости до исходников.** Сначала копируются манифесты
  зависимостей и ставятся пакеты, потом `COPY . .` — иначе любой чих
  репо перекачивает torch. CPU-сборка torch (--index-url
  .../whl/cpu) во всех образах: PyPI тянет CUDA-бандл.

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

All commands assume you are at the **repo root** (`jarvis-py/`) — it is the
single working directory; the shared venv lives at `venv/` there.

- Tests: `PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q`
  (or `make test` — same thing).
- Coverage: `make test-cov`.
- Lint/format/types (the pre-commit gate): `./venv/bin/ruff check jarvis/ tests/ &&
  ./venv/bin/ruff format --check jarvis/ tests/ && ./venv/bin/python -m mypy jarvis/ &&
  cargo check --manifest-path jarvis-ui/src-tauri/Cargo.toml` (run python/mypy
  with `env -u APPIMAGE -u ARGV0 -u APPDIR` when invoked from ZCode's shell).
- **Don't run `pytest tests/` without markers** — `tests/integration/`
  opens real audio/display devices and will hang. Always combine with
  `-m "not slow and not integration"` for unit suites (`make test` already
  does; bare `pytest tests/` is the hang trap).
- Single test: `./venv/bin/python -m pytest tests/test_env.py -v`.
- Docker unit tests (CI uses these; install everything): `make docker-test-arch`
  / `docker-test-debian` / `docker-test-fedora`. NOTE: docker bridge network
  has no internet on this machine — `docker run --network host`.
- Integration: `make docker-integration-i3` / `docker-integration-sway` —
  Sway needs `--privileged`, i3 uses `--cap-add=SYS_PTRACE --security-opt
  seccomp=unconfined`.
- Run app: `source venv/bin/activate && jarvis run`. Dry run:
  `jarvis run --dry-run` — skips STT/TTS/VAD model loads.
- GUI dev: `cd jarvis-ui && npm run tauri dev`; frontend gates:
  `npm run build` (tsc+vite) and `npm run lint` (oxlint).
- Packages: `npx tauri build --bundles deb,rpm,appimage` (from jarvis-ui,
  needs ubuntu-22.04 for portable glibc — locally Arch glibc is newer),
  Arch pkg: `cd dist/arch && makepkg -f` (repacks the deb).

## Python / test gotchas

- Python 3.10–3.12 is the sweet spot. On 3.13/3.14: no `vosk` wheel; `pyaudio`
  needs `brew install portaudio` (macOS); `audioop` removed (`audioop-lts`
  shim in `requirements.txt` / `pyproject.toml`, gated on
  `python_version >= '3.13'`).
  - On Python 3.14 this repo's venv has a working `vosk 0.3.45`; new venvs
    on 3.14 should not expect vosk to install from PyPI.
- `jarvis` package import pulls heavy deps transitively (STT/TTS/sklearn
  import lazily inside `start()`/factories, but `jarvis.modules.nlu` and
  `jarvis.modules.llm` import `sklearn`/`anthropic` at module level), so a
  bare interpreter missing them will fail. Two ways past it:
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

## Release / sync flow (single repo — no mirrors since v2.5.0)

1. Bump the version in **one place per side**: `pyproject.toml` +
   `jarvis-ui/src-tauri/tauri.conf.json` (+ `Cargo.toml`/`package.json`)
   + `dist/arch/PKGBUILD` — these must stay equal (as of v2.6.2 they are).
2. Commit, tag `vX.Y.Z`, push: `git push origin main --tags` from the repo
   root (HTTPS + `GITHUB_TOKEN` in `~/.zshenv`).
3. `release.yml` (on `v*` tags) builds the PyInstaller sidecar + deb/rpm/
   AppImage on ubuntu-22.04 and a dmg on macOS; artifacts are attached
   manually to the GitHub Release (workflow only uploads run artifacts).
4. Arch pkg is repacked locally: `cd dist/arch && makepkg -f`
   (workflow skips it on ubuntu).

Releases so far: v2.1.0 → v2.6.2. Since v2.6.2 python/UI versions are a
single scheme (2.6.2 everywhere).
