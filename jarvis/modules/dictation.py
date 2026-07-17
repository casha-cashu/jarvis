#!/usr/bin/env python3
"""
Модуль диктовки — голосовой ввод текста в активное окно.
VAD → запись → Whisper → wtype/xdotool
"""

import os
import time
import logging
import subprocess
import numpy as np
from typing import Optional, Callable

from jarvis._env import sanitized_env

logger = logging.getLogger(__name__)


def _type_text(text: str):
    """
    Печатает текст в активное окно.
    Wayland: wtype
    X11: xdotool
    """
    if not text.strip():
        return

    # Экранирование для shell
    escaped = text.replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")

    if os.environ.get("WAYLAND_DISPLAY"):
        # Wayland
        try:
            subprocess.run(
                ["wtype", "-"], input=escaped.encode(), timeout=5, env=sanitized_env()
            )
        except FileNotFoundError:
            logger.warning("⚠️ wtype не найден. Установи: pacman -S wtype")
        except Exception as e:
            logger.error(f"❌ wtype: {e}")
    else:
        # X11
        try:
            subprocess.run(
                ["xdotool", "type", "--", text], timeout=5, env=sanitized_env()
            )
        except FileNotFoundError:
            logger.warning("⚠️ xdotool не найден. Установи: pacman -S xdotool")
        except Exception as e:
            logger.error(f"❌ xdotool: {e}")


def dictation_loop(
    stt,
    on_text: Optional[Callable] = None,
    silence_timeout: float = 1.5,
    max_duration: int = 60,
) -> str:
    """
    Цикл диктовки:
      1. Слушает микрофон (VAD буферизация)
      2. При паузе > silence_timeout → транскрибация
      3. Текст печатается в активное окно
      4. Продолжает слушать
      5. Возвращает полный текст по окончании

    Args:
        stt: Экземпляр STT (VoskSTT или WhisperSTT)
        on_text: Callback при получении текста (для вывода)
        silence_timeout: Пауза для分割 предложений (сек)
        max_duration: Макс. длительность диктовки (сек)

    Returns:
        Полный распознанный текст
    """
    from jarvis.modules.vad import SileroVAD, VADIteratorWrapper
    import pyaudio
    import audioop

    logger.info("🎤 Диктовка началась. Говори текст...")

    # Инициализация аудио
    audio = pyaudio.PyAudio()
    device_index = stt.device_index if hasattr(stt, "device_index") else None
    mic_rate = stt.mic_sample_rate if hasattr(stt, "mic_sample_rate") else 16000
    mic_channels = stt.mic_channels if hasattr(stt, "mic_channels") else 1

    # Открываем поток сразу с правильным числом каналов (без fallback)
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=mic_channels,
        rate=mic_rate,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=2048,
    )

    stream.start_stream()

    # VAD
    vad = SileroVAD(threshold=0.3, sampling_rate=16000)
    vad_iter = VADIteratorWrapper(vad)

    full_text = []
    current_segment = []
    need_resample = mic_rate != 16000
    speech_detected = False
    silence_timer = 0
    last_speech_time = time.time()
    start_time = time.time()

    try:
        while stream.is_active():
            if time.time() - start_time > max_duration:
                logger.info("⏱️ Макс. время диктовки")
                break

            data = stream.read(2048, exception_on_overflow=False)

            # Стерео → моно (если 2 канала)
            audio_int16 = np.frombuffer(data, dtype=np.int16)
            if mic_channels > 1:
                audio_int16 = audio_int16.reshape(-1, 2).mean(axis=1).astype(np.int16)

            # Ресемплинг если нужно
            if need_resample:
                audio_data, _ = audioop.ratecv(
                    audio_int16.tobytes(), 2, 1, mic_rate, 16000, None
                )
                audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

            # VAD
            audio_float = audio_int16.astype(np.float32) / 32768.0
            vad_result = vad_iter.process_chunk(audio_float)

            if vad_result["start"]:
                speech_detected = True
                silence_timer = 0
                print("\r🎤 [[говорит]]", end="", flush=True)

            if vad_result["end"]:
                silence_timer = time.time()
                print("\r⏳ [[жду]]", end="", flush=True)

            if speech_detected:
                current_segment.append(audio_float)

            # Транскрибация при паузе
            if speech_detected and silence_timer > 0:
                if time.time() - silence_timer > silence_timeout:
                    if current_segment:
                        segment = np.concatenate(current_segment)
                        current_segment = []
                        silence_timer = 0
                        speech_detected = False

                        # Транскрибация через Vosk или Whisper
                        if (
                            hasattr(stt, "model")
                            and "whisper" in type(stt).__name__.lower()
                        ):
                            text = _transcribe_whisper(stt, segment)
                        else:
                            text = _transcribe_vosk(stt, segment)

                        if text:
                            full_text.append(text)
                            print(f"\r📝 {text}")
                            if on_text:
                                on_text(text)
                            _type_text(text + " ")

            # Небольшая пауза для снижения нагрузки
            time.sleep(0.01)

    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

    # Финальный сегмент
    if current_segment:
        segment = np.concatenate(current_segment)
        if hasattr(stt, "model") and "whisper" in type(stt).__name__.lower():
            text = _transcribe_whisper(stt, segment)
        else:
            text = _transcribe_vosk(stt, segment)
        if text:
            full_text.append(text)
            _type_text(text + " ")

    result = " ".join(full_text)
    logger.info(f"✅ Диктовка завершена: {len(full_text)} сегментов")
    return result


def _transcribe_whisper(stt, audio: np.ndarray) -> str:
    """Транскрибация через Whisper"""
    try:
        segments, _ = stt.model.transcribe(audio, language="ru", beam_size=3)
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        logger.error(f"❌ Whisper: {e}")
        return ""


def _transcribe_vosk(stt, audio: np.ndarray) -> str:
    """Транскрибация через Vosk"""
    try:
        data = (audio * 32768.0).astype(np.int16).tobytes()
        if stt.recognizer.AcceptWaveform(data):
            import json

            res = json.loads(stt.recognizer.Result())
            return res.get("text", "").strip()
        return ""
    except Exception as e:
        logger.error(f"❌ Vosk: {e}")
        return ""
