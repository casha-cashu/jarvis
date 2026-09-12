"""Аудио-pipeline: микрофон → VAD → STT.

Раньше всё это инициализировалось внутри ``Jarvis.initialize`` (148+ строк
ручной возни в god class). Вынесено отдельно чтобы:
  - тесты могли заглушить STT без поднятия всего Jarvis
  - ``--dry-run`` действительно НЕ грузил модели (P8)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Владеет инстансом STT (Vosk или Whisper) и его lifecycle'ом."""

    def __init__(
        self,
        config: dict,
        dry_run: bool = False,
        max_reconnect_attempts: int = 5,
        reconnect_base_delay: float = 0.5,
        reconnect_max_delay: float = 8.0,
    ):
        self.config = config
        self.dry_run = dry_run
        # VoskSTT | WhisperSTT; типы импортируются лениво в start(),
        # поэтому Any вместо union.
        self.stt: Any = None
        self._started = False
        # PR-AUDIO-REC-1: автореконнект при обрыве микрофонного потока.
        self.max_reconnect_attempts = max(1, int(max_reconnect_attempts))
        self.reconnect_base_delay = float(reconnect_base_delay)
        self.reconnect_max_delay = float(reconnect_max_delay)
        self.consecutive_errors = 0
        self.last_error: Optional[str] = None
        self.stream_healthy = True
        self._needs_recovery = False
        self._sleep: Callable[[float], None] = time.sleep

    def start(self) -> None:
        """Поднимает STT/VAD. В dry-run режиме НЕ скачивает и не грузит
        модели — нужно чтобы CI/быстрая проверка конфига работали без
        полугига torch-вeсов на диске."""
        if self._started:
            return
        if self.dry_run:
            logger.info("🧪 dry-run: пропускаю загрузку STT/VAD моделей")
            self._started = True
            return

        stt_cfg = self.config.get("stt", {})
        audio_cfg = self.config.get("audio", {})
        vad_cfg = self.config.get("vad", {})
        sample_rate = stt_cfg.get("sample_rate", 16000)
        engine = stt_cfg.get("engine", "vosk")

        device_name = audio_cfg.get("microphone", {}).get("device_name")
        use_vad = vad_cfg.get("enabled", True)
        vad_threshold = vad_cfg.get("silero", {}).get("threshold", 0.5)
        # None → движок возьмёт свой дефолт (vosk 2.0 / whisper 1.0)
        silence_threshold = stt_cfg.get("silence_threshold")

        if engine == "whisper":
            from jarvis.modules.stt_whisper import WhisperSTT

            wcfg = stt_cfg.get("whisper", {})
            initial_prompt = wcfg.get("initial_prompt")
            whisper_kwargs: dict[str, Any] = dict(
                model_size=wcfg.get("model_size", "tiny"),
                model_path=wcfg.get("model_path") or None,
                sample_rate=sample_rate,
                device_name=device_name,
                use_vad=use_vad,
                vad_threshold=vad_threshold,
                partial_interval_ms=wcfg.get("partial_interval_ms", 1000),
                silence_threshold=silence_threshold,
            )
            if initial_prompt is not None:
                whisper_kwargs["initial_prompt"] = initial_prompt
            self.stt = WhisperSTT(**whisper_kwargs)
        else:
            try:
                from jarvis.modules.stt import VoskSTT
            except ImportError as e:
                raise RuntimeError(
                    "Движок STT 'vosk' выбран в config.yaml, но vosk не установлен. "
                    'Варианты: pip install ".[vosk]" — wheels есть только для Python '
                    "3.10-3.12; либо переключитесь на whisper: config.yaml → "
                    "stt.engine: whisper (проверка: jarvis doctor)."
                ) from e

            self.stt = VoskSTT(
                model_path=stt_cfg["vosk"]["model_path"],
                sample_rate=sample_rate,
                device_name=device_name,
                use_vad=use_vad,
                vad_threshold=vad_threshold,
                silence_threshold=silence_threshold,
            )

        self.stt.list_devices()
        self._started = True

    def recognize(
        self,
        phrase_time_limit: int,
        on_partial: Optional[Callable[[str], None]] = None,
        on_level: Optional[Callable[[float], None]] = None,
    ) -> Optional[str]:
        if self.dry_run:
            return None
        if self.stt is None:
            # Деградированный поток (прошлая попытка реконнекта исчерпана):
            # пробуем подняться заново — вызовы идут раз в несколько секунд,
            # это естественный rate limit. Нестартованный пайплайн молчит.
            if not (self._started or self._needs_recovery):
                return None
            if not self._recover():
                return None
        try:
            result = self._call_stt(phrase_time_limit, on_partial, on_level)
        except Exception as e:
            if not self._started:
                return None
            self.consecutive_errors += 1
            self.last_error = str(e)
            logger.error(f"❌ STT ошибка: {e}")
            if not self._recover():
                return None
            try:
                result = self._call_stt(phrase_time_limit, on_partial, on_level)
            except Exception as e2:
                self.consecutive_errors += 1
                self.last_error = str(e2)
                logger.error(f"❌ STT ошибка после реконнекта: {e2}")
                return None
        self.consecutive_errors = 0
        self.last_error = None
        self.stream_healthy = True
        self._needs_recovery = False
        return result

    def _call_stt(
        self,
        phrase_time_limit: int,
        on_partial: Optional[Callable[[str], None]],
        on_level: Optional[Callable[[float], None]],
    ) -> Optional[str]:
        # on_level прокидываем только когда задан — иначе ломается контракт
        # recognize_from_mic(phrase_time_limit, callback) у старых вызовов.
        kwargs: dict[str, Any] = {
            "phrase_time_limit": phrase_time_limit,
            "callback": on_partial,
        }
        if on_level is not None:
            kwargs["on_level"] = on_level
        return self.stt.recognize_from_mic(**kwargs)

    def _recover(self) -> bool:
        """Остановить и поднять STT заново с экспоненциальным backoff.

        Возвращает True если поток жив. Не бросает исключений наружу:
        исчерпание попыток переводит пайплайн в деградированный режим
        (stream_healthy=False), сервис продолжает работать без микрофона.
        """
        delay = self.reconnect_base_delay
        for attempt in range(1, self.max_reconnect_attempts + 1):
            try:
                self.stop()
            except Exception:
                pass
            try:
                self.start()
            except Exception as e:
                logger.warning(
                    f"🔁 Реконнект STT {attempt}/{self.max_reconnect_attempts} "
                    f"не удался: {e}"
                )
            if self.stt is not None and self._started:
                self.consecutive_errors = 0
                self.last_error = None
                self.stream_healthy = True
                self._needs_recovery = False
                logger.info("✅ STT поток восстановлен")
                return True
            if attempt < self.max_reconnect_attempts:
                self._sleep(delay)
                delay = min(delay * 2, self.reconnect_max_delay)
        self.stream_healthy = False
        self._needs_recovery = True
        logger.error(
            f"❌ STT не восстановлен за {self.max_reconnect_attempts} попыток "
            f"(last: {self.last_error})"
        )
        return False

    def stop(self) -> None:
        if self.stt:
            try:
                self.stt.close()
            except Exception:
                pass
        self.stt = None
        self._started = False
        # Счётчики здоровья НЕ сбрасываем: stop() вызывается и внутри
        # _recover(), где затирание last_error ломало бы диагностику.
        # Сброс — только при успехе (recognize/_recover).
        self._needs_recovery = False
