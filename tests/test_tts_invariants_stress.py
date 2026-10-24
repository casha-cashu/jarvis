"""Adversarial stress test suite for TTS Invariant Preservation (Requirement R4).

Verifies that under NO circumstance do <think>...</think> tokens reach speech output,
audio queue, or synthesizer across ResponsePipeline, TTSWorker, TTSManager, and PiperTTS.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
from unittest.mock import MagicMock, patch
import pytest

from jarvis.modules.tts import (
    PiperTTS,
    TTSManager,
    TTSWorker,
    _strip_thinking,
)
from jarvis.prompt_builder import (
    strip_thinking_tags,
)
from jarvis.response_pipeline import ResponsePipeline


# =====================================================================
# 1. Regex & String Level Tag Stripping Invariants
# =====================================================================
class TestThinkingTagRegexInvariants:
    @pytest.mark.parametrize(
        "tag_input,expected_clean",
        [
            ("<think>simple thought</think>Hello world", "Hello world"),
            ("<THINK>all caps</THINK>Hello world", "Hello world"),
            ("<Think>capitalized</Think>Hello world", "Hello world"),
            ("<tHiNk>mixed case</tHiNk>Hello world", "Hello world"),
            (
                "<think type='internal' id='42'>\nmultiline\nthought\n</think>Hello world",
                "Hello world",
            ),
            (
                '<think\n  type="internal"\n  priority="high"\n>\nline 1\nline 2\n</think>Hello world',
                "Hello world",
            ),
            ("<think>unclosed thoughts at end", ""),
            ("Prefix <think>unclosed thoughts at end", "Prefix"),
            (
                "<think>thought 1</think> middle <think>thought 2</think> end",
                "middle  end",
            ),
            ("<<think>>double angle bracket</think>>Hello", "<>Hello"),
        ],
    )
    def test_strip_thinking_tags_pb(self, tag_input: str, expected_clean: str):
        assert strip_thinking_tags(tag_input) == expected_clean

    @pytest.mark.parametrize(
        "tag_input,expected_clean",
        [
            ("<think>simple thought</think>Hello world", "Hello world"),
            ("<THINK>all caps</THINK>Hello world", "Hello world"),
            ("<Think>capitalized</Think>Hello world", "Hello world"),
            ("<tHiNk>mixed case</tHiNk>Hello world", "Hello world"),
            (
                "<think type='internal' id='42'>\nmultiline\nthought\n</think>Hello world",
                "Hello world",
            ),
            ("<think>unclosed thoughts at end", ""),
            ("Prefix <think>unclosed thoughts at end", "Prefix"),
            (
                "<think>thought 1</think> middle <think>thought 2</think> end",
                "middle  end",
            ),
        ],
    )
    def test_strip_thinking_tts(self, tag_input: str, expected_clean: str):
        assert _strip_thinking(tag_input) == expected_clean

    def test_nested_adjacent_think_tags(self):
        """<think><think>inner</think></think>Clean answer."""
        text = "<think><think>inner</think></think>Clean answer"
        assert strip_thinking_tags(text) == "Clean answer"
        assert _strip_thinking(text) == "Clean answer"

    def test_nested_think_tags_with_intermediate_content_leaks(self):
        """Adversarial case: content between nested closing tags.
        Iterative stripping ensures nested tags and intermediate reasoning content
        are completely eradicated without leaking into clean answer.
        """
        text = (
            "<think>outer start <think>nested</think> outer end </think> Clean answer"
        )
        pb_res = strip_thinking_tags(text)
        tts_res = _strip_thinking(text)
        assert pb_res == "Clean answer"
        assert tts_res == "Clean answer"
        assert "outer end" not in pb_res
        assert "outer end" not in tts_res

    def test_orphaned_close_tags_pb_vs_tts(self):
        """Adversarial check: orphaned closing tags with whitespace."""
        # Standard closing tag
        assert strip_thinking_tags("</think>Clean") == "Clean"
        assert _strip_thinking("</think>Clean") == "Clean"

        # Tag with space after slash: </ think>
        assert strip_thinking_tags("</ think>Clean") == "Clean"
        assert _strip_thinking("</ think>Clean") == "Clean"

        # Tag with space before slash: < /think>
        # Both prompt_builder and tts.py use r"<\s*/\s*think\s*>" -> handles space before slash
        assert strip_thinking_tags("< /think>Clean") == "Clean"
        assert _strip_thinking("< /think>Clean") == "Clean"


# =====================================================================
# 2. ResponsePipeline.speak Invariant & Exception Safety
# =====================================================================
class TestResponsePipelineSpeakInvariants:
    def test_speak_clean_response_dispatched(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        pipeline.speak("Привет, сэр.")
        mock_worker.speak.assert_called_once_with("Привет, сэр.")

    def test_speak_strips_thinking_tags(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        pipeline.speak("<think>секретные рассуждения</think>Привет, сэр.")
        mock_worker.speak.assert_called_once_with("Привет, сэр.")

    def test_speak_silent_when_only_thinking(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        pipeline.speak("<think>только мысли и ничего больше</think>")
        mock_worker.speak.assert_not_called()

    def test_speak_silent_when_unclosed_thinking(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        pipeline.speak("<think>бесконечные размышления без закрывающего тега")
        mock_worker.speak.assert_not_called()

    def test_speak_strips_multiline_attributed_thinking(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        pipeline.speak(
            '<think type="internal" id="42">\nСтрока 1\nСтрока 2\n</think>Ответ готов.'
        )
        mock_worker.speak.assert_called_once_with("Ответ готов.")

    def test_speak_strips_case_variations(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        pipeline.speak("<THINK>ALL CAPS</THINK>Ответ капсом.")
        mock_worker.speak.assert_called_once_with("Ответ капсом.")

        mock_worker.reset_mock()
        pipeline.speak("<tHiNk>mIxEd CaSe</tHiNk>Ответ смешанный.")
        mock_worker.speak.assert_called_once_with("Ответ смешанный.")

    def test_speak_exception_in_sanitize_for_tts_still_strips_thinking(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        with patch(
            "jarvis.prompt_builder.sanitize_for_tts",
            side_effect=RuntimeError("Sanitize failure"),
        ):
            pipeline.speak("<think>рассуждения</think>Ответ после ошибки санитайзинга")
        mock_worker.speak.assert_called_once_with("Ответ после ошибки санитайзинга")

    def test_speak_exception_in_redact_secrets_still_strips_thinking(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        with patch(
            "jarvis.prompt_builder.redact_secrets",
            side_effect=ValueError("Redact failure"),
        ):
            pipeline.speak(
                "<think>секреты в мыслях</think>Ответ после ошибки маскирования"
            )
        mock_worker.speak.assert_called_once_with("Ответ после ошибки маскирования")

    def test_speak_exception_in_sanitize_when_only_thinking_stays_silent(self):
        mock_worker = MagicMock()
        pipeline = ResponsePipeline({"llm": {}}, tts_worker=mock_worker)
        with patch(
            "jarvis.prompt_builder.sanitize_for_tts",
            side_effect=RuntimeError("Sanitize failure"),
        ):
            pipeline.speak("<think>только мысли</think>")
        mock_worker.speak.assert_not_called()


# =====================================================================
# 3. TTSWorker Invariants
# =====================================================================
class TestTTSWorkerInvariants:
    def test_tts_worker_speak_strips_thinking_before_enqueue(self):
        mock_engine = MagicMock()
        worker = TTSWorker(mock_engine)
        try:
            res = worker.speak("<think>скрытые мысли</think>Озвучь меня")
            assert res is True
            time.sleep(0.05)
            mock_engine.speak.assert_called_once_with("Озвучь меня")
        finally:
            worker.close()

    def test_tts_worker_speak_only_thinking_not_enqueued(self):
        mock_engine = MagicMock()
        worker = TTSWorker(mock_engine)
        try:
            res = worker.speak("<think>только мысли</think>")
            assert res is False
            time.sleep(0.05)
            mock_engine.speak.assert_not_called()
            assert worker.pending == 0
        finally:
            worker.close()

    def test_tts_worker_speak_unclosed_thinking_not_enqueued(self):
        mock_engine = MagicMock()
        worker = TTSWorker(mock_engine)
        try:
            res = worker.speak("<think>мысли без закрытия")
            assert res is False
            time.sleep(0.05)
            mock_engine.speak.assert_not_called()
            assert worker.pending == 0
        finally:
            worker.close()

    def test_tts_worker_speak_space_orphan_tag_leak(self):
        """Adversarial check: direct call to TTSWorker with '< /think>'."""
        mock_engine = MagicMock()
        worker = TTSWorker(mock_engine)
        try:
            worker.speak("< /think>Озвучь меня")
            time.sleep(0.05)
            # Due to _ORPHAN_THINK_CLOSE_RE in tts.py, '< /think>' is stripped before passing to engine
            call_arg = mock_engine.speak.call_args[0][0]
            assert call_arg == "Озвучь меня", (
                "Invariant preserved: < /think> stripped before reaching engine"
            )
        finally:
            worker.close()


# =====================================================================
# 4. TTSManager Invariants
# =====================================================================
class TestTTSManagerInvariants:
    def test_tts_manager_speak_strips_thinking_tags(self):
        cfg = {"engine": "piper", "piper": {}, "gtts": {}}
        mgr = TTSManager(cfg)
        mock_primary = MagicMock()
        mgr.primary = mock_primary

        res = mgr.speak("<think>планирование ответа</think>Чистый ответ")
        assert res is True
        mock_primary.speak.assert_called_once_with("Чистый ответ")

    def test_tts_manager_speak_only_thinking_returns_false(self):
        cfg = {"engine": "piper", "piper": {}, "gtts": {}}
        mgr = TTSManager(cfg)
        mock_primary = MagicMock()
        mgr.primary = mock_primary

        res = mgr.speak("<think>только мысли</think>")
        assert res is False
        mock_primary.speak.assert_not_called()

    def test_tts_manager_fallback_receives_stripped_text(self):
        cfg = {"engine": "piper", "piper": {}, "gtts": {}}
        mgr = TTSManager(cfg)
        mock_primary = MagicMock()
        mock_primary.speak.side_effect = RuntimeError("Primary failure")
        mock_fallback = MagicMock()
        mock_fallback.speak.return_value = True
        mgr.primary = mock_primary
        mgr.fallback = mock_fallback

        res = mgr.speak("<think>мысли</think>Фоллбек ответ")
        assert res is True
        mock_primary.speak.assert_called_once_with("Фоллбек ответ")
        mock_fallback.speak.assert_called_once_with("Фоллбек ответ")


# =====================================================================
# 5. PiperTTS Invariants
# =====================================================================
class TestPiperTTSInvariants:
    def test_piper_speak_strips_thinking_before_synthesis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_model = Path(tmpdir) / "voice.onnx"
            dummy_model.touch()
            with patch("subprocess.run"):
                piper = PiperTTS(str(dummy_model))

            piper._speak_oneshot = MagicMock(return_value=True)
            piper.use_coprocess = False

            res = piper.speak("<think>внутренний диалог</think>Синтезируемый текст")
            assert res is True
            piper._speak_oneshot.assert_called_once()
            called_text = piper._speak_oneshot.call_args[0][0]
            assert called_text == "Синтезируемый текст"

    def test_piper_speak_only_thinking_aborts_early(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_model = Path(tmpdir) / "voice.onnx"
            dummy_model.touch()
            with patch("subprocess.run"):
                piper = PiperTTS(str(dummy_model))

            piper._speak_oneshot = MagicMock(return_value=True)
            piper.use_coprocess = False

            res = piper.speak("<think>только мысли</think>")
            assert res is False
            piper._speak_oneshot.assert_not_called()

    def test_piper_speak_unclosed_thinking_aborts_early(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_model = Path(tmpdir) / "voice.onnx"
            dummy_model.touch()
            with patch("subprocess.run"):
                piper = PiperTTS(str(dummy_model))

            piper._speak_oneshot = MagicMock(return_value=True)
            piper.use_coprocess = False

            res = piper.speak("<think>незакрытые мысли")
            assert res is False
            piper._speak_oneshot.assert_not_called()

    def test_piper_speak_space_orphan_tag_leak(self):
        """Adversarial check: direct call to PiperTTS with '< /think>'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_model = Path(tmpdir) / "voice.onnx"
            dummy_model.touch()
            with patch("subprocess.run"):
                piper = PiperTTS(str(dummy_model))

            piper._speak_oneshot = MagicMock(return_value=True)
            piper.use_coprocess = False

            piper.speak("< /think>Синтезируемый текст")
            called_text = piper._speak_oneshot.call_args[0][0]
            assert called_text == "Синтезируемый текст", (
                "Invariant preserved: < /think> stripped before reaching synthesizer"
            )
