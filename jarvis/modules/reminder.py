#!/usr/bin/env python3
"""
Модуль напоминаний.
Парсинг фраз типа "напомни через 10 минут позвонить",
таймер в фоне, notify-send + TTS.
"""

import re
import json
import time
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

REMINDERS_FILE = Path.home() / '.local' / 'share' / 'jarvis' / 'reminders.json'


def _load_reminders() -> list:
    """Загружает активные напоминания"""
    if REMINDERS_FILE.exists():
        try:
            return json.loads(REMINDERS_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_reminders(reminders: list):
    """Сохраняет напоминания"""
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REMINDERS_FILE.write_text(
        json.dumps(reminders, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )


def parse_time(text: str) -> Optional[tuple]:
    """
    Парсит время из текста.
    Возвращает (секунд, текст_напоминания) или None.

    Примеры:
      "через 10 минут позвонить"            → (600, "позвонить")
      "напомни через 5 секунд выключить"    → (5, "выключить")
      "поставь таймер на 10 минут"          → (600, "прошло 10 минут")
      "таймер на 5 минут"                   → (300, "прошло 5 минут")
      "напомни завтра в 9 утра собрание"    → None (не поддерживается)
    """

    # Словарь: слово → число
    NUM_WORDS = {
        'ноль': 0, 'один': 1, 'одну': 1, 'одна': 1,
        'два': 2, 'две': 2, 'три': 3, 'четыре': 4,
        'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8,
        'девять': 9, 'десять': 10,
        'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13,
        'четырнадцать': 14, 'пятнадцать': 15, 'шестнадцать': 16,
        'семнадцать': 17, 'восемнадцать': 18, 'девятнадцать': 19,
        'двадцать': 20, 'тридцать': 30, 'сорок': 40,
        'пятьдесят': 50, 'шестьдесят': 60,
    }

    UNIT_WORDS = r'(?:секунд[а-я]*|минут[а-я]*|час[а-я]*)'
    NUMBER = r'(?:\d+|' + '|'.join(NUM_WORDS.keys()) + r')'

    def _amount(s: str) -> int:
        """Парсит число из цифр или слов."""
        s = s.strip().lower()
        if s.isdigit():
            return int(s)
        return NUM_WORDS.get(s, 0)

    def _unit_multiplier(u: str) -> int:
        u = u.lower()
        if u.startswith('секунд'):
            return 1
        if u.startswith('минут'):
            return 60
        if u.startswith('час'):
            return 3600
        return 60

    text_lower = text.lower().strip()

    # Паттерны с числами (цифры или слова)
    patterns = [
        # "через 10 минут сделать что-то" / "через десять минут сделать"
        rf'(?:через|подожди)\s+({NUMBER})\s+({UNIT_WORDS})\s+(.+)$',
        # "напомни через 10 минут сделать что-то"
        rf'напомни\s+через\s+({NUMBER})\s+({UNIT_WORDS})\s+(.+)$',
        # "напомни сделать что-то через 10 минут"
        rf'напомни\s+(.+?)\s+через\s+({NUMBER})\s+({UNIT_WORDS})$',
        # "таймер на 10 минут" / "поставь таймер на 10 минут"
        rf'(?:поставь\s+)?таймер(?:а)?\s+на\s+({NUMBER})\s+({UNIT_WORDS})(?:\s*(.+))?$',
        # "через 10 минут" (без текста)
        rf'(?:через|подожди)\s+({NUMBER})\s+({UNIT_WORDS})$',
    ]

    for pat in patterns:
        m = re.search(pat, text_lower)
        if m:
            groups = m.groups()
            # Нормализуем: None → ""
            groups = tuple("" if g is None else g for g in groups)

            if len(groups) >= 2:
                amount_str = groups[0]
                unit_str = groups[1]
                # Если есть третий элемент — это текст напоминания
                reminder_text = groups[2].strip() if len(groups) > 2 and groups[2] else ""

                amount = _amount(amount_str)
                seconds = amount * _unit_multiplier(unit_str)

                if reminder_text:
                    text_clean = reminder_text.rstrip('.')
                    return (seconds, text_clean)
                return (seconds, f"прошло {amount} {unit_str}")

    return None


class ReminderManager:
    """Управление напоминаниями"""

    def __init__(self, on_trigger: Optional[Callable] = None):
        """
        Args:
            on_trigger: Функция, вызываемая при срабатывании (текст напоминания)
        """
        self.on_trigger = on_trigger or self._default_trigger
        self.timers: list = []
        self._load_active()

    def _default_trigger(self, text: str):
        """Стандартное уведомление (fallback — без PlatformAdapter)"""
        try:
            subprocess.run([
                'notify-send', '-u', 'critical',
                '🔔 Напоминание', text
            ], timeout=3)
        except Exception:
            pass
        print(f"\n⏰ Напоминание: {text}")

    def _load_active(self):
        """Загружает и запускает таймеры для активных напоминаний"""
        reminders = _load_reminders()
        now = time.time()
        for r in reminders:
            remaining = r['time'] - now
            if remaining > 0:
                t = threading.Timer(remaining, self._fire, args=[r])
                t.daemon = True
                t.start()
                self.timers.append(t)
                logger.info(f"⏰ Напоминание загружено: «{r['text']}» через {int(remaining)}с")
            else:
                # Просроченные удаляем
                logger.debug(f"⏰ Просроченное напоминание удалено: {r['text']}")
        # Сохраняем только будущие
        self._prune()

    def _prune(self):
        """Удаляет просроченные напоминания"""
        now = time.time()
        reminders = [r for r in _load_reminders() if r['time'] > now]
        _save_reminders(reminders)

    def _fire(self, reminder: dict):
        """Срабатывание напоминания"""
        text = reminder['text']
        logger.info(f"⏰ Напоминание сработало: {text}")
        self.on_trigger(text)
        self._prune()

    def add(self, text: str, seconds: int) -> str:
        """
        Добавляет напоминание.

        Args:
            text: Текст напоминания
            seconds: Через сколько секунд

        Returns:
            Подтверждение для TTS
        """
        reminder = {
            'text': text,
            'time': time.time() + seconds,
            'created': time.time()
        }

        # Сохраняем
        reminders = _load_reminders()
        reminders.append(reminder)
        _save_reminders(reminders)

        # Запускаем таймер
        t = threading.Timer(seconds, self._fire, args=[reminder])
        t.daemon = True
        t.start()
        self.timers.append(t)

        time_str = self._format_time(seconds)
        logger.info(f"⏰ Напоминание установлено: «{text}» через {time_str}")
        return f"Хорошо, сэр. Я напомню {time_str}."

    def _format_time(self, seconds: int) -> str:
        """Форматирует секунды в читаемый вид"""
        if seconds < 60:
            return f"через {seconds} секунд"
        elif seconds < 3600:
            return f"через {seconds // 60} минут"
        else:
            return f"через {seconds // 3600} час {seconds % 3600 // 60} минут"

    @staticmethod
    def list_active() -> list:
        """Возвращает список активных напоминаний"""
        reminders = _load_reminders()
        now = time.time()
        return [(r['text'], int(r['time'] - now)) for r in reminders if r['time'] > now]
