#!/usr/bin/env python3
"""
Speech-to-Text module using Vosk
Распознавание речи с поддержкой Silero VAD
"""

import json
import queue
from pathlib import Path
import pyaudio
from vosk import Model, KaldiRecognizer
from typing import Optional, Callable
import logging
import time

from .stt_base import BaseSTT
from .vad import SileroVAD, VADIteratorWrapper

logger = logging.getLogger(__name__)


class VoskSTT(BaseSTT):
    """Vosk Speech-to-Text с VAD"""

    # Дефолт: секунд тишины для завершения фразы (если не задан в конфиге)
    DEFAULT_SILENCE_THRESHOLD = 2.0

    def __init__(
        self,
        model_path: str,
        sample_rate: int = 16000,
        device_name: Optional[str] = None,
        use_vad: bool = True,
        vad_threshold: float = 0.5,
        silence_threshold: Optional[float] = None,
    ):
        """
        Args:
            model_path: Путь к модели Vosk
            sample_rate: Частота для Vosk (обычно 16000)
            device_name: Часть имени микрофона для поиска (например "Blue Microphones")
            use_vad: Использовать Silero VAD
            vad_threshold: Порог VAD (0.0-1.0)
            silence_threshold: Секунд тишины для завершения фразы
                (None → DEFAULT_SILENCE_THRESHOLD)
        """
        super().__init__(sample_rate=sample_rate, device_name=device_name)
        self.use_vad = use_vad
        self.silence_threshold = (
            float(silence_threshold)
            if silence_threshold and silence_threshold > 0
            else self.DEFAULT_SILENCE_THRESHOLD
        )

        # Разрешаем "auto" путь до модели
        model_path = self._resolve_model_path(model_path)

        # Загружаем модель Vosk
        logger.info(f"Загрузка Vosk модели: {model_path}")
        try:
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, sample_rate)
            logger.info("✅ Vosk модель загружена")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки Vosk: {e}")
            raise

        # Инициализируем VAD если нужно
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

    @staticmethod
    def _resolve_model_path(model_path: str) -> str:
        """Разрешает 'auto' в реальный путь до Vosk модели"""
        if model_path.lower() != "auto":
            return model_path

        paths_to_check = [
            Path("models"),
            Path.home() / ".local" / "share" / "vosk",
            Path.home() / "models" / "vosk",
            Path.home() / "Models" / "vosk",
            Path("/usr") / "share" / "vosk",
        ]

        for base in paths_to_check:
            if not base.exists():
                continue
            # Ищем любую директорию, содержащую 'vosk-model' или 'model'
            for p in sorted(base.iterdir()):
                name = p.name.lower()
                if p.is_dir() and ("vosk-model" in name or "model" in name):
                    logger.info(f"✅ Найдена Vosk модель: {p}")
                    return str(p)

        logger.warning("⚠️ Vosk модель не найдена, используется путь 'auto'")
        return "auto"

    def recognize_from_mic(
        self,
        phrase_time_limit: int = 10,
        callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Распознаёт речь с микрофона

        Args:
            phrase_time_limit: Максимальное время записи (секунды)
            callback: Функция для partial результатов

        Returns:
            Распознанный текст
        """
        audio_queue = queue.Queue()

        def audio_callback(in_data, frame_count, time_info, status):
            if status and status != 2:  # Игнорируем input overflow (2)
                logger.warning(f"⚠️ Audio status: {status}")
            audio_queue.put(in_data)
            return (in_data, pyaudio.paContinue)

        # Открываем поток — channels уже известен (определён при init)
        # Никаких fallback-задержек: открываем сразу с правильным числом
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

        stream.start_stream()
        logger.debug("🎤 Слушаю...")

        start_time = time.time()
        speech_detected = False
        speech_start_time = None
        silence_start = None
        min_phrase_duration = 0.5  # минимальная длительность речи (сек)

        try:
            while stream.is_active():
                if time.time() - start_time > phrase_time_limit:
                    logger.debug("⏱️ Таймаут")
                    break

                try:
                    data = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # === Стерео → Моно + Ресемплинг + Нормализация ===
                audio_int16 = self._stereo_to_mono(data, self.mic_channels)
                if need_resample:
                    audio_int16 = self._resample_pcm16(
                        audio_int16.tobytes(),
                        self.mic_sample_rate,
                        self.sample_rate,
                    )
                audio_int16, audio_float32 = self._normalize_volume(audio_int16)
                data = audio_int16.tobytes()

                # === VAD на правильной частоте (16kHz) ===
                if self.use_vad and self.vad_iterator:
                    vad_result = self.vad_iterator.process_chunk(audio_float32)

                    if vad_result["start"]:
                        logger.debug("🗣️ Речь началась")
                        if not speech_detected:
                            speech_start_time = time.time()
                        speech_detected = True
                        silence_start = None

                    if vad_result["end"]:
                        logger.debug("🤐 Речь закончилась")
                        silence_start = time.time()

                    # Завершаем фразу, только если было достаточно речи
                    # И тишина длится дольше silence_threshold
                    if speech_detected and silence_start:
                        speech_duration = time.time() - (
                            speech_start_time or time.time()
                        )
                        if speech_duration >= min_phrase_duration:
                            if time.time() - silence_start > self.silence_threshold:
                                logger.debug("✅ Фраза завершена")
                                break

                # === Vosk: распознавание (16kHz, моно, PCM16) ===
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        logger.debug(f"📝 Финальный: {text}")
                        return text
                else:
                    partial = json.loads(self.recognizer.PartialResult())
                    partial_text = partial.get("partial", "").strip()
                    if partial_text and callback:
                        callback(partial_text)

        finally:
            stream.stop_stream()
            stream.close()
            if self.vad_iterator:
                self.vad_iterator.reset()

        final = json.loads(self.recognizer.FinalResult())
        text = final.get("text", "").strip()
        self.recognizer.Reset()

        return text

    def recognize_from_file(self, audio_file: str) -> str:
        """
        Распознаёт речь из аудио файла

        Args:
            audio_file: Путь к WAV файлу (16kHz, моно)

        Returns:
            Распознанный текст
        """
        import wave

        # P4: context-manager закрывает FD на любом из путей выхода.
        # Раньше "wrong format" / exception в while-loop протекали через
        # raw wave.open и оставляли FD открытым.
        with wave.open(audio_file, "rb") as wf:
            if (
                wf.getnchannels() != 1
                or wf.getsampwidth() != 2
                or wf.getframerate() != self.sample_rate
            ):
                logger.error(
                    f"❌ Неверный формат аудио. Нужно: моно, 16bit, {self.sample_rate}Hz"
                )
                return ""

            recognizer = KaldiRecognizer(self.model, self.sample_rate)

            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break

                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "")
                    if text:
                        return text

            final = json.loads(recognizer.FinalResult())
            return final.get("text", "")

    def close(self):
        """Закрывает ресурсы"""
        if self.audio:
            self.audio.terminate()
        logger.info("🛑 STT закрыт")
