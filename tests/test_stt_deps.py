"""Tests for PR-DEPS-1: Optional audio/STT deps do not crash import."""

from __future__ import annotations

import sys
from unittest.mock import patch
import pytest


class TestOptionalSTTDeps:
    def test_stt_import_succeeds_without_vosk_and_pyaudio(self, monkeypatch):
        with patch.dict(sys.modules, {"vosk": None, "pyaudio": None}):
            import importlib
            import jarvis.modules.stt as stt_mod

            importlib.reload(stt_mod)
            assert stt_mod.VoskSTT is not None

    def test_vosk_stt_raises_friendly_error_when_vosk_missing(self, monkeypatch):
        import jarvis.modules.stt as stt_mod

        monkeypatch.setattr(stt_mod, "Model", None)
        monkeypatch.setattr(stt_mod, "KaldiRecognizer", None)

        with pytest.raises(RuntimeError) as exc_info:
            stt_mod.VoskSTT(model_path="dummy")
        msg = str(exc_info.value)
        assert "Vosk is not installed" in msg
        assert "whisper" in msg.lower()

    def test_vosk_stt_raises_friendly_error_when_pyaudio_missing(self, monkeypatch):
        import jarvis.modules.stt as stt_mod

        monkeypatch.setattr(stt_mod, "Model", lambda p: None)
        monkeypatch.setattr(stt_mod, "KaldiRecognizer", lambda m, sr: None)
        monkeypatch.setattr(stt_mod, "pyaudio", None)

        with patch.object(
            stt_mod.VoskSTT, "_resolve_model_path", return_value="/tmp/dummy"
        ):
            with pytest.raises(RuntimeError) as exc_info:
                stt_mod.VoskSTT(model_path="/tmp/dummy")
            msg = str(exc_info.value)
            assert "PyAudio is not installed" in msg

    def test_whisper_stt_raises_friendly_error_when_pyaudio_missing(self, monkeypatch):
        import jarvis.modules.stt_whisper as whisper_mod

        monkeypatch.setattr(whisper_mod, "pyaudio", None)

        with pytest.raises(RuntimeError) as exc_info:
            whisper_mod.WhisperSTT(model_size="tiny")
        msg = str(exc_info.value)
        assert "PyAudio is not installed" in msg
