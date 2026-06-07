#!/usr/bin/env python3
"""
JARVIS — главный класс голосового ассистента.
"""

import os
import re
import sys
import yaml
import shlex
import logging
import signal
import time
import json
from pathlib import Path
from typing import Optional, Callable

from jarvis.modules.stt import VoskSTT
from jarvis.modules.tts import TTSManager
from jarvis.modules.llm import LLMManager
from jarvis.modules.commands import CommandManager


def setup_logging(config: dict, verbose: bool = False):
    """Настраивает логирование"""
    log_config = config.get('logging', {})
    log_file = log_config.get('file', 'logs/jarvis.log')
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    log_level = logging.DEBUG if verbose else getattr(logging, log_config.get('level', 'INFO'))

    file_fmt = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_fmt = logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S'
    ) if verbose else logging.Formatter('%(message)s')

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(file_fmt)
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(console_fmt)
    ch.setLevel(log_level)
    root.addHandler(ch)

    for noisy in ['vosk', 'torch', 'urllib3', 'anthropic']:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def beep():
    """Короткий звуковой сигнал при wake word"""
    print('\a', end='', flush=True)
    sound = os.getenv('JARVIS_WAKE_SOUND', '')
    if sound and Path(sound).exists():
        import subprocess
        subprocess.Popen(['paplay', sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Jarvis:
    """Голосовой ассистент JARVIS"""

    def __init__(self, config_path: str = 'config.yaml',
                 verbose: bool = False,
                 provider: Optional[str] = None,
                 provider_config: Optional[dict] = None,
                 continuous: bool = False,
                 muted: bool = False,
                 wake_mode: str = 'classic',
                 dry_run: bool = False):
        self.verbose = verbose
        self.continuous = continuous
        self.muted = muted
        self.wake_mode = wake_mode
        self.dry_run = dry_run

        # Загрузка конфига
        self.config_path = Path(config_path)
        if not self.config_path.is_absolute():
            self.config_path = Path.cwd() / config_path
        self.config = self._load_config(str(self.config_path))

        # Логирование
        setup_logging(self.config, verbose)
        self.logger = logging.getLogger(__name__)

        self.logger.info("=" * 50)
        self.logger.info("   JARVIS - Голосовой ассистент")
        self.logger.info("=" * 50)

        if provider and provider_config:
            self.config['llm']['provider'] = provider
            self.config['llm'][provider] = provider_config
            self.logger.info(f"  Провайдер: {provider} ({provider_config.get('model', '?')})")
        elif provider:
            self.config['llm']['provider'] = provider
            self.logger.info(f"  Провайдер: {provider}")

        # Temp dir
        Path(self.config.get('misc', {}).get('temp_dir', '/tmp/jarvis')).mkdir(parents=True, exist_ok=True)

        # Состояние
        self.stt = None
        self.tts = None
        self.llm = None
        self.commands = None
        self.reminder_mgr = None
        self.running = False
        self.is_muted = muted
        self.last_speech_time = 0

        if self.continuous:
            self.logger.info("  Режим: continuous (без wake word)")
        if self.muted:
            self.logger.info("  Режим: тишина (скажи 'джарвис проснись')")
        if self.dry_run:
            self.logger.info("  Режим: dry-run (проверка без микрофона)")
        if self.wake_mode == 'vad':
            self.logger.info("  Wake mode: VAD-буфер")

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _load_config(self, config_path: str) -> dict:
        """Загружает конфиг с подстановкой переменных окружения и валидацией"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            config = self._expand_env_vars(config)
            # Валидация через pydantic-схему
            try:
                from jarvis.config_schema import validate_config
                config = validate_config(config)
            except ImportError:
                self.logger.debug("config_schema не найден, пропускаю валидацию")
            return config
        except Exception as e:
            print(f"❌ Ошибка загрузки конфига {config_path}: {e}")
            sys.exit(1)

    def _expand_env_vars(self, obj):
        """Подставляет ${VAR} из окружения и расширяет ~"""
        if isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            for var in re.findall(r'\$\{([^}]+)\}', obj):
                obj = obj.replace(f'${{{var}}}', os.getenv(var, ''))
            if '$HOME' in obj:
                obj = obj.replace('$HOME', os.path.expanduser('~'))
            if obj.startswith('~/'):
                obj = os.path.expanduser(obj)
            return obj
        return obj

    def _signal_handler(self, signum, frame):
        self.logger.info(f"\n🛑 Получен сигнал {signum}")
        self.running = False

    def initialize(self):
        """Инициализация всех модулей"""
        try:
            self.logger.info("🎤 Инициализация STT...")
            stt_cfg = self.config.get('stt', {})
            audio_cfg = self.config.get('audio', {})
            vad_cfg = self.config.get('vad', {})
            sample_rate = stt_cfg.get('sample_rate', 16000)
            engine = stt_cfg.get('engine', 'vosk')

            if engine == 'whisper':
                from jarvis.modules.stt_whisper import WhisperSTT
                wcfg = stt_cfg.get('whisper', {})
                self.stt = WhisperSTT(
                    model_size=wcfg.get('model_size', 'tiny'),
                    model_path=wcfg.get('model_path') or None,
                    sample_rate=sample_rate,
                    device_name=audio_cfg['microphone']['device_name'],
                    use_vad=vad_cfg.get('enabled', True),
                    vad_threshold=vad_cfg.get('silero', {}).get('threshold', 0.5)
                )
            else:
                self.stt = VoskSTT(
                    model_path=stt_cfg['vosk']['model_path'],
                    sample_rate=sample_rate,
                    device_name=audio_cfg['microphone']['device_name'],
                    use_vad=vad_cfg.get('enabled', True),
                    vad_threshold=vad_cfg.get('silero', {}).get('threshold', 0.5)
                )

            if not self.dry_run:
                self.stt.list_devices()

            self.logger.info("🔊 Инициализация TTS...")
            self.tts = TTSManager(self.config.get('tts', {}))

            # Платформа (для system prompt и адаптеров)
            from jarvis.modules.platform_adapter import PlatformAdapter
            self.platform = PlatformAdapter()

            self.logger.info("🧠 Инициализация LLM...")
            llm_cfg = self.config.get('llm', {})
            platform_str = f"{self.platform.os}"
            if self.platform.distro:
                platform_str += f"/{self.platform.distro}"
            if self.platform.de:
                platform_str += f" ({self.platform.de})"
            if 'system_prompt' in llm_cfg:
                llm_cfg['system_prompt'] = llm_cfg['system_prompt'].replace(
                    '{platform}', platform_str
                )
            self.llm = LLMManager(llm_cfg)

            self.logger.info("⚡ Инициализация Commands...")
            self.commands = CommandManager(self.config)

            self.logger.info("✅ Все модули инициализированы")
            if self.dry_run:
                print("\n🧪 Dry-run: попробую тестовый запрос к LLM...")
                resp = self.llm.chat("Ответь OK")
                print(f"   LLM ответ: {resp}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации: {e}")
            if self.dry_run:
                print(f"   ❌ {e}")
            raise

    def run(self):
        """Главный цикл работы"""
        if self.dry_run:
            print("\n✅ Dry-run завершён успешно!")
            return

        self.running = True

        if not self.verbose:
            mode = "без wake word" if self.continuous else "wake word"
            print("\n" + "=" * 50)
            print("   🤖 JARVIS — голосовой ассистент")
            print(f"   Режим: {mode}")
            if self.is_muted:
                print("   🔇 Режим тишины")
            print("=" * 50 + "\n")

        self._speak("Система готова. Я на связи, сэр.")

        wake_word = self.config['stt'].get('wake_word', 'джарвис')
        wake_alts = self.config['stt'].get('wake_word_alternatives', [])
        all_wake = [wake_word] + wake_alts
        multi_turn_timeout = self.config.get('stt', {}).get('multi_turn_timeout', 10)
        phrase_limit = self.config.get('stt', {}).get('phrase_time_limit', 10)

        self.logger.info(f"🎤 Wake word: {', '.join(all_wake)}")

        # VAD-based wake word: rolling buffer
        wake_buffer = []
        vad_enabled = self.config.get('vad', {}).get('enabled', False)
        use_vad_wake = (self.wake_mode == 'vad' and vad_enabled)

        # Reminder manager (атрибут для shutdown)
        from jarvis.modules.reminder import ReminderManager
        self.reminder_mgr = ReminderManager(on_trigger=self._on_reminder)

        while self.running:
            try:
                if self.is_muted:
                    print(f"\r🔇 Режим тишины (скажи 'проснись')", end='', flush=True)
                    text = self._listen_for_unmute(phrase_limit, all_wake)
                    if text:
                        self.is_muted = False
                        self._speak("Я слушаю, сэр.")
                    continue

                if self.continuous:
                    text = self._listen_continuous(phrase_limit)
                else:
                    text = self._listen_with_wake(
                        phrase_limit, all_wake,
                        use_vad_wake, wake_buffer
                    )

                if not text:
                    continue

                self.logger.info(f"👤 Запрос: {text}")

                # Обработка специальных маркеров
                response = self._process_special(text)
                if response is not None:
                    if response:
                        self._speak(response)
                    continue

                # Обработка запроса
                response = self.process_query(text)

                if response:
                    self.logger.info(f"🤖 Джарвис: {response}")

                # Multi-turn
                if response and not self.continuous:
                    self._speak(response)
                    self.last_speech_time = time.time()
                    follow_up = self._listen_follow_up(
                        multi_turn_timeout, phrase_limit
                    )
                    while follow_up:
                        self.logger.info(f"👤 Follow-up: {follow_up}")
                        resp2 = self.process_query(follow_up)
                        if resp2:
                            self._speak(resp2)
                        else:
                            break
                        follow_up = self._listen_follow_up(
                            multi_turn_timeout, phrase_limit
                        )

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"❌ Ошибка: {e}")
                continue

        self.shutdown()

    def _process_special(self, text: str):
        """
        Обрабатывает специальные маркеры из команд:
          __MUTE__, __UNMUTE__, __DICTATE__,
          __REMINDER__:..., __REMINDER_LIST__, __EXIT__
        """
        lower = text.lower().strip()

        if not hasattr(self, 'commands') or self.commands is None:
            return None

        parsed = self.commands.executor.parse_voice_command(lower)

        if parsed == '__MUTE__':
            self.is_muted = True
            return "Хорошо, сэр. Я замолкаю."

        if parsed == '__UNMUTE__':
            self.is_muted = False
            return "Я снова слушаю, сэр."

        if parsed == '__EXIT__':
            self.running = False
            return "Завершаю работу, сэр."

        if parsed == '__DICTATE__':
            self._speak("Включаю режим диктовки. Говорите текст.")
            from jarvis.modules.dictation import dictation_loop
            try:
                dictation_loop(self.stt, on_text=self._on_dictation_text)
                return "Диктовка завершена."
            except Exception as e:
                self.logger.error(f"❌ Dictation: {e}")
                return "Ошибка диктовки."

        if parsed and parsed.startswith('__REMINDER__:'):
            parts = parsed.split(':', 2)
            if len(parts) == 3:
                _, seconds_str, reminder_text = parts
                try:
                    seconds = int(seconds_str)
                    if self.reminder_mgr:
                        return self.reminder_mgr.add(reminder_text, seconds)
                except ValueError:
                    pass
            return "Не удалось установить напоминание."

        if parsed == '__REMINDER_LIST__':
            from jarvis.modules.reminder import ReminderManager
            reminders = ReminderManager.list_active()
            if reminders:
                lines = [f"  • «{t}» — через {s} сек" for t, s in reminders]
                return "Активные напоминания:\n" + "\n".join(lines)
            else:
                return "Нет активных напоминаний."

        return None

    def _on_reminder(self, text: str):
        """Callback при срабатывании напоминания — TTS + notify"""
        self._speak(f"Напоминаю: {text}")
        try:
            import subprocess
            subprocess.Popen(
                shlex.split(self.platform.notify('🔔 Напоминание JARVIS', text)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _on_dictation_text(self, text: str):
        """Callback при получении сегмента диктовки"""
        self.logger.info(f"📝 Диктовка: {text}")

    def _speak(self, text: str):
        """Произносит текст и выводит в консоль"""
        print(f"\r🤖 {text}")
        if self.tts:
            self.tts.speak(text)

    def _listen_for_unmute(self, phrase_limit: int, wake_words: list) -> Optional[str]:
        text = self._recognize(phrase_limit)
        if text:
            lower = text.lower()
            for w in ['проснись', 'джарвис', 'хай']:
                if w in lower:
                    return text
        return None

    def _listen_with_wake(self, phrase_limit: int, wake_words: list,
                           use_vad_wake: bool, wake_buffer: list) -> Optional[str]:
        if not self.verbose:
            print(f"\r💤 Жду 'джарвис'...", end='', flush=True)

        text = self._recognize(phrase_limit)
        if not text:
            return None

        lower = text.lower()
        for wake in wake_words:
            if wake in lower:
                beep()
                query = lower.replace(wake, '', 1).strip()
                self.logger.info(f"🗣️ Wake word detected: {wake}")

                if not query:
                    self._speak("Слушаю вас, сэр.")
                    retry = self._recognize(phrase_limit)
                    if retry:
                        return retry.lower()
                    return None
                return query

        return None

    def _listen_continuous(self, phrase_limit: int) -> Optional[str]:
        if not self.verbose:
            print(f"\r🎤 Слушаю...", end='', flush=True)
        return self._recognize(phrase_limit)

    def _listen_follow_up(self, timeout: int, phrase_limit: int) -> Optional[str]:
        print(f"\r💬 Жду продолжение ({timeout}с)...", end='', flush=True)
        text = self._recognize(min(phrase_limit, timeout))
        if text:
            lower = text.lower()
            all_wake = [self.config['stt'].get('wake_word', 'джарвис')] + self.config['stt'].get('wake_word_alternatives', [])
            for wake in all_wake:
                if wake in lower:
                    self.logger.debug("⏭️ Follow-up прерван — новый wake word")
                    return None
            for wake in all_wake:
                if wake in lower:
                    cleaned = lower.replace(wake, '', 1).strip()
                    if cleaned:
                        return cleaned
                    return None
            return text
        return None

    def _recognize(self, phrase_limit: int) -> Optional[str]:
        try:
            return self.stt.recognize_from_mic(
                phrase_time_limit=phrase_limit,
                callback=self._on_partial
            )
        except Exception as e:
            self.logger.error(f"❌ STT ошибка: {e}")
            return None

    def _on_partial(self, text: str):
        if self.verbose:
            self.logger.debug(f"📝 {text}")
        else:
            cleaned = text[:60]
            print(f"\r🎤 {cleaned:<60}", end='', flush=True)

    def process_query(self, query: str) -> str:
        """Обрабатывает запрос пользователя — единый pipeline."""
        cmd_resp = self.commands.process(query)
        if cmd_resp is not None:
            if cmd_resp.startswith('__'):
                return ""
            return cmd_resp if cmd_resp else "Готово, сэр."

        try:
            return self.llm.chat(query) or ""
        except Exception as e:
            self.logger.error(f"❌ LLM: {e}")
            return "Извините, сэр, произошла ошибка."

    def shutdown(self):
        """Корректное завершение"""
        self.logger.info("🛑 Завершение...")
        if self.reminder_mgr:
            self.reminder_mgr.shutdown()
        self._speak("До свидания, сэр.")
        if self.stt:
            self.stt.close()
        self.logger.info("👋 JARVIS остановлен")
