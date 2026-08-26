---
name: stt-tts-pipeline
description: "Use when editing audio_pipeline.py, stt.py, stt_whisper.py, tts.py, vad.py, or any audio/voice-related module. Covers STT/VAD/TTS lifecycle, dry_run mode, and Silero VAD integration."
---

# STT/TTS Pipeline Skill

## Architecture

Audio flows through a pipeline managed by `jarvis/audio_pipeline.py`:

```
Mic → PyAudio → Silero VAD → Vosk/faster-whisper STT → text
text → ResponsePipeline → LLM/Commands → response text
response text → Piper/gTTS/SpeechT5 TTS → speaker
```

## Key Files (jarvis-claude/)

- `jarvis/audio_pipeline.py` — STT/VAD lifecycle orchestrator. Skips model
  load when `dry_run=True`.
- `jarvis/modules/stt.py` — Vosk-based STT. Uses `vosk.Model` +
  `vosk.KaldiRecognizer`.
- `jarvis/modules/stt_whisper.py` — faster-whisper based STT (alternative).
- `jarvis/modules/tts.py` — TTS with Piper (offline), gTTS (online), SpeechT5.
- `jarvis/modules/vad.py` — Silero VAD wrapper for voice activity detection.

## Conventions

- **dry_run=True** skips all model loads. This is used in tests and
  `--dry-run` CLI mode. Always check this flag before instantiating models.
- **Python 3.13+ removed `audioop`**. The `audioop-lts` shim is in
  `requirements.txt`, gated on `python_version >= '3.13'`.
- **Vosk has no wheel on Python 3.13/3.14** — the shared venv in
  `jarvis-new/venv` has a hand-built `vosk 0.3.45` on Python 3.14. Do not
  expect `pip install vosk` to work on 3.14.
- All subprocess calls pass through `sanitized_env()` from `jarvis/_env.py`.
- STT/TTS/LLM are **eagerly imported** in `jarvis/__init__.py`. Tests stub
  them via `sys.modules.setdefault()` before import (see
  `tests/test_audio_modules.py`).

## Editing Checklist

1. Is `dry_run` handled? Model loads must be inside `if not dry_run:`.
2. Are all `subprocess.*` calls using `env=sanitized_env()`?
3. Are audio streams properly closed on shutdown (no zombie threads)?
4. If adding a new STT/TTS engine, register it in `config.yaml` under
   `stt.engine` / `tts.engine` with proper config block.
5. Are `ReminderManager.timers` mutations protected by `self._lock`?
