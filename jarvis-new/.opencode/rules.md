## Project Context

This is JARVIS — a voice assistant for Linux/macOS running on CachyOS + Hyprland.

### Critical
- Python venv: `source venv/bin/activate` before any `python` or `pip` command
- GPU GTX 1050 (sm_61) is incompatible with current PyTorch — everything runs on CPU
- `audioop` removed in Python 3.14 — use `audioop-lts`
- Piper TTS lib_path is CachyOS-specific (/usr/share/steam/...)
- Real API keys are in `.env` and `SESSION.md` — never commit

### Commands
- Run: `cd ~/Projects/jarvis-py/jarvis-new && source venv/bin/activate && ollama serve &>/dev/null & jarvis run`
- Test: `make test` (after venv)
- Lint: `python -m pytest tests/ -v`
- Dry run: `jarvis run --dry-run`

### Priority
1. Working directory is `~/Projects/jarvis-py/jarvis-new`
2. GitHub mirror is `~/Projects/jarvis-py/jarvis-github`
3. Keep backward compatibility with config.yaml structure

### Key decisions
- Command pipeline order: exact → fuzzy → pattern → standalone app → voice cmd → LLM
- Platform adapter overrides commands.json
- microphone channels determined once at init
