#!/usr/bin/env python3
"""
Speech-to-Text module using faster-whisper (OpenAI Whisper CTranslate2)
Опциональный бэкенд — выше точность, но больше RAM (tiny ~1GB)
"""

import audioop
import queue
import numpy as np
import pyaudio
from typing import Optional, Callable, List
import logging
import time

from pathlib import Path
from .vad import SileroVAD, VADIteratorWrapper

logger = logging.getLogger(__name__)


class WhisperSTT:
    """
    Распознавание речи через faster-whisper

    В отличие от Vosk (streaming), Whisper работает батчами:
    1. Записывает аудио в буфер пока говорит пользователь
    2. Когда наступила тишина — транскрибирует весь буфер разом
    Это даёт более высокое качество, но добавляет задержку (~200-500ms).
    """

    def __init__(
        self,
        model_size: str = "tiny",
        model_path: Optional[str] = None,
        sample_rate: int = 16000,
        device_name: Optional[str] = None,
        use_vad: bool = True,
        vad_threshold: float = 0.5
    ):
        """
        Args:
            model_size: Размер модели (tiny|base|small|medium|large)
            model_path: Путь к локальной модели (если None, скачивает из HF)
            sample_rate: Частота дискретизации для VAD/Vosk
            device_name: Часть имени микрофона
            use_vad: Использовать Silero VAD
            vad_threshold: Порог VAD
        """
        self.model_size = model_size if model_size != "auto" else "tiny"
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.device_name = device_name
        self.use_vad = use_vad

        # PyAudio (единый экземпляр)
        self.audio = pyaudio.PyAudio()
        self.device_index = self._find_device()
        self.mic_sample_rate = self._get_device_sample_rate()
        self.mic_channels = self._get_device_channels()

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
                compute_type="int8",      # 8-bit quantisation для скорости
                cpu_threads=4,
                num_workers=2,
                local_files_only=bool(self.model_path and Path(self.model_path).exists())
            )
            logger.info(f"✅ faster-whisper ({model_source}) загружена")
        except ImportError:
            logger.error(
                "❌ faster-whisper не установлен. Установи: "
                "pip install faster-whisper"
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
                self.vad = SileroVAD(
                    threshold=vad_threshold,
                    sampling_rate=sample_rate
                )
                self.vad_iterator = VADIteratorWrapper(self.vad)
                logger.info("✅ Silero VAD инициализирован")
            except Exception as e:
                logger.warning(f"⚠️ VAD не загружен: {e}")
                self.use_vad = False

    # ── Поиск устройств (аналогично VoskSTT) ─────────────────────────

    def _find_device(self) -> Optional[int]:
        """Находит микрофон по имени (использует self.audio)"""
        if not self.device_name:
            default_device = self.audio.get_default_input_device_info()
            logger.info(f"Используется дефолтный микрофон: {default_device['name']}")
            return None

        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                if self.device_name.lower() in info['name'].lower():
                    logger.info(f"✅ Найден микрофон: {info['name']} (index={i})")
                    return i

        logger.warning(f"⚠️ Микрофон '{self.device_name}' не найден, используется дефолтный")
        return None

    def _get_device_sample_rate(self) -> int:
        """Получает частоту дискретизации микрофона"""
        if self.device_index is not None:
            info = self.audio.get_device_info_by_index(self.device_index)
        else:
            info = self.audio.get_default_input_device_info()

        rate = int(info['defaultSampleRate'])
        logger.info(f"📊 Частота микрофона: {rate}Hz, Whisper: {self.sample_rate}Hz")
        return rate

    def _get_device_channels(self) -> int:
        """Определяет количество входных каналов микрофона (однократно)."""
        if self.device_index is not None:
            info = self.audio.get_device_info_by_index(self.device_index)
        else:
            info = self.audio.get_default_input_device_info()
        channels = int(info.get('maxInputChannels', 1))
        if channels > 2:
            channels = 2
        logger.info(f"🎤 Каналов микрофона (Whisper): {channels}")
        return channels

    def list_devices(self):
        """Выводит список всех аудио устройств"""
        print("\n=== АУДИО УСТРОЙСТВА ===")
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                print(f"{i}: {info['name']}")
                print(f"   Каналов: {info['maxInputChannels']}, "
                      f"Частота: {int(info['defaultSampleRate'])}Hz")
        print("=" * 40)

    # ── Основной метод распознавания ─────────────────────────────────

    def recognize_from_mic(
        self,
        phrase_time_limit: int = 10,
        callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        Записывает речь в буфер, затем транскрибирует через faster-whisper.

        Args:
            phrase_time_limit: Макс. время ожидания речи (сек)
            callback: Функция для partial-результатов (не поддерживается)

        Returns:
            Распознанный текст
        """
        audio_queue = queue.Queue()

        def audio_callback(in_data, frame_count, time_info, status):
            audio_queue.put(in_data)
            return (in_data, pyaudio.paContinue)

        # Открываем поток — каналы известны заранее (определено в __init__)
        stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.mic_channels,
            rate=self.mic_sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=2048,
            stream_callback=audio_callback
        )

        need_resample = (self.mic_sample_rate != self.sample_rate)
        stream.start_stream()
        logger.debug("🎤 Слушаю (Whisper)...")

        # Буфер для накопления аудио
        audio_buffer: List[np.ndarray] = []

        start_time = time.time()
        speech_detected = False
        silence_start = None
        silence_threshold = 1.0
        has_emitted_partial = False

        try:
            while stream.is_active():
                if time.time() - start_time > phrase_time_limit:
                    logger.debug("⏱️ Таймаут")
                    break

                try:
                    data = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # ── Стерео → Моно (если 2 канала) ──
                audio_int16 = np.frombuffer(data, dtype=np.int16)
                if self.mic_channels > 1:
                    audio_int16 = audio_int16.reshape(-1, 2).mean(axis=1).astype(np.int16)
                data = audio_int16.tobytes()

                # ── Ресемплинг 48→16kHz (anti-aliasing) ──
                if need_resample:
                    data, _ = audioop.ratecv(
                        data, 2, 1,
                        self.mic_sample_rate, self.sample_rate, None
                    )
                    audio_int16 = np.frombuffer(data, dtype=np.int16)

                # ── Нормализация ──
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                peak = np.max(np.abs(audio_float32))
                if peak > 0 and peak < 0.15:
                    gain = min(0.7 / peak, 4.0)
                    audio_float32 = audio_float32 * gain
                    audio_int16 = np.clip(
                        (audio_float32 * 32768.0).astype(np.int16),
                        -32768, 32767
                    )

                # ── VAD ──
                if self.use_vad and self.vad_iterator:
                    vad_result = self.vad_iterator.process_chunk(audio_float32)

                    if vad_result['start']:
                        logger.debug("🗣️ Речь началась")
                        speech_detected = True
                        silence_start = None

                    if vad_result['end']:
                        logger.debug("🤐 Речь закончилась")
                        silence_start = time.time()

                    if speech_detected and silence_start:
                        if time.time() - silence_start > silence_threshold:
                            logger.debug("✅ Фраза завершена (тишина)")
                            break

                # Накопление аудио в буфер
                if speech_detected:
                    audio_buffer.append(audio_float32)

        finally:
            stream.stop_stream()
            stream.close()
            if self.vad_iterator:
                self.vad_iterator.reset()

        # Если ничего не записано — пусто
        if not audio_buffer:
            return ""

        # Склеиваем буфер в один массив
        audio_full = np.concatenate(audio_buffer)

        # Транскрибируем через faster-whisper
        try:
            logger.debug("🧠 Транскрибация Whisper...")
            segments, info = self.model.transcribe(
                audio_full,
                language="ru",
                beam_size=3,
                vad_filter=False,  # VAD уже есть свой
                condition_on_previous_text=False
            )

            text_parts = [seg.text.strip() for seg in segments]
            text = " ".join(text_parts).strip()

            if text:
                logger.info(f"📝 Whisper: {text}")
            else:
                logger.debug("📝 Whisper: пусто")

            return text

        except Exception as e:
            logger.error(f"❌ Ошибка Whisper транскрибации: {e}")
            return ""

    def close(self):
        """Закрывает ресурсы"""
        if self.audio:
            self.audio.terminate()
        logger.info("🛑 WhisperSTT закрыт")
