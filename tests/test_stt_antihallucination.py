"""Round 8: anti-hallucination для русского STT + RU-only ответы.

Контекст: Whisper tiny галлюцинирует на коротких русских фразах
("джарвис привет" → "Service hello"), а LLM зеркалит язык и отвечает
по-английски. Фикс: дефолт base + детерминированный декод + RU-словарь
в initial_prompt + жёсткое RU-правило в system_prompt шаблона.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


def _make_stt(**kwargs):
    """Hermetic WhisperSTT: мок модели и PyAudio, без железа и сети."""
    with (
        patch("faster_whisper.WhisperModel") as mock_wm,
        patch("jarvis.modules.stt_whisper.pyaudio.PyAudio"),
    ):
        mock_wm.return_value = MagicMock()
        from jarvis.modules.stt_whisper import WhisperSTT

        return WhisperSTT(use_vad=False, **kwargs)


class TestWhisperDefaults:
    def test_default_model_size_is_base(self):
        stt = _make_stt()
        assert stt.model_size == "base"

    def test_auto_model_size_resolves_to_base(self):
        stt = _make_stt(model_size="auto")
        assert stt.model_size == "base"

    def test_explicit_tiny_still_allowed(self):
        stt = _make_stt(model_size="tiny")
        assert stt.model_size == "tiny"

    def test_default_initial_prompt_has_russian_vocab(self):
        stt = _make_stt()
        prompt = stt.initial_prompt or ""
        for word in ("Джарвис", "привет", "включи", "выключи", "открой"):
            assert word in prompt, f"нет слова {word!r} в initial_prompt"


class TestDecodeParams:
    def test_antihallucination_defaults(self):
        stt = _make_stt()
        assert stt.temperature == 0.0
        assert stt.no_speech_threshold == 0.6
        assert stt.hallucination_silence_threshold == 2.0

    def test_decode_params_overridable(self):
        stt = _make_stt(temperature=0.2, no_speech_threshold=0.5)
        assert stt.temperature == 0.2
        assert stt.no_speech_threshold == 0.5

    def test_transcribe_passes_decode_params_to_model(self):
        import numpy as np

        stt = _make_stt()
        fake_seg = MagicMock()
        fake_seg.text = "привет"
        stt.model.transcribe.return_value = ([fake_seg], MagicMock())
        text = stt._transcribe_array(np.zeros(1600, dtype=np.float32))
        assert text == "привет"
        _, kwargs = stt.model.transcribe.call_args
        assert kwargs.get("language") == "ru"
        assert kwargs.get("temperature") == 0.0
        assert kwargs.get("no_speech_threshold") == 0.6
        assert kwargs.get("hallucination_silence_threshold") == 2.0


class TestPipelinePassthrough:
    def _start_with_whisper_cfg(self, whisper_cfg: dict):
        from unittest.mock import MagicMock, patch

        config = {
            "stt": {
                "engine": "whisper",
                "sample_rate": 16000,
                "whisper": whisper_cfg,
            },
            "vad": {"enabled": False},
            "audio": {"microphone": {}},
            "misc": {},
        }
        mock_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"jarvis.modules.stt_whisper": MagicMock(WhisperSTT=mock_cls)},
        ):
            from jarvis.audio_pipeline import AudioPipeline

            AudioPipeline(config, dry_run=False).start()
        return mock_cls

    def test_explicit_decode_keys_forwarded(self):
        mock_cls = self._start_with_whisper_cfg(
            {"model_size": "base", "temperature": 0.2}
        )
        _, kwargs = mock_cls.call_args
        assert kwargs.get("temperature") == 0.2
        assert kwargs.get("model_size") == "base"

    def test_absent_decode_keys_keep_legacy_call_shape(self):
        mock_cls = self._start_with_whisper_cfg({"model_size": "base"})
        _, kwargs = mock_cls.call_args
        assert "temperature" not in kwargs
        assert "no_speech_threshold" not in kwargs
        assert "hallucination_silence_threshold" not in kwargs


class TestWhisperSchema:
    def test_decode_fields_with_defaults(self):
        from jarvis.config_schema import WhisperConfig

        cfg = WhisperConfig()
        assert cfg.model_size == "base"
        assert cfg.temperature == 0.0
        assert cfg.no_speech_threshold == 0.6
        assert cfg.hallucination_silence_threshold == 2.0


class TestConfigExample:
    def test_whisper_base_and_ru_rule(self):
        example = Path(__file__).resolve().parent.parent / "config.example.yaml"
        cfg = yaml.safe_load(example.read_text(encoding="utf-8"))
        assert cfg["stt"]["whisper"]["model_size"] == "base"
        system_prompt = cfg["llm"]["system_prompt"]
        assert "русском" in system_prompt.lower()


class TestAdversarialAudio:
    """Ломаем вход: мусор вместо аудио не должен ронять движок."""

    def _silent_segments(self, stt, retval=([], MagicMock())):
        stt.model.transcribe.return_value = retval

    def test_empty_array_returns_empty_string(self):
        import numpy as np

        stt = _make_stt()
        self._silent_segments(stt)
        assert stt._transcribe_array(np.zeros(0, dtype=np.float32)) == ""

    def test_nan_array_does_not_raise(self):
        import numpy as np

        stt = _make_stt()
        self._silent_segments(stt)
        arr = np.full(1600, float("nan"), dtype=np.float32)
        assert isinstance(stt._transcribe_array(arr), str)

    def test_inf_array_does_not_raise(self):
        import numpy as np

        stt = _make_stt()
        self._silent_segments(stt)
        arr = np.full(1600, float("inf"), dtype=np.float32)
        assert isinstance(stt._transcribe_array(arr), str)

    def test_wrong_dtype_does_not_raise(self):
        import numpy as np

        stt = _make_stt()
        self._silent_segments(stt)
        assert isinstance(stt._transcribe_array(np.zeros(1600, dtype=np.int16)), str)

    def test_2d_array_does_not_raise(self):
        import numpy as np

        stt = _make_stt()
        self._silent_segments(stt)
        assert isinstance(
            stt._transcribe_array(np.zeros((2, 800), dtype=np.float32)), str
        )

    def test_huge_array_does_not_raise(self):
        import numpy as np

        stt = _make_stt()
        self._silent_segments(stt)
        assert isinstance(
            stt._transcribe_array(np.zeros(16000 * 60, dtype=np.float32)), str
        )

    def test_model_explosion_returns_empty_string(self):
        import numpy as np

        stt = _make_stt()
        stt.model.transcribe.side_effect = RuntimeError("CUDA OOM")
        assert stt._transcribe_array(np.zeros(1600, dtype=np.float32)) == ""

    def test_none_segments_returns_empty_string(self):
        import numpy as np

        stt = _make_stt()
        stt.model.transcribe.return_value = (None, MagicMock())
        assert stt._transcribe_array(np.zeros(1600, dtype=np.float32)) == ""

    def test_whitespace_segments_collapse_to_empty(self):
        import numpy as np

        stt = _make_stt()
        segs = [MagicMock(text="   "), MagicMock(text="\n\t ")]
        stt.model.transcribe.return_value = (segs, MagicMock())
        assert stt._transcribe_array(np.zeros(1600, dtype=np.float32)) == ""


class TestAdversarialConfig:
    """Ломаем конфиг: кривые типы и мусорные ключи."""

    def test_string_temperature_rejected(self):
        from pydantic import ValidationError

        from jarvis.config_schema import WhisperConfig

        with pytest.raises(ValidationError):
            WhisperConfig(temperature="high")  # type: ignore[arg-type]

    def test_unknown_key_rejected(self):
        from pydantic import ValidationError

        from jarvis.config_schema import WhisperConfig

        with pytest.raises(ValidationError):
            WhisperConfig(beam_size_hack=99)  # type: ignore[call-arg]

    def test_none_model_size_rejected(self):
        from pydantic import ValidationError

        from jarvis.config_schema import WhisperConfig

        with pytest.raises(ValidationError):
            WhisperConfig(model_size=None)  # type: ignore[arg-type]

    def test_none_initial_prompt_allowed(self):
        from jarvis.config_schema import WhisperConfig

        assert WhisperConfig(initial_prompt=None).initial_prompt is None

    def test_empty_initial_prompt_falls_back_to_default(self):
        stt = _make_stt(initial_prompt="")
        # Пустая строка — валидный явный ввод, движок хранит как есть,
        # faster-whisper трактует "" как отсутствие подсказки.
        assert stt.initial_prompt == ""


class TestAdversarialPipeline:
    """Ломаем сборку пайплайна: отсутствующие секции и мусор."""

    def _start(self, stt_cfg: dict):
        from unittest.mock import MagicMock, patch

        config = {
            "stt": {"engine": "whisper", "sample_rate": 16000, **stt_cfg},
            "vad": {"enabled": False},
            "audio": {"microphone": {}},
            "misc": {},
        }
        mock_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"jarvis.modules.stt_whisper": MagicMock(WhisperSTT=mock_cls)},
        ):
            from jarvis.audio_pipeline import AudioPipeline

            AudioPipeline(config, dry_run=False).start()
        return mock_cls

    def test_missing_whisper_section_uses_base_defaults(self):
        mock_cls = self._start({})
        _, kwargs = mock_cls.call_args
        assert kwargs.get("model_size") == "base"
        assert "temperature" not in kwargs

    def test_garbage_decode_key_ignored_not_forwarded(self):
        mock_cls = self._start({"model_size": "base", "temperature_typo": 0.5})
        _, kwargs = mock_cls.call_args
        assert "temperature_typo" not in kwargs
        assert "temperature" not in kwargs
