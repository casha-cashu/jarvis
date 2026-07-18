#!/usr/bin/env python3
"""
Text-to-Speech module using Piper TTS
Синтез речи (офлайн, быстрый)
"""

import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional

from jarvis._env import sanitized_env

logger = logging.getLogger(__name__)


def _auto_detect_piper_lib_path() -> Optional[str]:
    """Пробует найти libpiper.so / libonnxruntime.so без hardcoded Steam-пути.

    Порядок проверки:
      1. ldconfig -p — каноничный источник на glibc/Linux
      2. Стандартные системные пути
      3. Директория, где лежит бинарь piper (часто там же лежат и .so)
      4. Hardcoded Steam Proton path (старый fallback, исторически
         использовался на Arch/CachyOS)

    Возвращает путь к директории, содержащей libpiper.so / libonnxruntime.so,
    или None если ничего не нашли.
    """
    # 1. ldconfig
    if shutil.which("ldconfig"):
        try:
            res = subprocess.run(
                ["ldconfig", "-p"],
                capture_output=True,
                text=True,
                timeout=3,
                env=sanitized_env(),
            )
            for line in res.stdout.splitlines():
                # Format: "libpiper.so (libc6,x86-64) => /usr/lib/libpiper.so"
                if "libpiper" in line or "libonnxruntime" in line:
                    if "=>" in line:
                        so_path = line.split("=>", 1)[1].strip()
                        parent = str(Path(so_path).parent)
                        logger.info(f"🔍 piper lib found via ldconfig: {parent}")
                        return parent
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    # 2. Стандартные пути
    candidates = [
        Path("/usr/lib"),
        Path("/usr/local/lib"),
        Path("/usr/lib/x86_64-linux-gnu"),
        Path("/usr/local/lib/x86_64-linux-gnu"),
        Path("/opt/piper/lib"),
    ]
    # 3. Папка piper-бинаря
    piper_bin = shutil.which("piper")
    if piper_bin:
        candidates.insert(0, Path(piper_bin).parent)

    for d in candidates:
        if not d.is_dir():
            continue
        if any(
            (d / name).exists()
            for name in ("libpiper.so", "libonnxruntime.so", "libonnxruntime.so.1")
        ):
            logger.info(f"🔍 piper lib found in standard path: {d}")
            return str(d)

    # 4. Steam Proton — историческая совместимость
    steam = Path(
        "/usr/share/steam/compatibilitytools.d/proton-ge-custom/files/lib/x86_64-linux-gnu"
    )
    if steam.is_dir():
        logger.info(f"🔍 piper lib falling back to Steam path: {steam}")
        return str(steam)

    return None


class PiperTTS:
    """Piper TTS для синтеза речи"""

    def __init__(
        self,
        model_path: str,
        config_path: Optional[str] = None,
        binary_path: str = "piper",
        lib_path: Optional[str] = None,
        speaker_id: int = 0,
        length_scale: float = 1.0,
    ):
        """
        Args:
            model_path: Путь к .onnx модели Piper
            config_path: Путь к .json конфигу (если None, ищет рядом с моделью)
            binary_path: Путь к бинарнику piper (по умолчанию ищет в PATH)
            lib_path: Путь к библиотекам для LD_LIBRARY_PATH
            speaker_id: ID голоса (для мультиголосовых моделей)
            length_scale: Скорость речи (1.0 = норма, <1 = быстрее, >1 = медленнее)
        """
        self.model_path = Path(model_path)
        self.binary_path = binary_path
        self.speaker_id = speaker_id
        self.length_scale = length_scale

        # P13: lib_path может быть не задан или указывать на несуществующий
        # путь (как старый Steam Proton в дефолтном config.yaml). Пробуем
        # авто-детект перед тем как сдаваться.
        if lib_path and Path(lib_path).is_dir():
            self.lib_path = lib_path
        else:
            detected = _auto_detect_piper_lib_path()
            if detected:
                self.lib_path = detected
            else:
                if lib_path:
                    logger.warning(
                        "lib_path %s не существует и авто-детект ничего не нашёл; "
                        "piper попробует системный loader",
                        lib_path,
                    )
                self.lib_path = None

        # Проверяем модель
        if not self.model_path.exists():
            raise FileNotFoundError(f"Модель Piper не найдена: {model_path}")

        # Ищем конфиг
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = self.model_path.with_suffix(".onnx.json")

        if not self.config_path.exists():
            logger.warning(f"⚠️ Конфиг не найден: {self.config_path}")
            self.config_path = None

        # Проверяем наличие piper
        try:
            env = self._get_env()
            result = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
            logger.info(f"✅ Piper TTS: {result.stdout.strip()}")
        except FileNotFoundError:
            logger.error(f"❌ piper не найден: {self.binary_path}")
            raise
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки Piper: {e}")

    def _get_env(self):
        """Возвращает sanitized env + LD_LIBRARY_PATH для piper.

        ``sanitized_env`` гарантирует, что API ключи (ANTHROPIC_API_KEY,
        OPENROUTER_API_KEY, …) НЕ попадают в окружение piper-процесса.
        """
        import os

        extra = {}
        if self.lib_path:
            current_ld = os.environ.get("LD_LIBRARY_PATH", "")
            extra["LD_LIBRARY_PATH"] = (
                f"{self.lib_path}:{current_ld}" if current_ld else self.lib_path
            )
        return sanitized_env(extra=extra)

    def speak(
        self, text: str, output_file: Optional[str] = None, play: bool = True
    ) -> bool:
        """
        Синтезирует и воспроизводит речь

        Args:
            text: Текст для озвучки
            output_file: Путь для сохранения WAV (если None, используется temp)
            play: Воспроизвести сразу

        Returns:
            True если успешно
        """
        if not text.strip():
            return False

        try:
            # Создаём временный файл если не указан
            if output_file:
                wav_file = Path(output_file)
            else:
                # Создаём директорию если не существует
                temp_dir = Path("/tmp/jarvis")
                temp_dir.mkdir(parents=True, exist_ok=True)

                temp_file = tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False, dir=temp_dir
                )
                wav_file = Path(temp_file.name)
                temp_file.close()

            # Команда piper
            cmd = [
                self.binary_path,
                "--model",
                str(self.model_path),
                "--output_file",
                str(wav_file),
                "--length_scale",
                str(self.length_scale),
            ]

            if self.config_path:
                cmd.extend(["--config", str(self.config_path)])

            if self.speaker_id > 0:
                cmd.extend(["--speaker", str(self.speaker_id)])

            # Запускаем piper с правильным окружением
            env = self._get_env()
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env=env,
            )

            process.communicate(input=text)

            if process.returncode != 0:
                logger.error(f"❌ Piper вернул код {process.returncode}")
                return False

            # Воспроизводим
            if play:
                self._play_audio(wav_file)

            # Удаляем временный файл
            if not output_file:
                try:
                    wav_file.unlink()
                except OSError:
                    pass

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка TTS: {e}")
            return False

    def _play_audio(self, audio_file: Path):
        """Воспроизводит аудио файл"""
        # Пробуем разные плееры
        players = [
            ["mpv", "--really-quiet", str(audio_file)],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_file)],
            ["aplay", str(audio_file)],
            ["paplay", str(audio_file)],
        ]

        for player_cmd in players:
            try:
                subprocess.run(
                    player_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    check=True,
                    env=sanitized_env(),
                )
                return
            except (
                FileNotFoundError,
                subprocess.TimeoutExpired,
                subprocess.CalledProcessError,
            ):
                continue

        logger.error("❌ Не найден аудио плеер (mpv/ffplay/aplay/paplay)")


class GTTSFallback:
    """Fallback на Google TTS если Piper не работает"""

    def __init__(self, lang: str = "ru", slow: bool = False):
        self.lang = lang
        self.slow = slow

        try:
            from gtts import gTTS

            self.gTTS = gTTS
            logger.info("✅ gTTS доступен как fallback")
        except ImportError:
            logger.warning("⚠️ gTTS не установлен")
            self.gTTS = None

    def speak(self, text: str, play: bool = True) -> bool:
        """Синтезирует речь через Google TTS"""
        if not self.gTTS or not text.strip():
            return False

        # Создаём директорию если не существует
        temp_dir = Path("/tmp/jarvis")
        temp_dir.mkdir(parents=True, exist_ok=True)

        temp_file = tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False,
            dir=temp_dir,
        )
        temp_path = Path(temp_file.name)
        temp_file.close()

        # P17: cleanup в finally — раньше leak случался при двух сценариях:
        # (1) play=False (см. старую реализацию) — cleanup был внутри
        #     if play и не вызывался,
        # (2) исключение в gTTS.save / mpv — cleanup пропускался по обычному
        #     потоку и обрывался except'ом.
        try:
            tts = self.gTTS(text=text, lang=self.lang, slow=self.slow)
            tts.save(str(temp_path))

            if play:
                subprocess.run(
                    ["mpv", "--really-quiet", str(temp_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    env=sanitized_env(),
                )

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка gTTS: {e}")
            return False
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


class SpeechT5TTS:
    """SpeechT5 TTS (голос Джарвиса из фильма) — lazy loading"""

    def __init__(
        self,
        model_name: str = "aaryansr/speecht5_tts_jarvis",
        vocoder_path: Optional[str] = None,
        device: Optional[str] = None,
        speaker_id: int = 0,
    ):
        """
        Args:
            model_name: HuggingFace модель или локальный путь
            vocoder_path: Локальный путь к HiFi-GAN (если None, качает с HF)
            device: cpu/cuda (auto-detect если None)
            speaker_id: ID speaker embedding
        """
        self.model_name = model_name
        self.vocoder_path_param = vocoder_path
        self.speaker_id = speaker_id
        self.device = device or "cpu"
        self.logger = logging.getLogger(__name__)

        # Lazy: модели загружаются при первом speak()
        self._model = None
        self._processor = None
        self._vocoder = None
        self._speaker_embeddings = None

        self.logger.info(f"🎙️ SpeechT5 зарегистрирован (lazy load): {model_name}")

    def _load_models(self):
        """Lazy loading моделей — вызывается при первом speak()"""
        # P16: предупреждаем пользователя ДО блокирующего скачивания.
        # Без этого UX выглядит как «ассистент завис» на 30+ секунд
        # при первом обращении (модели весят ~500MB).
        self.logger.info(
            "🎙️ Загрузка SpeechT5 (~500MB)... первый запуск может занять минуту, "
            "после кеша HuggingFace будет мгновенно."
        )
        print("🎙️ Загружаю SpeechT5 (~500MB)... подождите, сэр.", flush=True)

        try:
            import torch
            from transformers import (
                SpeechT5Processor,
                SpeechT5ForTextToSpeech,
                SpeechT5HifiGan,
            )
        except ImportError:
            raise ImportError("Установи: pip install transformers torch soundfile")

        self.logger.info(f"🎙️ Загрузка модели {self.model_name}...")
        self._processor = SpeechT5Processor.from_pretrained(self.model_name)
        self._model = SpeechT5ForTextToSpeech.from_pretrained(
            self.model_name, torch_dtype=torch.float32
        ).to(self.device)

        vocoder_path = self.vocoder_path_param or "microsoft/speecht5_hifigan"
        self.logger.info(f"🎙️ Загрузка HiFi-GAN vocoder: {vocoder_path}")
        self._vocoder = SpeechT5HifiGan.from_pretrained(
            vocoder_path, torch_dtype=torch.float32
        ).to(self.device)

        self._speaker_embeddings = torch.zeros((1, 512)).to(self.device)
        self.logger.info(f"✅ SpeechT5 готов ({self.device})")

    def speak(self, text: str, play: bool = True) -> bool:
        """Синтезирует речь голосом Джарвиса (lazy load при первом вызове)"""
        if not text.strip():
            return False

        # Lazy loading
        if self._model is None:
            self._load_models()

        try:
            import torch
            import soundfile as sf
            import tempfile
            import subprocess
            from pathlib import Path

            inputs = self._processor(text=text, return_tensors="pt").to(self.device)
            speech = self._model.generate_speech(
                inputs["input_ids"], self._speaker_embeddings, vocoder=self._vocoder
            )

            if isinstance(speech, torch.Tensor):
                speech = speech.cpu().numpy()

            # Сохраняем и играем
            temp_dir = Path("/tmp/jarvis")
            temp_dir.mkdir(parents=True, exist_ok=True)

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=temp_dir)
            sf.write(tmp.name, speech, samplerate=16000)
            tmp.close()

            if play:
                players = [
                    ["mpv", "--really-quiet", tmp.name],
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp.name],
                    ["aplay", tmp.name],
                    ["paplay", tmp.name],
                ]
                import subprocess

                for cmd in players:
                    try:
                        subprocess.run(
                            cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=30,
                            check=True,
                            env=sanitized_env(),
                        )
                        break
                    except (
                        FileNotFoundError,
                        subprocess.TimeoutExpired,
                        subprocess.CalledProcessError,
                    ):
                        continue

            Path(tmp.name).unlink(missing_ok=True)
            return True

        except Exception as e:
            self.logger.error(f"❌ SpeechT5: {e}")
            return False


class TTSManager:
    """Менеджер TTS с автоматическим fallback"""

    def __init__(self, config: dict):
        """
        Args:
            config: Словарь с настройками из config.yaml['tts']
        """
        self.engine = config.get("engine", "piper")
        self.primary = None
        self.fallback = None

        # Инициализируем основной движок
        if self.engine == "piper":
            try:
                piper_config = config.get("piper", {})
                self.primary = PiperTTS(
                    model_path=piper_config.get("model_path"),
                    config_path=piper_config.get("config_path"),
                    binary_path=piper_config.get("binary_path", "piper"),
                    lib_path=piper_config.get("lib_path"),
                    speaker_id=piper_config.get("speaker_id", 0),
                    length_scale=piper_config.get("length_scale", 1.0),
                )
                logger.info("✅ Основной TTS: Piper")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации Piper: {e}")

        elif self.engine == "speecht5":
            try:
                st5_config = config.get("speecht5", {})
                self.primary = SpeechT5TTS(
                    model_name=st5_config.get("model", "aaryansr/speecht5_tts_jarvis"),
                    vocoder_path=st5_config.get("vocoder_path"),
                    device=st5_config.get("device"),
                    speaker_id=st5_config.get("speaker_id", 0),
                )
                logger.info("✅ Основной TTS: SpeechT5 (голос Джарвиса)")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации SpeechT5: {e}")

        # Инициализируем fallback
        try:
            gtts_config = config.get("gtts", {})
            self.fallback = GTTSFallback(
                lang=gtts_config.get("lang", "ru"), slow=gtts_config.get("slow", False)
            )
            logger.info("✅ Fallback TTS: gTTS")
        except Exception as e:
            logger.warning(f"⚠️ Fallback TTS недоступен: {e}")

    def speak(self, text: str) -> bool:
        """
        Озвучивает текст (пробует primary, потом fallback)

        Args:
            text: Текст для озвучки

        Returns:
            True если успешно
        """
        if not text.strip():
            return False

        # Пробуем основной
        if self.primary:
            try:
                if self.primary.speak(text):
                    return True
            except Exception as e:
                logger.warning(f"⚠️ Основной TTS не сработал: {e}")

        # Пробуем fallback
        if self.fallback:
            try:
                return self.fallback.speak(text)
            except Exception as e:
                logger.error(f"❌ Fallback TTS не сработал: {e}")

        logger.error("❌ Все TTS движки недоступны")
        return False
