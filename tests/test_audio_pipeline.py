"""
Тесты для jarvis.audio_pipeline.AudioPipeline.
Полная изоляция от аудио-оборудования (никакого открытия микрофона/ALSA/PulseAudio).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from jarvis.audio_pipeline import AudioPipeline


class TestAudioPipelineInit:
    def test_init_defaults(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=False)
        assert pipeline.config == sample_config
        assert pipeline.dry_run is False
        assert pipeline.stt is None
        assert pipeline._started is False

    def test_init_dry_run(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=True)
        assert pipeline.dry_run is True


class TestAudioPipelineStart:
    def test_start_dry_run_skips_model_load(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=True)
        pipeline.start()
        assert pipeline._started is True
        assert pipeline.stt is None

    def test_start_idempotent(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=True)
        pipeline.start()
        assert pipeline._started is True

        # Повторный вызов не должен ничего делать
        pipeline.start()
        assert pipeline._started is True

    def test_start_vosk_success(self, sample_config):
        mock_vosk_cls = MagicMock()
        mock_vosk_inst = MagicMock()
        mock_vosk_cls.return_value = mock_vosk_inst

        with patch.dict(
            "sys.modules", {"jarvis.modules.stt": MagicMock(VoskSTT=mock_vosk_cls)}
        ):
            pipeline = AudioPipeline(sample_config, dry_run=False)
            pipeline.start()

            assert pipeline._started is True
            assert pipeline.stt is mock_vosk_inst
            mock_vosk_inst.list_devices.assert_called_once()
            mock_vosk_cls.assert_called_once_with(
                model_path="/tmp/test-vosk",
                sample_rate=16000,
                device_name=None,
                use_vad=False,
                vad_threshold=0.5,
                silence_threshold=None,
            )

    def test_start_vosk_import_error_raises_runtime_error(self, sample_config):
        with patch.dict("sys.modules", {"jarvis.modules.stt": None}):
            # При попытке импорта VoskSTT возникнет ImportError
            with patch(
                "builtins.__import__", side_effect=ImportError("No module named 'vosk'")
            ):
                pipeline = AudioPipeline(sample_config, dry_run=False)
                with pytest.raises(RuntimeError, match="Движок STT 'vosk' выбран"):
                    pipeline.start()

    def test_start_whisper_success(self, sample_config):
        whisper_config = dict(sample_config)
        whisper_config["stt"] = dict(sample_config["stt"])
        whisper_config["stt"]["engine"] = "whisper"
        whisper_config["stt"]["whisper"] = {
            "model_size": "base",
            "model_path": "/tmp/whisper-model",
            "partial_interval_ms": 500,
        }
        whisper_config["vad"] = {"enabled": True, "silero": {"threshold": 0.6}}
        whisper_config["audio"] = {"microphone": {"device_name": "USB Mic"}}

        mock_whisper_cls = MagicMock()
        mock_whisper_inst = MagicMock()
        mock_whisper_cls.return_value = mock_whisper_inst

        with patch.dict(
            "sys.modules",
            {"jarvis.modules.stt_whisper": MagicMock(WhisperSTT=mock_whisper_cls)},
        ):
            pipeline = AudioPipeline(whisper_config, dry_run=False)
            pipeline.start()

            assert pipeline._started is True
            assert pipeline.stt is mock_whisper_inst
            mock_whisper_inst.list_devices.assert_called_once()
            mock_whisper_cls.assert_called_once_with(
                model_size="base",
                model_path="/tmp/whisper-model",
                sample_rate=16000,
                device_name="USB Mic",
                use_vad=True,
                vad_threshold=0.6,
                partial_interval_ms=500,
                silence_threshold=None,
            )


class TestAudioPipelineRecognize:
    def test_recognize_dry_run_returns_none(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=True)
        pipeline.start()
        res = pipeline.recognize(phrase_time_limit=5)
        assert res is None

    def test_recognize_no_stt_returns_none(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=False)
        # stt is None
        res = pipeline.recognize(phrase_time_limit=5)
        assert res is None

    def test_recognize_delegates_to_stt(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=False)
        mock_stt = MagicMock()
        mock_stt.recognize_from_mic.return_value = "тестовая фраза"
        pipeline.stt = mock_stt
        pipeline._started = True

        partial_cb = MagicMock()
        res = pipeline.recognize(phrase_time_limit=7, on_partial=partial_cb)

        assert res == "тестовая фраза"
        mock_stt.recognize_from_mic.assert_called_once_with(
            phrase_time_limit=7,
            callback=partial_cb,
        )

    def test_recognize_handles_exception_gracefully(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=False)
        mock_stt = MagicMock()
        mock_stt.recognize_from_mic.side_effect = IOError("ALSA device busy")
        pipeline.stt = mock_stt
        pipeline._started = True

        # Не должно вызывать падение процесса
        res = pipeline.recognize(phrase_time_limit=5)
        assert res is None


class TestAudioPipelineStop:
    def test_stop_closes_stt_and_resets_flag(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=False)
        mock_stt = MagicMock()
        pipeline.stt = mock_stt
        pipeline._started = True

        pipeline.stop()
        assert pipeline._started is False
        assert pipeline.stt is None
        mock_stt.close.assert_called_once()

    def test_stop_handles_stt_close_exception(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=False)
        mock_stt = MagicMock()
        mock_stt.close.side_effect = RuntimeError("PortAudio error on close")
        pipeline.stt = mock_stt
        pipeline._started = True

        pipeline.stop()
        assert pipeline._started is False
        assert pipeline.stt is None

    def test_stop_when_no_stt(self, sample_config):
        pipeline = AudioPipeline(sample_config, dry_run=True)
        pipeline.start()
        pipeline.stop()
        assert pipeline._started is False
        assert pipeline.stt is None


def test_jarvis_stt_property(sample_config):
    from jarvis import Jarvis

    j = Jarvis(config_path="config.example.yaml", dry_run=True)
    assert j.stt is None
    mock_stt = MagicMock()
    j.audio.stt = mock_stt
    assert j.stt is mock_stt
    j.stt = None
    assert j.audio.stt is None
