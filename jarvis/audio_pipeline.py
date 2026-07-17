"""Аудио-pipeline: микрофон → VAD → STT.

Раньше всё это инициализировалось внутри ``Jarvis.initialize`` (148+ строк
ручной возни в god class). Вынесено отдельно чтобы:
  - тесты могли заглушить STT без поднятия всего Jarvis
  - ``--dry-run`` действительно НЕ грузил модели (P8)
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Владеет инстансом STT (Vosk или Whisper) и его lifecycle'ом."""

    def __init__(self, config: dict, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.stt = None
        self._started = False

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

        if engine == "whisper":
            from jarvis.modules.stt_whisper import WhisperSTT

            wcfg = stt_cfg.get("whisper", {})
            self.stt = WhisperSTT(
                model_size=wcfg.get("model_size", "tiny"),
                model_path=wcfg.get("model_path") or None,
                sample_rate=sample_rate,
                device_name=device_name,
                use_vad=use_vad,
                vad_threshold=vad_threshold,
            )
        else:
            from jarvis.modules.stt import VoskSTT

            self.stt = VoskSTT(
                model_path=stt_cfg["vosk"]["model_path"],
                sample_rate=sample_rate,
                device_name=device_name,
                use_vad=use_vad,
                vad_threshold=vad_threshold,
            )

        self.stt.list_devices()
        self._started = True

    def recognize(
        self, phrase_time_limit: int, on_partial: Optional[Callable[[str], None]] = None
    ) -> Optional[str]:
        if self.dry_run or not self.stt:
            return None
        try:
            return self.stt.recognize_from_mic(
                phrase_time_limit=phrase_time_limit,
                callback=on_partial,
            )
        except Exception as e:
            logger.error(f"❌ STT ошибка: {e}")
            return None

    def stop(self) -> None:
        if self.stt:
            try:
                self.stt.close()
            except Exception:
                pass
        self._started = False
