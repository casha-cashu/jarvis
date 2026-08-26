"""TTS-очередь и отмена озвучки: TTSWorker, ResponsePipeline speech-control,
ConversationManager.mute и связка «тихо» → cancel в Jarvis.

Реального аудио нет: движки — фейки, subprocess — моки.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from jarvis.modules.tts import TTSWorker


class FakeEngine:
    """Фейковый TTS-движок: пишет фразы, умеет блокироваться."""

    def __init__(self):
        self.spoken = []
        self.lock = threading.Lock()
        self.gate = threading.Event()
        self.release = threading.Event()

    def speak(self, text):
        with self.lock:
            self.spoken.append(text)
        if self.gate.is_set():
            self.release.wait(timeout=5)
        return True


def _wait_until(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


class FakeProc:
    """Фейковый Popen: «висит», пока его не terminate/kill."""

    def __init__(self, rc=0, hang=False):
        self.rc = rc
        self.hang = hang
        self.terminated = False
        self.killed = False
        self.cmd = None
        self.returncode = None

    def poll(self):
        if self.hang and not (self.terminated or self.killed):
            return None
        if self.killed:
            self.returncode = -9
        elif self.terminated:
            self.returncode = -15
        else:
            self.returncode = self.rc
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.poll()


class TestTTSWorkerQueue:
    def test_speak_noop_without_engine(self):
        w = TTSWorker(None)
        assert w.speak("привет") is False
        assert not w.busy
        assert w.pending == 0
        w.close(timeout=2)

    def test_empty_text_not_enqueued(self):
        eng = FakeEngine()
        w = TTSWorker(eng)
        assert w.speak("") is False
        assert w.speak("   ") is False
        assert w.pending == 0
        w.close(timeout=2)

    def test_fifo_order(self):
        eng = FakeEngine()
        w = TTSWorker(eng)
        for t in ("один", "два", "три"):
            assert w.speak(t) is True
        assert w.wait_idle(timeout=5)
        assert eng.spoken == ["один", "два", "три"]
        w.close(timeout=2)

    def test_close_rejects_new_phrases(self):
        eng = FakeEngine()
        w = TTSWorker(eng)
        w.close(timeout=2)
        assert w.speak("после закрытия") is False


class TestTTSWorkerCancel:
    def test_cancel_clears_queue_but_keeps_current(self):
        eng = FakeEngine()
        eng.gate.set()  # первая фраза «застрянет» в speak
        w = TTSWorker(eng)
        try:
            w.speak("текущая")
            assert _wait_until(lambda: w.busy)
            w.speak("лишняя-1")
            w.speak("лишняя-2")

            dropped = w.cancel()

            assert dropped == 2
            assert w.pending == 0
        finally:
            eng.release.set()
        assert w.wait_idle(timeout=5)
        assert eng.spoken == ["текущая"]

        # После отмены новые фразы должны проигрываться (событие сброшено)
        assert w.speak("новая") is True
        assert w.wait_idle(timeout=5)
        assert eng.spoken == ["текущая", "новая"]
        w.close(timeout=2)

    def test_cancel_with_empty_queue_is_safe(self):
        eng = FakeEngine()
        w = TTSWorker(eng)
        assert w.cancel() == 0
        w.close(timeout=2)


class TestPlaybackCancellation:
    @pytest.fixture(autouse=True)
    def _reset_cancel_event(self):
        from jarvis.modules import tts as tts_mod

        tts_mod._reset_playback_cancel()
        yield
        tts_mod._reset_playback_cancel()

    def _patch_subprocess(self, monkeypatch, popen_impl):
        from jarvis.modules import tts as tts_mod

        fake_subprocess = MagicMock()
        fake_subprocess.Popen.side_effect = popen_impl
        # TimeoutExpired нужен _stop_proc через except-пути
        fake_subprocess.TimeoutExpired = tts_mod.subprocess.TimeoutExpired
        monkeypatch.setattr(tts_mod, "subprocess", fake_subprocess)
        return tts_mod

    def test_play_audio_first_player_success(self, monkeypatch):
        procs = []
        tts_mod = self._patch_subprocess(
            monkeypatch,
            lambda cmd, **kw: procs.append(FakeProc(rc=0)) or procs[-1],
        )
        assert tts_mod._play_audio_file("/tmp/fake.wav") is True
        assert len(procs) == 1

    def test_play_audio_falls_through_on_failure(self, monkeypatch):
        procs = []

        def popen(cmd, **kw):
            # первый плеер «ломается», второй работает
            p = FakeProc(rc=0 if procs else 1)
            procs.append(p)
            return p

        tts_mod = self._patch_subprocess(monkeypatch, popen)
        assert tts_mod._play_audio_file("/tmp/fake.wav") is True
        assert len(procs) == 2  # mpv не сработал → ffplay

    def test_play_audio_no_players(self, monkeypatch):
        def no_player(cmd, **kw):
            raise FileNotFoundError(cmd[0])

        tts_mod = self._patch_subprocess(monkeypatch, no_player)
        assert tts_mod._play_audio_file("/tmp/fake.wav") is False

    def test_cancel_kills_active_player_without_next_fallback(self, monkeypatch):
        procs = []

        def popen(cmd, **kw):
            # только первый плеер «зависает», последующие играют нормально
            p = FakeProc(rc=0, hang=len(procs) == 0)
            procs.append(p)
            return p

        tts_mod = self._patch_subprocess(monkeypatch, popen)

        result = {}
        th = threading.Thread(
            target=lambda: result.update(r=tts_mod._play_audio_file("/tmp/fake.wav")),
            daemon=True,
        )
        th.start()
        assert _wait_until(lambda: len(tts_mod._active_players) == 1)

        killed = tts_mod.cancel_playback()
        th.join(timeout=2)

        assert result["r"] is False
        assert killed == 1
        assert procs[0].terminated
        # Цепочка fallback-плееров после отмены НЕ продолжается
        assert len(procs) == 1
        assert not tts_mod._active_players

        # Новая фраза после сброса отмены играет как обычно
        tts_mod._reset_playback_cancel()
        assert tts_mod._play_audio_file("/tmp/fake.wav") is True
        assert len(procs) == 2

    def test_worker_cancel_terminates_engine_players(self, monkeypatch):
        """Сквозной путь: TTSWorker.cancel() глушит плеер текущей фразы."""
        procs = []
        tts_mod = self._patch_subprocess(
            monkeypatch,
            lambda cmd, **kw: procs.append(FakeProc(rc=0, hang=True)) or procs[-1],
        )

        class PlayingEngine:
            def speak(self, text):
                return tts_mod._play_audio_file("/tmp/fake.wav")

        w = TTSWorker(PlayingEngine())
        try:
            w.speak("длинная фраза")
            assert _wait_until(lambda: len(tts_mod._active_players) == 1)
            dropped = w.cancel()
            assert dropped == 0
            assert _wait_until(lambda: not tts_mod._active_players)
            assert procs[0].terminated
        finally:
            tts_mod._reset_playback_cancel()
            w.close(timeout=2)


class TestResponsePipelineSpeechControl:
    def _pipeline(self):
        from jarvis.response_pipeline import ResponsePipeline

        return ResponsePipeline({})

    def test_speak_routes_to_worker(self, capsys):
        p = self._pipeline()
        worker = MagicMock()
        p.tts_worker = worker
        p.speak("тест")
        worker.speak.assert_called_once_with("тест")

    def test_speak_noop_without_tts(self, capsys):
        p = self._pipeline()
        p.speak("тишина")  # не должно падать
        assert p.tts is None
        assert p.tts_worker is None

    def test_cancel_and_wait_delegate_to_worker(self):
        p = self._pipeline()
        worker = MagicMock()
        p.tts_worker = worker
        p.cancel_speech()
        worker.cancel.assert_called_once()
        p.wait_for_speech(timeout=1)
        worker.wait_idle.assert_called_once_with(1)

    def test_wait_for_speech_true_without_worker(self):
        assert self._pipeline().wait_for_speech() is True

    def test_start_wraps_manager_into_worker(self):
        with (
            patch("jarvis.modules.tts.TTSManager") as mock_mgr,
            patch("jarvis.modules.llm.LLMManager"),
            patch("jarvis.modules.commands.CommandManager"),
            patch("jarvis.modules.platform_adapter.PlatformAdapter"),
        ):
            p = self._pipeline()
            p.start()
            try:
                assert p.tts_worker is not None
                assert p.tts_worker.tts is p.tts
                assert mock_mgr.called
            finally:
                p.stop()

    def test_injected_worker_survives_start(self):
        injected = MagicMock()
        with (
            patch("jarvis.modules.tts.TTSManager"),
            patch("jarvis.modules.llm.LLMManager"),
            patch("jarvis.modules.commands.CommandManager"),
            patch("jarvis.modules.platform_adapter.PlatformAdapter"),
        ):
            p = self._pipeline()
            p.tts_worker = injected
            p.start()
            try:
                assert p.tts_worker is injected
            finally:
                p.stop()


class TestConversationMute:
    def test_mute_sets_flag_and_calls_callback(self):
        from jarvis.conversation_manager import ConversationManager

        calls = []
        cm = ConversationManager(
            wake_words=["джарвис"], on_mute=lambda: calls.append(1)
        )
        assert not cm.is_muted
        cm.mute()
        assert cm.is_muted
        assert calls == [1]

    def test_mute_without_callback(self):
        from jarvis.conversation_manager import ConversationManager

        cm = ConversationManager(wake_words=["джарвис"])
        cm.mute()
        assert cm.is_muted

    def test_mute_callback_exception_swallowed(self):
        from jarvis.conversation_manager import ConversationManager

        def boom():
            raise RuntimeError("cancel failed")

        cm = ConversationManager(wake_words=["джарвис"], on_mute=boom)
        cm.mute()
        assert cm.is_muted


class TestJarvisSpeechControlIntegration:
    def test_process_special_mute_cancels_worker(self, jarvis_instance):
        j = jarvis_instance
        worker = MagicMock()
        j.response.tts_worker = worker
        j.commands = MagicMock()
        j.commands.executor.parse_voice_command.return_value = "__MUTE__"

        out = j._process_special("тихо")

        assert out
        assert j.conversation.is_muted is True
        assert j.is_muted is True
        worker.cancel.assert_called_once()

    def test_dictation_receives_stop_phrase_check(self, jarvis_instance):
        j = jarvis_instance
        j.commands = MagicMock()
        j.commands.executor.parse_voice_command.return_value = "__DICTATE__"
        j.stt = MagicMock()

        with patch("jarvis.modules.dictation.dictation_loop") as dl:
            dl.return_value = ""
            out = j._process_special("диктуй")
            assert out
            assert dl.call_args.kwargs.get("stop_phrase_check") is not None

        checker = dl.call_args.kwargs["stop_phrase_check"]
        assert checker("стоп диктовку") is True
        assert checker("Закончить диктовку") is True
        assert checker("стоп диктовку пожалуйста") is True
        assert checker("привет мир") is False
        assert checker("") is False

    def test_recognize_waits_for_speech_to_finish(self, jarvis_instance):
        j = jarvis_instance
        j.response.tts_worker = MagicMock()
        j.audio.recognize = MagicMock(return_value="ok")
        assert j._recognize(5) == "ok"
        j.response.tts_worker.wait_idle.assert_called_once()
