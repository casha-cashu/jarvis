#!/usr/bin/env python3
"""
Speech-to-Text module using faster-whisper (OpenAI Whisper CTranslate2)
Опциональный бэкенд — выше точность, но больше RAM (tiny ~1GB)
"""

import queue
import pyaudio
from typing import Optional, Callable, List
import logging
import time

from pathlib import Path
import numpy as np

from .stt_base import BaseSTT
from .vad import SileroVAD, VADIteratorWrapper

logger = logging.getLogger(__name__)


class WhisperSTT(BaseSTT):
    """
    Распознавание речи через faster-whisper

    В отличие от Vosk (streaming), Whisper работает батчами:
    1. Записывает аудио в буфер пока говорит пользователь
    2. Раз в partial_interval_ms прогоняет буфер через модель и отдаёт
       промежуточную гипотезу в callback (не пишется в историю)
    3. Когда наступила тишина — транскрибирует весь буфер разом
    Это даёт более высокое качество, но добавляет задержку (~200-500ms).
    """

    # Дефолт: секунд тишины для завершения фразы (если не задан в конфиге)
    DEFAULT_SILENCE_THRESHOLD = 1.0

    def __init__(
        self,
        model_size: str = "tiny",
        model_path: Optional[str] = None,
        sample_rate: int = 16000,
        device_name: Optional[str] = None,
        use_vad: bool = True,
        vad_threshold: float = 0.5,
        partial_interval_ms: int = 1000,
        silence_threshold: Optional[float] = None,
        initial_prompt: Optional[str] = (
            "Разговор с голосовым ассистентом по имени Джарвис."
        ),
    ):
        """
        Args:
            model_size: Размер модели (tiny|base|small|medium|large)
            model_path: Путь к локальной модели (если None, скачивает из HF)
            sample_rate: Частота дискретизации для VAD/Whisper
            device_name: Часть имени микрофона
            use_vad: Использовать Silero VAD
            vad_threshold: Порог VAD
            partial_interval_ms: Интервал промежуточных гипотез (мс; 0 = off)
            silence_threshold: Секунд тишины для завершения фразы
                (None → DEFAULT_SILENCE_THRESHOLD)
            initial_prompt: Текстовая подсказка для контекста (опционально)
        """
        super().__init__(sample_rate=sample_rate, device_name=device_name)
        self.model_size = model_size if model_size != "auto" else "tiny"
        self.model_path = model_path
        self.use_vad = use_vad
        self.partial_interval_ms = max(0, partial_interval_ms)
        self.initial_prompt = initial_prompt
        self.silence_threshold = (
            silence_threshold
            if silence_threshold is not None and silence_threshold > 0
            else self.DEFAULT_SILENCE_THRESHOLD
        )

        # Определяем источник модели
        model_source = self.model_path or self.model_size

        # Если указан локальный путь, проверяем что он существует
        if self.model_path:
            model_path_resolved = Path(self.model_path)
            if model_path_resolved.exists():
                # faster-whisper может сам загрузить из директории
                logger.info(f"📁 Локальная модель: {self.model_path}")
            else:
                logger.warning(
                    f"⚠️ Локальный путь не существует: {self.model_path}. "
                    f"Пробуем загрузить '{self.model_size}' из HuggingFace..."
                )
                model_source = self.model_size  # fallback на HF

        logger.info(f"⏳ Загрузка faster-whisper ({model_source})...")
        try:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(
                model_source,
                device="cpu",
                compute_type="int8",  # 8-bit quantisation для скорости
                cpu_threads=4,
                num_workers=2,
                local_files_only=bool(
                    self.model_path and Path(self.model_path).exists()
                ),
            )
            logger.info(f"✅ faster-whisper ({model_source}) загружена")
        except ImportError:
            logger.error(
                "❌ faster-whisper не установлен. Установи: pip install faster-whisper"
            )
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки faster-whisper: {e}")
            raise

        # VAD (переиспользуем Silero из vad.py)
        self.vad = None
        self.vad_iterator = None
        if use_vad:
            try:
                self.vad = SileroVAD(threshold=vad_threshold, sampling_rate=sample_rate)
                self.vad_iterator = VADIteratorWrapper(self.vad)
                logger.info("✅ Silero VAD инициализирован")
            except Exception as e:
                logger.warning(f"⚠️ VAD не загружен: {e}")
                self.use_vad = False

    def recognize_from_mic(
        self,
        phrase_time_limit: int = 10,
        callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Записывает речь в буфер, затем транскрибирует через faster-whisper.

        Args:
            phrase_time_limit: Макс. время ожидания речи (сек)
            callback: Функция для partial-результатов (промежуточные
                гипотезы раз в partial_interval_ms)

        Returns:
            Распознанный текст
        """
        audio_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=100)
        pa_continue = getattr(pyaudio, "paContinue", 0)
        is_recording = True

        def audio_callback(in_data, frame_count, time_info, status):
            if is_recording:
                try:
                    audio_queue.put_nowait(in_data)
                except queue.Full:
                    try:
                        audio_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        audio_queue.put_nowait(in_data)
                    except queue.Full:
                        pass
            return (in_data, pa_continue)

        # Открываем поток — каналы известны заранее (определено в __init__)
        stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.mic_channels,
            rate=self.mic_sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=2048,
            stream_callback=audio_callback,
        )

        need_resample = self.mic_sample_rate != self.sample_rate
        # Буфер для накопления аудио
        audio_buffer: List[np.ndarray] = []
        last_partial_ts = 0.0
        partial_interval_s = self.partial_interval_ms / 1000.0

        start_time = time.time()
        speech_detected = not bool(self.use_vad and self.vad_iterator)
        silence_start = None

        try:
            stream.start_stream()
            logger.debug("🎤 Слушаю (Whisper)...")
            while stream.is_active():
                if time.time() - start_time > phrase_time_limit:
                    logger.debug("⏱️ Таймаут")
                    break

                try:
                    data = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # ── Стерео → Моно + Ресемплинг + Нормализация ──
                audio_int16 = self._stereo_to_mono(data, self.mic_channels)
                if need_resample:
                    audio_int16 = self._resample_pcm16(
                        audio_int16.tobytes(),
                        self.mic_sample_rate,
                        self.sample_rate,
                    )
                _audio_int16, audio_float32 = self._normalize_volume(audio_int16)

                # ── VAD ──
                if self.use_vad and self.vad_iterator:
                    vad_result = self.vad_iterator.process_chunk(audio_float32)

                    if vad_result["start"]:
                        logger.debug("🗣️ Речь началась")
                        speech_detected = True
                        silence_start = None

                    if vad_result["end"]:
                        logger.debug("🤐 Речь закончилась")
                        silence_start = time.time()

                    if speech_detected and silence_start:
                        if time.time() - silence_start > self.silence_threshold:
                            logger.debug("✅ Фраза завершена (тишина)")
                            break

                # Накопление аудио в буфер + промежуточные гипотезы
                if speech_detected:
                    audio_buffer.append(audio_float32)

                    if (
                        callback is not None
                        and partial_interval_s > 0
                        and time.time() - last_partial_ts >= partial_interval_s
                    ):
                        last_partial_ts = time.time()
                        partial_text = self._transcribe_array(
                            np.concatenate(audio_buffer), vad_filter=True, beam_size=1
                        )
                        if partial_text:
                            logger.debug(f"📝 Whisper partial: {partial_text}")
                            callback(partial_text)

        finally:
            try:
                try:
                    if stream.is_active():
                        stream.stop_stream()
                except Exception as e:
                    logger.debug(f"stop_stream error: {e}")
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                if self.vad_iterator:
                    self.vad_iterator.reset()

        # Если ничего не записано — пусто
        if not audio_buffer:
            return ""

        # Транскрибируем весь буфер разом
        text = self._transcribe_array(
            np.concatenate(audio_buffer), vad_filter=False, beam_size=3
        )

        if text:
            logger.info(f"📝 Whisper: {text}")
        else:
            logger.debug("📝 Whisper: пусто")

        return text

    def _transcribe_array(
        self,
        audio: np.ndarray,
        vad_filter: bool = False,
        beam_size: int = 3,
        initial_prompt: Optional[str] = None,
    ) -> str:
        """Транскрибирует float32-массив через faster-whisper."""
        try:
            prompt = (
                initial_prompt if initial_prompt is not None else self.initial_prompt
            )
            segments, _info = self.model.transcribe(
                audio,
                language="ru",
                beam_size=beam_size,
                vad_filter=vad_filter,
                condition_on_previous_text=False,
                initial_prompt=prompt,
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as e:
            logger.error(f"❌ Ошибка Whisper транскрибации: {e}")
            return ""

    def close(self):
        """Закрывает ресурсы"""
        if self.audio:
            try:
                self.audio.terminate()
            except Exception:
                pass
            self.audio = None
        logger.info("🛑 WhisperSTT закрыт")
