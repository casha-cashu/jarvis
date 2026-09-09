"""
Tests for jarvis/modules/dictation.py (BACKEND-BUG-6).
"""

from unittest.mock import MagicMock, patch

from jarvis.modules.dictation import _type_text, dictation_loop


class TestTypeText:
    def test_type_text_returns_true_on_empty(self):
        assert _type_text("") is True
        assert _type_text("   ") is True

    def test_type_text_success_wayland(self, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert _type_text("hello") is True

    def test_type_text_failure_wayland_nonzero(self, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert _type_text("hello") is False

    def test_type_text_not_found_wayland(self, monkeypatch):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _type_text("hello") is False

    def test_type_text_success_x11(self, monkeypatch):
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert _type_text("hello") is True

    def test_type_text_failure_x11_nonzero(self, monkeypatch):
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert _type_text("hello") is False

    def test_type_text_not_found_x11(self, monkeypatch):
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _type_text("hello") is False


class TestDictationLoop:
    def test_dictation_loop_stops_on_stop_event(self):
        mock_stt = MagicMock()
        mock_stt.device_index = 0
        mock_stt.mic_sample_rate = 16000
        mock_stt.mic_channels = 1

        mock_stream = MagicMock()
        mock_stream.is_active.return_value = True

        mock_pa_inst = MagicMock()
        mock_pa_inst.open.return_value = mock_stream

        with (
            patch("pyaudio.PyAudio", return_value=mock_pa_inst),
            patch("jarvis.modules.vad.SileroVAD"),
            patch("jarvis.modules.vad.VADIteratorWrapper"),
        ):
            res = dictation_loop(mock_stt, stop_event=lambda: True)
            assert res == ""
            mock_stream.stop_stream.assert_called_once()
            mock_stream.close.assert_called_once()
            mock_pa_inst.terminate.assert_called_once()

    def test_dictation_loop_isolates_stop_stream_and_close(self):
        mock_stt = MagicMock()
        mock_stream = MagicMock()
        mock_stream.is_active.return_value = True
        mock_stream.stop_stream.side_effect = RuntimeError("stop stream failed")

        mock_pa_inst = MagicMock()
        mock_pa_inst.open.return_value = mock_stream

        with (
            patch("pyaudio.PyAudio", return_value=mock_pa_inst),
            patch("jarvis.modules.vad.SileroVAD"),
            patch("jarvis.modules.vad.VADIteratorWrapper"),
        ):
            res = dictation_loop(mock_stt, stop_event=lambda: True)
            assert res == ""
            mock_stream.close.assert_called_once()
            mock_pa_inst.terminate.assert_called_once()
