"""
Тесты PR-AUDIO-REC-1: автореконнект STT-потока при обрыве микрофона.

Полная изоляция от аудио-оборудования: FakeSTT вместо реальных движков,
пересоздание STT подменяется через monkeypatch метода start().
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from jarvis.audio_pipeline import AudioPipeline
from jarvis.modules.stt_base import BaseSTT


class FakeSTT:
    """Скриптованный STT: outcomes — значения или исключения по очереди."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []
        self.closed = 0
        self.level_cbs = []

    def recognize_from_mic(self, phrase_time_limit=10, callback=None, on_level=None):
        self.calls.append(
            {"phrase_time_limit": phrase_time_limit, "on_level": on_level}
        )
        if on_level is not None:
            self.level_cbs.append(on_level)
        if not self._outcomes:
            return ""
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self):
        self.closed += 1

    def list_devices(self):
        pass


def _pipeline(sample_config, fake, **kwargs):
    kwargs.setdefault("max_reconnect_attempts", 3)
    kwargs.setdefault("reconnect_base_delay", 0.1)
    kwargs.setdefault("reconnect_max_delay", 1.0)
    pipeline = AudioPipeline(sample_config, dry_run=False, **kwargs)
    pipeline.stt = fake
    pipeline._started = True
    return pipeline


class TestTransientFailureRecovers:
    def test_single_blip_recovers_and_returns_text(self, sample_config, monkeypatch):
        pipeline = _pipeline(sample_config, FakeSTT([OSError("ALSA stream dropped")]))
        replacement = FakeSTT(["привет"])

        def _fake_start():
            pipeline.stt = replacement
            pipeline._started = True

        monkeypatch.setattr(pipeline, "start", _fake_start)
        sleeps = []
        monkeypatch.setattr(pipeline, "_sleep", sleeps.append)

        res = pipeline.recognize(phrase_time_limit=5)

        assert res == "привет"
        assert pipeline.stream_healthy is True
        assert pipeline.consecutive_errors == 0
        # Успех с первой попытки — слипов нет (пауза только МЕЖДУ попытками)
        assert sleeps == []

    def test_empty_results_do_not_trigger_recovery(self, sample_config, monkeypatch):
        fake = FakeSTT(["", "", "есть речь"])
        pipeline = _pipeline(sample_config, fake)
        started = []
        monkeypatch.setattr(pipeline, "start", lambda: started.append(True))

        assert pipeline.recognize(phrase_time_limit=5) == ""
        assert pipeline.recognize(phrase_time_limit=5) == ""
        assert pipeline.recognize(phrase_time_limit=5) == "есть речь"
        assert started == []
        assert pipeline.consecutive_errors == 0
        assert pipeline.stream_healthy is True


class TestPersistentFailureDegradesGracefully:
    def test_exhausted_retries_return_none_without_crash(
        self, sample_config, monkeypatch
    ):
        pipeline = _pipeline(
            sample_config, FakeSTT([OSError("no mic"), OSError("no mic")])
        )
        starts = []
        stops = []

        def _fail_start():
            starts.append(True)
            raise RuntimeError("PortAudio: no default device")

        monkeypatch.setattr(pipeline, "start", _fail_start)
        orig_stop = pipeline.stop
        monkeypatch.setattr(pipeline, "stop", lambda: (stops.append(True), orig_stop()))
        sleeps = []
        monkeypatch.setattr(pipeline, "_sleep", sleeps.append)

        res = pipeline.recognize(phrase_time_limit=5)

        assert res is None
        assert pipeline.stream_healthy is False
        assert pipeline.last_error is not None
        assert len(starts) == 3  # max_reconnect_attempts
        # Паузы только МЕЖДУ попытками: после последней слипа нет
        assert sleeps == [pytest.approx(0.1), pytest.approx(0.2)]

    def test_backoff_capped_by_max_delay(self, sample_config, monkeypatch):
        pipeline = _pipeline(
            sample_config,
            FakeSTT([OSError("drop")]),
            max_reconnect_attempts=4,
            reconnect_base_delay=1.0,
            reconnect_max_delay=1.5,
        )
        monkeypatch.setattr(
            pipeline, "start", MagicMock(side_effect=RuntimeError("down"))
        )
        sleeps = []
        monkeypatch.setattr(pipeline, "_sleep", sleeps.append)

        assert pipeline.recognize(phrase_time_limit=5) is None
        assert sleeps == [pytest.approx(1.0), pytest.approx(1.5), pytest.approx(1.5)]

    def test_next_turn_retries_after_degraded(self, sample_config, monkeypatch):
        pipeline = _pipeline(sample_config, FakeSTT([OSError("drop")]))
        monkeypatch.setattr(
            pipeline, "start", lambda: (_ for _ in ()).throw(RuntimeError("down"))
        )
        monkeypatch.setattr(pipeline, "_sleep", lambda s: None)

        assert pipeline.recognize(phrase_time_limit=5) is None
        assert pipeline.stream_healthy is False

        # Микрофон вернулся: следующий вызов снова пробует и чинится
        replacement = FakeSTT(["снова слышу"])

        def _fake_start():
            pipeline.stt = replacement
            pipeline._started = True

        monkeypatch.setattr(pipeline, "start", _fake_start)
        assert pipeline.recognize(phrase_time_limit=5) == "снова слышу"
        assert pipeline.stream_healthy is True

    def test_dry_run_never_recovers(self, sample_config, monkeypatch):
        pipeline = AudioPipeline(sample_config, dry_run=True)
        pipeline.start()
        starts = []
        monkeypatch.setattr(pipeline, "start", lambda: starts.append(True))
        assert pipeline.recognize(phrase_time_limit=5) is None
        assert starts == []

    def test_unstarted_pipeline_without_stt_stays_quiet(
        self, sample_config, monkeypatch
    ):
        pipeline = AudioPipeline(sample_config, dry_run=False)
        starts = []
        monkeypatch.setattr(pipeline, "start", lambda: starts.append(True))
        assert pipeline.recognize(phrase_time_limit=5) is None
        assert starts == []


class TestLevelCallback:
    def test_on_level_forwarded_only_when_provided(self, sample_config):
        from unittest.mock import MagicMock

        pipeline = AudioPipeline(sample_config, dry_run=False)
        mock_stt = MagicMock()
        mock_stt.recognize_from_mic.return_value = "текст"
        pipeline.stt = mock_stt
        pipeline._started = True

        cb = MagicMock()
        pipeline.recognize(phrase_time_limit=7, on_partial=cb)
        mock_stt.recognize_from_mic.assert_called_once_with(
            phrase_time_limit=7, callback=cb
        )

        level_cb = MagicMock()
        pipeline.recognize(phrase_time_limit=7, on_partial=cb, on_level=level_cb)
        mock_stt.recognize_from_mic.assert_called_with(
            phrase_time_limit=7, callback=cb, on_level=level_cb
        )

    def test_engines_accept_on_level_kwarg(self):
        import jarvis.modules.stt as stt_mod
        import jarvis.modules.stt_whisper as whisper_mod

        for cls in (stt_mod.VoskSTT, whisper_mod.WhisperSTT):
            params = inspect.signature(cls.recognize_from_mic).parameters
            assert "on_level" in params, cls


class TestRmsLevel:
    def test_silence_is_zero(self):
        import numpy as np

        assert BaseSTT._rms_level(np.zeros(2048, dtype=np.float32)) == 0.0

    def test_empty_is_zero(self):
        import numpy as np

        assert BaseSTT._rms_level(np.zeros(0, dtype=np.float32)) == 0.0

    def test_full_scale_clamped(self):
        import numpy as np

        level = BaseSTT._rms_level(np.ones(2048, dtype=np.float32))
        assert level == pytest.approx(1.0)

    def test_sine_half_amplitude(self):
        import numpy as np

        t = np.arange(2048, dtype=np.float32)
        sine = 0.5 * np.sin(2 * np.pi * 440 * t / 16000).astype(np.float32)
        assert BaseSTT._rms_level(sine) == pytest.approx(0.5 / (2**0.5), rel=0.05)

    def test_within_unit_range(self):
        import numpy as np
        import math

        rng = np.random.default_rng(7)
        for _ in range(20):
            level = BaseSTT._rms_level(rng.uniform(-2.0, 2.0, 1024).astype(np.float32))
            assert 0.0 <= level <= 1.0
            assert not math.isnan(level)
