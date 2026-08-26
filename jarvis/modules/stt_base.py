#!/usr/bin/env python3
"""
Общая база для STT-движков (VoskSTT / WhisperSTT).

Сюда вынесено всё, что не зависит от конкретного движка:
поиск микрофона в PyAudio, частота/каналы устройства, список устройств,
стерео→моно, ресемплинг (audioop.ratecv) и нормализация громкости.
"""

import audioop
import logging
from typing import Optional, Tuple

import numpy as np
import pyaudio

logger = logging.getLogger(__name__)


class BaseSTT:
    """Общая обвязка микрофона для VoskSTT и WhisperSTT."""

    def __init__(self, sample_rate: int = 16000, device_name: Optional[str] = None):
        """
        Args:
            sample_rate: Целевая частота движка (обычно 16000)
            device_name: Часть имени микрофона (None/пусто = дефолтный)
        """
        self.sample_rate = sample_rate
        self.device_name = device_name

        # Единый экземпляр PyAudio для всех методов
        self.audio = pyaudio.PyAudio()

        # Находим микрофон
        self.device_index = self._find_device()

        # Определяем частоту микрофона
        self.mic_sample_rate = self._get_device_sample_rate()

        # Определяем количество каналов (1 раз, без fallback-задержек)
        self.mic_channels = self._get_device_channels()

    # ── Устройства ───────────────────────────────────────────────

    def _find_device(self) -> Optional[int]:
        """Находит микрофон по имени (использует self.audio)."""
        if not self.device_name:
            default_device = self.audio.get_default_input_device_info()
            logger.info(f"Используется дефолтный микрофон: {default_device['name']}")
            return None

        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                if self.device_name.lower() in info["name"].lower():
                    logger.info(f"✅ Найден микрофон: {info['name']} (index={i})")
                    return i

        logger.warning(
            f"⚠️ Микрофон '{self.device_name}' не найден, используется дефолтный"
        )
        return None

    def _get_device_sample_rate(self) -> int:
        """Получает частоту дискретизации микрофона."""
        if self.device_index is not None:
            info = self.audio.get_device_info_by_index(self.device_index)
        else:
            info = self.audio.get_default_input_device_info()

        rate = int(info["defaultSampleRate"])
        logger.info(f"📊 Частота микрофона: {rate}Hz, цель: {self.sample_rate}Hz")
        return rate

    def _get_device_channels(self) -> int:
        """Определяет количество входных каналов микрофона (однократно)."""
        if self.device_index is not None:
            info = self.audio.get_device_info_by_index(self.device_index)
        else:
            info = self.audio.get_default_input_device_info()
        channels = int(info.get("maxInputChannels", 1))
        # Каналы выше 2 — виртуальные устройства; движки работают со стерео
        if channels > 2:
            channels = 2
        logger.info(f"🎤 Каналов микрофона: {channels}")
        return channels

    def list_devices(self):
        """Выводит список всех аудио устройств."""
        print("\n=== АУДИО УСТРОЙСТВА ===")
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                print(f"{i}: {info['name']}")
                print(
                    f"   Каналов: {info['maxInputChannels']}, "
                    f"Частота: {int(info['defaultSampleRate'])}Hz"
                )
        print("=" * 40)

    # ── Аудио-помощники (PCM16 mono pipeline) ────────────────────

    @staticmethod
    def _stereo_to_mono(data: bytes, channels: int) -> np.ndarray:
        """PCM16-байты → int16-массив; микширует каналы в моно при >1."""
        audio_int16 = np.frombuffer(data, dtype=np.int16)
        if channels > 1:
            audio_int16 = (
                audio_int16.reshape(-1, channels).mean(axis=1).astype(np.int16)
            )
        return audio_int16

    @staticmethod
    def _resample_pcm16(data: bytes, src_rate: int, dst_rate: int) -> np.ndarray:
        """Ресемплинг PCM16 с anti-aliasing (audioop.ratecv); identity при
        равных частотах. Возвращает int16-массив."""
        if src_rate == dst_rate:
            return np.frombuffer(data, dtype=np.int16)
        converted, _ = audioop.ratecv(data, 2, 1, src_rate, dst_rate, None)
        return np.frombuffer(converted, dtype=np.int16)

    @staticmethod
    def _normalize_volume(
        audio_int16: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Нормализация громкости: подтягивает тихий голос (<0.15 peak).

        Returns:
            (int16-массив после нормализации, float32 в диапазоне [-1, 1])
        """
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        if audio_float32.size == 0:
            return audio_int16, audio_float32
        peak = float(np.max(np.abs(audio_float32)))
        if 0 < peak < 0.15:  # Только если сигнал слишком тихий
            gain = min(0.7 / peak, 4.0)  # Поднимаем до -3dB, максимум 4x
            audio_float32 = audio_float32 * gain
            audio_int16 = np.clip(
                (audio_float32 * 32768.0).astype(np.int16), -32768, 32767
            )
        return audio_int16, audio_float32
