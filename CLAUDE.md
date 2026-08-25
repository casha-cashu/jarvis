# JARVIS — Claude context

Russian-language voice assistant for Linux/macOS. Detects desktop env
(i3 / Sway / Hyprland / KDE / GNOME / macOS), listens via microphone,
transcribes (Vosk or faster-whisper), routes to commands or LLM
(Ollama / OpenAI / Anthropic / OpenRouter), speaks back (Piper / gTTS /
SpeechT5).

## Architecture (post P2 refactor)

`Jarvis` (`jarvis/__init__.py`) is a thin orchestrator. Real work lives in:

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
  (`app` / `search` / `workspace` / `volume_amount`).
  `IntentRouter.parse()` returns `{raw, intent, intent_confidence, slots}`.
  Replaces steps 2–3 (fuzzy/pattern) of the old CommandExecutor pipeline; old
  path kept as fallback. **Depends on `scikit-learn`** (installed in shared venv).
- `jarvis/modules/bash_agent.py` — **LLM-driven automation** with 3-layer
  approval: hardline blocklist (`rm -rf /`, `mkfs`, `dd of=/dev/`, fork
  bombs, etc.) → dangerous-pattern detector (~20 patterns: `curl|sh`,
  `git push -f`, `iptables -F`, `kill -9 -1`, etc.) → approval gate
  (`auto` / `strict` / `yolo`). Tools: `bash` / `read` / `write` (write
  blocks `/etc`, `/usr`, `/boot`, `/sys`, `/proc`, `/dev`). All commands
  pass through `sanitized_env()` and `subprocess.run(timeout=...)`.

`Jarvis._load_config` is kept as a thin delegating method because
`tests/conftest.py` patches it.

## Hard rules

- **No `shell=True`** anywhere in `jarvis/`. Adapter command strings go
  through `shlex.split` and `subprocess.Popen(env=sanitized_env())`. If
  a command needs runtime expansion (timestamp, slurp geometry), pass
  a callable as `cmd` — `CommandExecutor._run` invokes it.
- **No API keys in `os.environ`.** API keys flow as kwargs into LLM
  clients via `config.yaml` → `provider_config` → `LLMManager`. `cli_helpers`
  must NOT write to `os.environ`.
- **Every `subprocess.*` call passes `env=sanitized_env()`.** Verified by
  the script in the P0+P1 commit; CI / pre-commit should re-check.

## Test infrastructure caveats

Python 3.10–3.12 is the sweet spot. Local Python 3.14 has:
- no `vosk` wheel,
- `pyaudio` needs `brew install portaudio` first,
- `audioop` removed (`audioop-lts` shim is in `requirements.txt` already).

Because `jarvis/__init__.py` eagerly imports STT/TTS/LLM, you can't
`pytest tests/` on a bare 3.14. Options:

1. Use Docker: `make docker-test-arch` (or `debian`, `fedora`). CI relies
   on these and they install everything.
2. Stub heavy deps before import — pattern used in `tests/test_audio_modules.py`
   and the standalone smoke tests during the P0–P18 sweep:

   ```python
   import sys, types
   for n in ['vosk','torch','faster_whisper','silero_vad','pyaudio',
             'audioop','numpy','anthropic','requests','gtts','yaml']:
       sys.modules.setdefault(n, types.ModuleType(n))
   ```

## Running things

- Tests: `make test` (needs a venv with full deps, see above)
- Coverage: `make test-cov`
- Lint/format: `pre-commit run --all-files` (ruff + ruff-format + mypy +
  whitespace; rules in `.pre-commit-config.yaml`)
- Integration: `make docker-integration-i3` / `docker-integration-sway`
  (Sway needs `--privileged`)

## Known deferred work

- **P10**: each adapter still duplicates the command-string scaffolding for
  6 method families. Acknowledged tech debt; flagged for a future PR. Don't
  do it implicitly during unrelated work — it touches 6 adapter files and
  has subtle behavior implications.
- **`input_text` in `base.py`** still uses shell-style `wtype || xdotool`
  fallback in its returned string. It's effectively dead — the live dictation
  path is `jarvis/modules/dictation.py:_type_text`, which dispatches in
  Python. When `input_text` finally gets rewritten or deleted, watch the
  two adapter tests that assert its return type.

## Common pitfalls when editing

- `_add_platform_commands` builds the command table at `__init__` time.
  For anything time-sensitive (timestamps, interactive geometry), pass the
  **method reference** (not the call result) — `_run` invokes callable
  values at execute time.
- The adapter screenshot methods in `i3.py`, `gnome.py`, `macos.py`,
  `sway.py` resolve `~` and `datetime.now()` in Python. `kde.py` and
  `hyprland.py` use tools (spectacle / grimblast) that own their own
  naming — leave those alone.
- `ReminderManager.timers` is mutated from multiple threads. Take
  `self._lock` around any `append` / iteration / clear.
- **LLM history persists to `~/.local/share/jarvis/history.json`**
  (`jarvis/modules/llm.HISTORY_FILE`, overridable via `JARVIS_HISTORY_FILE`).
  All LLM clients share one file — switching providers preserves the
  conversation. `clear_history()` writes back empty atomically.
- **`CommandExecutor._run` blocks** for `commands.execution_timeout` (sec,
  default 30) then SIGTERM (2s grace) → SIGKILL. Don't add `_run` calls
  expecting fire-and-forget — use explicit `proc.detach()` pattern if you
  genuinely need async (today, none do).
- `LLMClient` is `ABC` — `chat()` is `@abstractmethod`. Subclasses must
  override it.
- Dead config keys (`cleanup_temp_on_start`, `sound_notifications`,
  `misc.gui`, `hyprland.enabled`) were **removed** in favour of
  implementing only the ones actually used (see `config_schema.py`). Don't
  re-add them without also wiring up the code path.
