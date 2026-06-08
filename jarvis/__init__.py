#!/usr/bin/env python3
"""JARVIS — thin orchestrator over modular pipelines.

Этот модуль НЕ должен делать ничего сам — он только связывает
config_loader / audio_pipeline / response_pipeline / conversation_manager
/ lifecycle. Любая логика, которая «пухнет» здесь, должна уходить
в соответствующий компонент.
"""

from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from jarvis._env import sanitized_env
from jarvis.audio_pipeline import AudioPipeline
from jarvis.config_loader import ConfigLoader
from jarvis.conversation_manager import ConversationManager
from jarvis.lifecycle import LifecycleManager
from jarvis.response_pipeline import ResponsePipeline


def setup_logging(config: dict, verbose: bool = False) -> None:
    log_config = config.get('logging', {})
    log_file = log_config.get('file', 'logs/jarvis.log')
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    log_level = logging.DEBUG if verbose else getattr(
        logging, log_config.get('level', 'INFO')
    )

    file_fmt = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    console_fmt = (
        logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
        if verbose else logging.Formatter('%(message)s')
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    # P14: log rotation honours config.logging.max_size / backup_count
    max_size = int(log_config.get('max_size', 10 * 1024 * 1024))
    backup_count = int(log_config.get('backup_count', 5))
    fh = RotatingFileHandler(
        log_file, maxBytes=max_size, backupCount=backup_count, encoding='utf-8',
    )
    fh.setFormatter(file_fmt)
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(console_fmt)
    ch.setLevel(log_level)
    root.addHandler(ch)

    for noisy in ('vosk', 'torch', 'urllib3', 'anthropic'):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def beep() -> None:
    """Короткий звуковой сигнал при wake word."""
    print('\a', end='', flush=True)
    sound = os.getenv('JARVIS_WAKE_SOUND', '')
    if sound and Path(sound).exists():
        import subprocess
        subprocess.Popen(
            ['paplay', sound],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=sanitized_env(),
        )


class Jarvis:
    """Тонкий оркестратор. Состав: ConfigLoader, AudioPipeline,
    ResponsePipeline, ConversationManager, LifecycleManager."""

    def __init__(self,
                 config_path: str = 'config.yaml',
                 verbose: bool = False,
                 provider: Optional[str] = None,
                 provider_config: Optional[dict] = None,
                 continuous: bool = False,
                 muted: bool = False,
                 wake_mode: str = 'classic',
                 dry_run: bool = False):
        self.verbose = verbose
        self.continuous = continuous
        self.wake_mode = wake_mode
        self.dry_run = dry_run

        self.config = self._load_config(config_path)
        setup_logging(self.config, verbose)
        self.logger = logging.getLogger(__name__)

        self.logger.info("=" * 50)
        self.logger.info("   JARVIS - Голосовой ассистент")
        self.logger.info("=" * 50)

        if provider and provider_config:
            self.config['llm']['provider'] = provider
            self.config['llm'][provider] = provider_config
            self.logger.info(
                f"  Провайдер: {provider} ({provider_config.get('model', '?')})"
            )
        elif provider:
            self.config['llm']['provider'] = provider
            self.logger.info(f"  Провайдер: {provider}")

        Path(self.config.get('misc', {}).get('temp_dir', '/tmp/jarvis')).mkdir(
            parents=True, exist_ok=True,
        )

        wake_word = self.config.get('stt', {}).get('wake_word', 'джарвис')
        wake_alts = self.config.get('stt', {}).get('wake_word_alternatives', [])
        self.conversation = ConversationManager(
            wake_words=[wake_word] + list(wake_alts), muted=muted,
        )
        self.audio = AudioPipeline(self.config, dry_run=dry_run)
        self.response = ResponsePipeline(self.config)
        self.lifecycle = LifecycleManager()

        # Аттрибуты, на которые опираются тесты / public API
        self.stt = None
        self.tts = None
        self.llm = None
        self.commands = None
        self.platform = None
        self.reminder_mgr = None
        self.running = False
        self.last_speech_time = 0.0
        self.is_muted = muted

        if self.continuous:
            self.logger.info("  Режим: continuous (без wake word)")
        if muted:
            self.logger.info("  Режим: тишина (скажи 'джарвис проснись')")
        if self.dry_run:
            self.logger.info("  Режим: dry-run (проверка без микрофона)")
        if self.wake_mode == 'vad':
            self.logger.info("  Wake mode: VAD-буфер")

        self.lifecycle.install_signal_handlers(self._on_signal)

    # ── Public API хвостовые методы (для тестов и обратной совместимости) ──

    def _load_config(self, config_path: str) -> dict:
        """Делегация в ConfigLoader. Метод оставлен как hook для
        ``patch.object(Jarvis, '_load_config', ...)`` в conftest.py."""
        return ConfigLoader(config_path).load()

    def initialize(self) -> None:
        """Поднимает аудио + response pipelines."""
        try:
            self.logger.info("🎤 Инициализация STT...")
            self.audio.start()
            self.stt = self.audio.stt

            self.logger.info("🔊 Инициализация TTS/LLM/Commands...")
            self.response.start()
            self.tts = self.response.tts
            self.llm = self.response.llm
            self.commands = self.response.commands
            self.platform = self.response.platform

            self.lifecycle.register(self.audio, self.response)

            self.logger.info("✅ Все модули инициализированы")
            if self.dry_run:
                print("\n🧪 Dry-run: попробую тестовый запрос к LLM...")
                try:
                    resp = self.llm.chat("Ответь OK") if self.llm else None
                    print(f"   LLM ответ: {resp}")
                except Exception as e:
                    print(f"   ❌ {e}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации: {e}")
            if self.dry_run:
                print(f"   ❌ {e}")
            raise

    def run(self) -> None:
        if self.dry_run:
            print("\n✅ Dry-run завершён успешно!")
            return

        self.running = True

        if not self.verbose:
            mode = "без wake word" if self.continuous else "wake word"
            print("\n" + "=" * 50)
            print("   🤖 JARVIS — голосовой ассистент")
            print(f"   Режим: {mode}")
            if self.conversation.is_muted:
                print("   🔇 Режим тишины")
            print("=" * 50 + "\n")

        self._speak("Система готова. Я на связи, сэр.")

        # Reminder manager
        from jarvis.modules.reminder import ReminderManager
        self.reminder_mgr = ReminderManager(on_trigger=self._on_reminder)
        self.lifecycle.register(self.reminder_mgr)

        multi_turn_timeout = self.config.get('stt', {}).get('multi_turn_timeout', 10)
        phrase_limit = self.config.get('stt', {}).get('phrase_time_limit', 10)
        self.logger.info(f"🎤 Wake word: {', '.join(self.conversation.wake_words)}")

        while self.running:
            try:
                if self.conversation.is_muted:
                    print(f"\r🔇 Режим тишины (скажи 'проснись')", end='', flush=True)
                    text = self._recognize(phrase_limit)
                    if text and self.conversation.is_unmute_phrase(text):
                        self.conversation.is_muted = False
                        self.is_muted = False
                        self._speak("Я слушаю, сэр.")
                    continue

                if self.continuous:
                    if not self.verbose:
                        print(f"\r🎤 Слушаю...", end='', flush=True)
                    text = self._recognize(phrase_limit)
                else:
                    if not self.verbose:
                        print(f"\r💤 Жду 'джарвис'...", end='', flush=True)
                    raw = self._recognize(phrase_limit)
                    detected, query = self.conversation.detect_wake(raw or "")
                    if not detected:
                        continue
                    beep()
                    self.logger.info("🗣️ Wake word detected")
                    if query is None:
                        self._speak("Слушаю вас, сэр.")
                        text = self._recognize(phrase_limit)
                    else:
                        text = query

                if not text:
                    continue
                self.logger.info(f"👤 Запрос: {text}")

                response = self._process_special(text)
                if response is not None:
                    if response:
                        self._speak(response)
                    continue

                response = self.process_query(text)
                if response:
                    self.logger.info(f"🤖 Джарвис: {response}")

                if response and not self.continuous:
                    self._speak(response)
                    self.last_speech_time = time.time()
                    self._multi_turn_loop(multi_turn_timeout, phrase_limit)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"❌ Ошибка: {e}")
                continue

        self.shutdown()

    # ── Внутренние помощники, оставшиеся в Jarvis из-за state-зависимости ──

    def _multi_turn_loop(self, timeout: int, phrase_limit: int) -> None:
        """P15: убрана дублирующаяся проверка wake_word после первой петли."""
        while True:
            print(f"\r💬 Жду продолжение ({timeout}с)...", end='', flush=True)
            follow_up = self._recognize(min(phrase_limit, timeout))
            if not follow_up:
                return
            if self.conversation.has_wake_in_follow_up(follow_up):
                self.logger.debug("⏭️ Follow-up прерван — новый wake word")
                return
            self.logger.info(f"👤 Follow-up: {follow_up}")
            resp = self.process_query(follow_up)
            if not resp:
                return
            self._speak(resp)

    def _recognize(self, phrase_limit: int) -> Optional[str]:
        return self.audio.recognize(phrase_limit, on_partial=self._on_partial)

    def _on_partial(self, text: str) -> None:
        if self.verbose:
            self.logger.debug(f"📝 {text}")
        else:
            print(f"\r🎤 {text[:60]:<60}", end='', flush=True)

    def _process_special(self, text: str) -> Optional[str]:
        if self.commands is None:
            return None
        parsed = self.commands.executor.parse_voice_command(text.lower().strip())

        if parsed == '__MUTE__':
            self.conversation.is_muted = True
            self.is_muted = True
            return "Хорошо, сэр. Я замолкаю."
        if parsed == '__UNMUTE__':
            self.conversation.is_muted = False
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
            _, _, rest = parsed.partition(':')
            seconds_str, _, reminder_text = rest.partition(':')
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
            return "Нет активных напоминаний."
        return None

    def _speak(self, text: str) -> None:
        self.response.speak(text)

    def process_query(self, query: str) -> str:
        return self.response.process_query(query)

    def _on_reminder(self, text: str) -> None:
        self._speak(f"Напоминаю: {text}")
        try:
            import shlex
            import subprocess
            subprocess.Popen(
                shlex.split(self.platform.notify('🔔 Напоминание JARVIS', text)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=sanitized_env(),
            )
        except Exception:
            pass

    def _on_dictation_text(self, text: str) -> None:
        self.logger.info(f"📝 Диктовка: {text}")

    def _on_signal(self) -> None:
        self.running = False

    def shutdown(self) -> None:
        self.logger.info("🛑 Завершение...")
        self.lifecycle.shutdown()
        self._speak("До свидания, сэр.")
        self.logger.info("👋 JARVIS остановлен")
