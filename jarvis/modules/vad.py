#!/usr/bin/env python3
"""
Voice Activity Detection (VAD) module using Silero VAD.
Детекция голоса для предотвращения обрезания начала/конца фраз.

Поддерживает чистый ONNX Runtime (CPU) без зависимости от PyTorch,
с прозрачным fallback на PyTorch если onnxruntime недоступен.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def _find_onnx_model_path() -> Optional[str]:
    """Ищет silero_vad.onnx в пакете silero-vad или локальных путях."""
    try:
        import silero_vad

        pkg_path = os.path.join(
            os.path.dirname(silero_vad.__file__), "data", "silero_vad.onnx"
        )
        if os.path.isfile(pkg_path):
            return pkg_path
    except Exception:
        pass

    try:
        from jarvis.resources import resource_path

        bundled = resource_path("data/silero_vad.onnx")
        if os.path.isfile(bundled):
            return bundled
    except Exception:
        pass

    candidates = [
        Path("data/silero_vad.onnx"),
        Path("models/silero_vad.onnx"),
        Path.home() / ".local/share/jarvis/models/silero_vad.onnx",
        Path("/usr/share/jarvis/models/silero_vad.onnx"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


class OnnxVADIterator:
    """Потоковый итератор VAD на чистом NumPy / ONNX."""

    def __init__(
        self,
        model: Any,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
    ):
        self.model = model
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        if sampling_rate not in (8000, 16000):
            raise ValueError(f"Unsupported sampling rate: {sampling_rate}")
        self.min_silence_samples = sampling_rate * min_silence_duration_ms / 1000
        self.speech_pad_samples = sampling_rate * speech_pad_ms / 1000
        self.triggered = False
        self.temp_end = 0
        self.current_sample = 0
        self.reset_states()

    def reset_states(self) -> None:
        if hasattr(self.model, "reset_states"):
            self.model.reset_states()
        self.triggered = False
        self.temp_end = 0
        self.current_sample = 0

    def __call__(
        self,
        x: Any,
        return_seconds: bool = False,
        time_resolution: int = 1,
    ) -> Optional[dict]:
        if hasattr(x, "numpy"):
            x = x.numpy()
        if isinstance(x, np.ndarray):
            window_size_samples = x.shape[-1]
        else:
            window_size_samples = len(x)
        self.current_sample += window_size_samples

        if hasattr(self.model, "is_speech"):
            speech_prob = self.model.is_speech(x)
        else:
            speech_prob = float(self.model(x, self.sampling_rate))

        if (speech_prob >= self.threshold) and self.temp_end:
            self.temp_end = 0

        if (speech_prob >= self.threshold) and not self.triggered:
            self.triggered = True
            speech_start = max(
                0,
                self.current_sample - self.speech_pad_samples - window_size_samples,
            )
            return {
                "start": (
                    int(speech_start)
                    if not return_seconds
                    else round(speech_start / self.sampling_rate, time_resolution)
                )
            }

        if (speech_prob < self.threshold - 0.15) and self.triggered:
            if not self.temp_end:
                self.temp_end = self.current_sample
            if self.current_sample - self.temp_end < self.min_silence_samples:
                return None
            speech_end = self.temp_end + self.speech_pad_samples - window_size_samples
            self.temp_end = 0
            self.triggered = False
            return {
                "end": (
                    int(speech_end)
                    if not return_seconds
                    else round(speech_end / self.sampling_rate, time_resolution)
                )
            }

        return None


class SileroVAD:
    """Silero VAD для детекции речи (ONNX Runtime с PyTorch fallback)."""

    def __init__(
        self,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 30,
        model_path: str = "auto",
    ):
        """
        Args:
            threshold: Порог вероятности речи (0.0-1.0)
            sampling_rate: Частота дискретизации (8000 или 16000)
            min_speech_duration_ms: Минимальная длительность речи (мс)
            min_silence_duration_ms: Минимальная длительность тишины (мс)
            speech_pad_ms: Padding вокруг речи (мс)
            model_path: Путь к модели или 'auto'
        """
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms

        self.is_onnx = False
        self._state: Optional[np.ndarray] = None
        self._context: Optional[np.ndarray] = None
        self.session: Any = None
        self.model: Any = None
        self.get_speech_timestamps: Any = None
        self.save_audio: Any = None
        self.read_audio: Any = None
        self.collect_chunks: Any = None

        # 1. Попытка загрузить чистый ONNX Runtime (CPU)
        onnx_file = (
            model_path
            if model_path != "auto" and os.path.isfile(model_path)
            else _find_onnx_model_path()
        )
        if onnx_file:
            try:
                import onnxruntime as ort

                opts = ort.SessionOptions()
                opts.inter_op_num_threads = 1
                opts.intra_op_num_threads = 1
                self.session = ort.InferenceSession(
                    onnx_file,
                    providers=["CPUExecutionProvider"],
                    sess_options=opts,
                )
                self.model = self.session
                self.is_onnx = True
                self.reset_states()
                self.VADIterator = OnnxVADIterator
                logger.info("✅ Silero VAD загружен через ONNX Runtime (CPU)")
                return
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось загрузить ONNX Silero VAD ({e}), пробую fallback на PyTorch..."
                )

        # 2. Fallback на PyTorch / silero_vad / torch.hub
        try:
            import torch

            try:
                from silero_vad import (
                    collect_chunks,
                    get_speech_timestamps,
                    load_silero_vad,
                    read_audio,
                    save_audio,
                    VADIterator,
                )

                self.model = load_silero_vad()
                utils = (
                    get_speech_timestamps,
                    save_audio,
                    read_audio,
                    VADIterator,
                    collect_chunks,
                )
            except ImportError:
                self.model, utils = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    force_reload=False,
                    onnx=False,
                    trust_repo=True,
                )

            (
                self.get_speech_timestamps,
                self.save_audio,
                self.read_audio,
                self.VADIterator,
                self.collect_chunks,
            ) = utils
            self.is_onnx = False
            logger.info("✅ Silero VAD загружен через PyTorch")

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки Silero VAD: {e}")
            raise

    def reset_states(self) -> None:
        """Сбрасывает скрытые состояния модели."""
        if self.is_onnx:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._context = np.zeros((1, 64), dtype=np.float32)
        elif hasattr(self.model, "reset_states"):
            self.model.reset_states()

    def is_speech(self, audio_chunk: Any) -> float:
        """
        Проверяет, содержит ли аудио речь.

        Args:
            audio_chunk: Аудио данные (numpy array, float32, [-1, 1])

        Returns:
            Вероятность речи (0.0-1.0)
        """
        try:
            if self.is_onnx:
                if hasattr(audio_chunk, "numpy"):
                    audio_chunk = audio_chunk.numpy()
                arr = np.asarray(audio_chunk, dtype=np.float32)
                if arr.ndim == 1:
                    arr = np.expand_dims(arr, 0)
                if self._context is None or self._state is None:
                    self.reset_states()
                assert self._context is not None and self._state is not None
                x = np.concatenate([self._context, arr], axis=1)
                sr = np.array(self.sampling_rate, dtype=np.int64)
                out, self._state = self.session.run(
                    None, {"input": x, "state": self._state, "sr": sr}
                )
                self._context = x[:, -64:]
                return float(out[0][0])
            else:
                import torch

                if isinstance(audio_chunk, np.ndarray):
                    audio_tensor = torch.from_numpy(audio_chunk).float()
                else:
                    audio_tensor = audio_chunk
                with torch.no_grad():
                    return float(self.model(audio_tensor, self.sampling_rate).item())

        except Exception as e:
            logger.error(f"❌ Ошибка VAD: {e}")
            return 0.0

    def detect_speech_segments(self, audio: np.ndarray) -> List[dict]:
        """
        Находит сегменты речи в аудио.

        Args:
            audio: Полное аудио (numpy array)

        Returns:
            Список словарей с 'start' и 'end' (в сэмплах)
        """
        try:
            if not self.is_onnx and self.get_speech_timestamps is not None:
                import torch

                audio_tensor = torch.from_numpy(audio).float()
                return self.get_speech_timestamps(
                    audio_tensor,
                    self.model,
                    threshold=self.threshold,
                    sampling_rate=self.sampling_rate,
                    min_speech_duration_ms=self.min_speech_duration_ms,
                    min_silence_duration_ms=self.min_silence_duration_ms,
                    speech_pad_ms=self.speech_pad_ms,
                )

            # Чистый ONNX путь
            iterator = OnnxVADIterator(
                self,
                threshold=self.threshold,
                sampling_rate=self.sampling_rate,
                min_silence_duration_ms=self.min_silence_duration_ms,
                speech_pad_ms=self.speech_pad_ms,
            )
            chunk_size = 512 if self.sampling_rate == 16000 else 256
            segments: List[dict] = []
            current_start: Optional[int] = None
            for i in range(0, len(audio), chunk_size):
                chunk = audio[i : i + chunk_size]
                if len(chunk) < chunk_size:
                    chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
                res = iterator(chunk, return_seconds=False)
                if res:
                    if "start" in res:
                        current_start = int(res["start"])
                    if "end" in res and current_start is not None:
                        segments.append(
                            {"start": current_start, "end": int(res["end"])}
                        )
                        current_start = None
            if current_start is not None:
                segments.append({"start": current_start, "end": len(audio)})
            return segments

        except Exception as e:
            logger.error(f"❌ Ошибка детекции сегментов: {e}")
            return []

    def extract_speech(self, audio: np.ndarray) -> Optional[np.ndarray]:
        """
        Извлекает только речь из аудио.

        Args:
            audio: Полное аудио

        Returns:
            Аудио только с речью или None
        """
        try:
            segments = self.detect_speech_segments(audio)
            if not segments:
                return None

            speech_chunks = [audio[s["start"] : s["end"]] for s in segments]
            if speech_chunks:
                return np.concatenate(speech_chunks)
            return None

        except Exception as e:
            logger.error(f"❌ Ошибка извлечения речи: {e}")
            return None


class VADIteratorWrapper:
    """Wrapper для потоковой обработки аудио с VAD."""

    def __init__(self, vad: SileroVAD, chunk_size: int = 512):
        self.vad = vad
        self.chunk_size = chunk_size
        if vad.is_onnx:
            self.iterator = vad.VADIterator(
                vad,
                threshold=vad.threshold,
                sampling_rate=vad.sampling_rate,
            )
        else:
            self.iterator = vad.VADIterator(vad.model, threshold=vad.threshold)
        self.is_speaking = False
        self.speech_started = False
        self._buffer = np.array([], dtype=np.float32)

    def process_chunk(self, audio_chunk: np.ndarray) -> dict:
        """
        Обрабатывает чанк аудио (накапливает буфер, подаёт по 512 сэмплов).

        Args:
            audio_chunk: Чанк аудио (любого размера)

        Returns:
            dict с ключами: speech (bool), start (bool), end (bool)
        """
        self._buffer = np.concatenate([self._buffer, audio_chunk])
        result = {"speech": False, "start": False, "end": False}

        while len(self._buffer) >= self.chunk_size:
            chunk = self._buffer[: self.chunk_size]
            self._buffer = self._buffer[self.chunk_size :]

            try:
                if self.vad.is_onnx:
                    speech_dict = self.iterator(chunk, return_seconds=False)
                else:
                    import torch

                    audio_tensor = torch.from_numpy(chunk).float()
                    speech_dict = self.iterator(audio_tensor, return_seconds=False)

                if speech_dict:
                    if "start" in speech_dict:
                        result["start"] = True
                        result["speech"] = True
                        self.is_speaking = True
                        self.speech_started = True

                    if "end" in speech_dict:
                        result["end"] = True
                        result["speech"] = False
                        self.is_speaking = False
                else:
                    result["speech"] = self.is_speaking

            except Exception as e:
                logger.error(f"❌ Ошибка обработки чанка: {e}")
                return {"speech": False, "start": False, "end": False}

        return result

    def flush(self) -> dict:
        """Сбрасывает остаток буфера (если речь была)."""
        result = {"speech": False, "start": False, "end": False}
        if len(self._buffer) > 0:
            needed = self.chunk_size - len(self._buffer)
            buf = self._buffer
            self._buffer = np.array([], dtype=np.float32)
            if needed > 0:
                chunk = np.pad(buf, (0, needed))
            else:
                chunk = buf[: self.chunk_size]
            result = self.process_chunk(chunk)
        self._buffer = np.array([], dtype=np.float32)
        return result

    def reset(self) -> None:
        """Сбрасывает состояние итератора."""
        self.iterator.reset_states()
        self.is_speaking = False
        self.speech_started = False
        self._buffer = np.array([], dtype=np.float32)
