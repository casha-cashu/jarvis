#!/usr/bin/env python3
"""
Voice Activity Detection (VAD) module using Silero VAD
Детекция голоса для предотвращения обрезания начала/конца фраз
"""

import torch
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class SileroVAD:
    """Silero VAD для детекции речи"""

    def __init__(
        self,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 30
    ):
        """
        Args:
            threshold: Порог вероятности речи (0.0-1.0)
            sampling_rate: Частота дискретизации (8000 или 16000)
            min_speech_duration_ms: Минимальная длительность речи (мс)
            min_silence_duration_ms: Минимальная длительность тишины (мс)
            speech_pad_ms: Padding вокруг речи (мс)
        """
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms

        # Загружаем модель Silero VAD
        try:
            self.model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False,
                trust_repo=True  # Доверяем репозиторию
            )

            (self.get_speech_timestamps,
             self.save_audio,
             self.read_audio,
             self.VADIterator,
             self.collect_chunks) = utils

            logger.info("✅ Silero VAD загружен")

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки Silero VAD: {e}")
            raise

    def is_speech(self, audio_chunk: np.ndarray) -> float:
        """
        Проверяет, содержит ли аудио речь

        Args:
            audio_chunk: Аудио данные (numpy array, float32, [-1, 1])

        Returns:
            Вероятность речи (0.0-1.0)
        """
        try:
            # Конвертируем в torch tensor
            if isinstance(audio_chunk, np.ndarray):
                audio_tensor = torch.from_numpy(audio_chunk).float()
            else:
                audio_tensor = audio_chunk

            # Получаем вероятность речи
            with torch.no_grad():
                speech_prob = self.model(audio_tensor, self.sampling_rate).item()

            return speech_prob

        except Exception as e:
            logger.error(f"❌ Ошибка VAD: {e}")
            return 0.0

    def detect_speech_segments(self, audio: np.ndarray) -> list:
        """
        Находит сегменты речи в аудио

        Args:
            audio: Полное аудио (numpy array)

        Returns:
            Список словарей с 'start' и 'end' (в сэмплах)
        """
        try:
            audio_tensor = torch.from_numpy(audio).float()

            speech_timestamps = self.get_speech_timestamps(
                audio_tensor,
                self.model,
                threshold=self.threshold,
                sampling_rate=self.sampling_rate,
                min_speech_duration_ms=self.min_speech_duration_ms,
                min_silence_duration_ms=self.min_silence_duration_ms,
                speech_pad_ms=self.speech_pad_ms
            )

            return speech_timestamps

        except Exception as e:
            logger.error(f"❌ Ошибка детекции сегментов: {e}")
            return []

    def extract_speech(self, audio: np.ndarray) -> Optional[np.ndarray]:
        """
        Извлекает только речь из аудио

        Args:
            audio: Полное аудио

        Returns:
            Аудио только с речью или None
        """
        try:
            segments = self.detect_speech_segments(audio)

            if not segments:
                return None

            # Собираем все сегменты речи
            speech_chunks = []
            for segment in segments:
                start = segment['start']
                end = segment['end']
                speech_chunks.append(audio[start:end])

            # Объединяем
            if speech_chunks:
                return np.concatenate(speech_chunks)

            return None

        except Exception as e:
            logger.error(f"❌ Ошибка извлечения речи: {e}")
            return None


class VADIteratorWrapper:
    """Wrapper для потоковой обработки аудио с VAD"""

    def __init__(self, vad: SileroVAD, chunk_size: int = 512):
        """
        Args:
            vad: Экземпляр SileroVAD
            chunk_size: Размер чанка для обработки (Silero VAD требует 512)
        """
        self.vad = vad
        self.chunk_size = chunk_size
        self.iterator = vad.VADIterator(vad.model, threshold=vad.threshold)
        self.is_speaking = False
        self.speech_started = False
        self._buffer = np.array([], dtype=np.float32)

    def process_chunk(self, audio_chunk: np.ndarray) -> dict:
        """
        Обрабатывает чанк аудио (накапливает буфер, подаёт по 512 сэмплов)

        Args:
            audio_chunk: Чанк аудио (любого размера)

        Returns:
            dict с ключами:
                - 'speech': bool (есть ли речь)
                - 'start': bool (начало речи)
                - 'end': bool (конец речи)
        """
        # Накапливаем в буфер
        self._buffer = np.concatenate([self._buffer, audio_chunk])

        result = {'speech': False, 'start': False, 'end': False}

        # Пока в буфере достаточно сэмплов — подаём по chunk_size
        while len(self._buffer) >= self.chunk_size:
            chunk = self._buffer[:self.chunk_size]
            self._buffer = self._buffer[self.chunk_size:]

            try:
                audio_tensor = torch.from_numpy(chunk).float()
                speech_dict = self.iterator(audio_tensor, return_seconds=False)

                if speech_dict:
                    if 'start' in speech_dict:
                        result['start'] = True
                        result['speech'] = True
                        self.is_speaking = True
                        self.speech_started = True

                    if 'end' in speech_dict:
                        result['end'] = True
                        result['speech'] = False
                        self.is_speaking = False
                else:
                    result['speech'] = self.is_speaking

            except Exception as e:
                logger.error(f"❌ Ошибка обработки чанка: {e}")
                return {'speech': False, 'start': False, 'end': False}

        return result

    def flush(self) -> dict:
        """Сбрасывает остаток буфера (если речь была)"""
        result = {'speech': False, 'start': False, 'end': False}
        if len(self._buffer) > 0:
            # Добиваем нулями до chunk_size
            needed = self.chunk_size - len(self._buffer)
            if needed > 0:
                chunk = np.pad(self._buffer, (0, needed))
                result = self.process_chunk(chunk)
        self._buffer = np.array([], dtype=np.float32)
        return result

    def reset(self):
        """Сбрасывает состояние итератора"""
        self.iterator.reset_states()
        self.is_speaking = False
        self.speech_started = False
        self._buffer = np.array([], dtype=np.float32)
