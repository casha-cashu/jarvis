#!/usr/bin/env python3
"""
Speech-to-Text module using Vosk
Распознавание речи с поддержкой Silero VAD
"""

import audioop
import json
import queue
from pathlib import Path
import numpy as np
import pyaudio
from vosk import Model, KaldiRecognizer
from typing import Optional, Callable
import logging
import time

from .vad import SileroVAD, VADIteratorWrapper

logger = logging.getLogger(__name__)


class VoskSTT:
    """Vosk Speech-to-Text с VAD"""

    def __init__(
        self,
        model_path: str,
        sample_rate: int = 16000,
        device_name: Optional[str] = None,
        use_vad: bool = True,
        vad_threshold: float = 0.5,
    ):
        """
        Args:
            model_path: Путь к модели Vosk
            sample_rate: Частота для Vosk (обычно 16000)
            device_name: Часть имени микрофона для поиска (например "USB PnP")
            use_vad: Использовать Silero VAD
            vad_threshold: Порог VAD (0.0-1.0)
        """
        self.sample_rate = sample_rate
        self.device_name = device_name
        self.use_vad = use_vad

        # Разрешаем "auto" путь до модели
        model_path = self._resolve_model_path(model_path)

        # Единый экземпляр PyAudio для всех методов
        self.audio = pyaudio.PyAudio()

        # Находим микрофон
        self.device_index = self._find_device()

        # Определяем частоту микрофона
        self.mic_sample_rate = self._get_device_sample_rate()

        # Определяем количество каналов (1 раз, без fallback-задержек)
        self.mic_channels = self._get_device_channels()

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

    def _find_device(self) -> Optional[int]:
        """Находит микрофон по имени (использует self.audio)"""
        # Если имя не указано, используем дефолтный
        if not self.device_name:
            default_device = self.audio.get_default_input_device_info()
            logger.info(f"Используется дефолтный микрофон: {default_device['name']}")
            return None

        # Ищем по имени
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
        """Получает частоту дискретизации микрофона (использует self.audio)"""
        if self.device_index is not None:
            info = self.audio.get_device_info_by_index(self.device_index)
        else:
            info = self.audio.get_default_input_device_info()

        rate = int(info["defaultSampleRate"])

        logger.info(f"📊 Частота микрофона: {rate}Hz, Vosk: {self.sample_rate}Hz")
        return rate

    def _get_device_channels(self) -> int:
        """Определяет количество входных каналов микрофона (однократно)."""
        if self.device_index is not None:
            info = self.audio.get_device_info_by_index(self.device_index)
        else:
            info = self.audio.get_default_input_device_info()
        channels = int(info.get("maxInputChannels", 1))
        # Большинство Vosk-моделей работают с моно; если устройство шлёт 2,
        # мы смешаем в моно в recognise_from_mic
        if channels > 2:
            channels = 2  # Каналы выше 2 — виртуальные устройства, берём стерео
        logger.info(f"🎤 Каналов микрофона: {channels}")
        return channels

    def list_devices(self):
        """Выводит список всех аудио устройств (использует self.audio)"""
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
        silence_threshold = 2.0  # секунд тишины для завершения фразы
        min_phrase_duration = 0.5  # минимальная длительность речи (сек)
        extra_listen_after_wake = 2.0  # дослушиваем после wake word

        try:
            while stream.is_active():
                if time.time() - start_time > phrase_time_limit:
                    logger.debug("⏱️ Таймаут")
                    break

                try:
                    data = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # === Шаг 1: Стерео → Моно (только если 2 канала) ===
                audio_int16 = np.frombuffer(data, dtype=np.int16)
                if self.mic_channels > 1:
                    audio_int16 = (
                        audio_int16.reshape(-1, 2).mean(axis=1).astype(np.int16)
                    )
                data = audio_int16.tobytes()

                # === Шаг 2: Ресемплинг 48→16kHz с anti-aliasing (audioop.ratecv) ===
                if need_resample:
                    data, _ = audioop.ratecv(
                        data, 2, 1, self.mic_sample_rate, self.sample_rate, None
                    )
                    audio_int16 = np.frombuffer(data, dtype=np.int16)

                # === Шаг 4: Нормализация громкости (подтягиваем тихий голос) ===
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                peak = np.max(np.abs(audio_float32))
                if peak > 0 and peak < 0.15:  # Только если сигнал слишком тихий
                    gain = min(0.7 / peak, 4.0)  # Поднимаем до -3dB, макс增益 4x
                    audio_float32 = audio_float32 * gain
                    audio_int16 = np.clip(
                        (audio_float32 * 32768.0).astype(np.int16), -32768, 32767
                    )
                    data = audio_int16.tobytes()

                # === Шаг 3: VAD ПОСЛЕ ресемплинга (на правильной частоте 16kHz) ===
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
                            if time.time() - silence_start > silence_threshold:
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
