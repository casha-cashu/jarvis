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

from jarvis._env import sanitized_env

logger = logging.getLogger(__name__)

REMINDERS_FILE = Path.home() / ".local" / "share" / "jarvis" / "reminders.json"

# Serialises every read-modify-write cycle on REMINDERS_FILE. The instance
# _lock only guards the in-memory timer list — without this module lock,
# add() racing a timer-thread prune() could drop a reminder.
_file_lock = threading.Lock()


def _load_reminders() -> list:
    with _file_lock:
        return _load_reminders_locked()


def _save_reminders_locked(reminders: list):
    with _file_lock:
        _save_reminders_locked(reminders)


def _load_reminders_locked() -> list:
    """Загружает активные напоминания"""
    if REMINDERS_FILE.exists():
        try:
            return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_reminders(reminders: list):
    """Сохраняет напоминания"""
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REMINDERS_FILE.write_text(
        json.dumps(reminders, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def parse_time(text: str) -> Optional[tuple]:
    """
    Парсит время из текста.
    Возвращает (секунд, текст_напоминания) или None.
    """

    NUM_WORDS = {
        "ноль": 0,
        "один": 1,
        "одну": 1,
        "одна": 1,
        "два": 2,
        "две": 2,
        "три": 3,
        "четыре": 4,
        "пять": 5,
        "шесть": 6,
        "семь": 7,
        "восемь": 8,
        "девять": 9,
        "десять": 10,
        "одиннадцать": 11,
        "двенадцать": 12,
        "тринадцать": 13,
        "четырнадцать": 14,
        "пятнадцать": 15,
        "шестнадцать": 16,
        "семнадцать": 17,
        "восемнадцать": 18,
        "девятнадцать": 19,
        "двадцать": 20,
        "тридцать": 30,
        "сорок": 40,
        "пятьдесят": 50,
        "шестьдесят": 60,
    }

    UNIT_WORDS = r"(?:секунд[а-я]*|минут[а-я]*|час[а-я]*)"
    NUMBER = r"(?:\d+|" + "|".join(NUM_WORDS.keys()) + r")"

    def _amount(s: str) -> int:
        s = s.strip().lower()
        if s.isdigit():
            return int(s)
        return NUM_WORDS.get(s, 0)

    def _unit_multiplier(u: str) -> int:
        u = u.lower()
        if u.startswith("секунд"):
            return 1
        if u.startswith("минут"):
            return 60
        if u.startswith("час"):
            return 3600
        return 60

    text_lower = text.lower().strip()

    patterns = [
        rf"(?:через|подожди)\s+({NUMBER})\s+({UNIT_WORDS})\s+(.+)$",
        rf"напомни\s+через\s+({NUMBER})\s+({UNIT_WORDS})\s+(.+)$",
        rf"напомни\s+(.+?)\s+через\s+({NUMBER})\s+({UNIT_WORDS})$",
        rf"(?:поставь\s+)?таймер(?:а)?\s+на\s+({NUMBER})\s+({UNIT_WORDS})(?:\s*(.+))?$",
        rf"(?:через|подожди)\s+({NUMBER})\s+({UNIT_WORDS})$",
    ]

    for pat in patterns:
        m = re.search(pat, text_lower)
        if m:
            groups = m.groups()
            groups = tuple("" if g is None else g for g in groups)

            if len(groups) >= 2:
                amount_str = groups[0]
                unit_str = groups[1]
                reminder_text = (
                    groups[2].strip() if len(groups) > 2 and groups[2] else ""
                )

                amount = _amount(amount_str)
                seconds = amount * _unit_multiplier(unit_str)

                if reminder_text:
                    text_clean = reminder_text.rstrip(".")
                    return (seconds, text_clean)
                return (seconds, f"прошло {amount} {unit_str}")

    return None


class ReminderManager:
    """Управление напоминаниями"""

    def __init__(self, on_trigger: Optional[Callable] = None):
        self.on_trigger = on_trigger or self._default_trigger
        self.timers: list = []
        # P3: timers мутируется из main thread (add) и timer threads
        # (_fire -> _cleanup_fired_timers). Без lock'а получаем гонку:
        # list изменяется во время iteration -> RuntimeError.
        self._lock = threading.Lock()
        self._load_active()

    def _default_trigger(self, text: str):
        try:
            subprocess.run(
                ["notify-send", "-u", "critical", "🔔 Напоминание", text],
                timeout=3,
                env=sanitized_env(),
            )
        except Exception:
            pass
        print(f"\n⏰ Напоминание: {text}")

    def _load_active(self):
        reminders = _load_reminders()
        now = time.time()
        for r in reminders:
            remaining = r["time"] - now
            if remaining > 0:
                t = threading.Timer(remaining, self._fire, args=[r])
                t.daemon = True
                t.start()
                with self._lock:
                    self.timers.append(t)
                logger.info(
                    f"⏰ Напоминание загружено: «{r['text']}» через {int(remaining)}с"
                )
            else:
                logger.debug(f"⏰ Просроченное напоминание удалено: {r['text']}")
        self._prune()

    def _prune(self):
        now = time.time()
        reminders = [r for r in _load_reminders() if r["time"] > now]
        _save_reminders(reminders)

    def _cleanup_fired_timers(self):
        """Удаляет сработавшие и отменённые таймеры из списка"""
        with self._lock:
            active = [t for t in self.timers if t.is_alive()]
            removed = len(self.timers) - len(active)
            self.timers = active
        if removed:
            logger.debug(f"⏰ Удалено {removed} неактивных таймеров")

    def _fire(self, reminder: dict):
        text = reminder["text"]
        logger.info(f"⏰ Напоминание сработало: {text}")
        self.on_trigger(text)
        self._prune()
        self._cleanup_fired_timers()

    def add(self, text: str, seconds: int) -> str:
        if seconds <= 0:
            self.on_trigger(text)
            return "Напоминание сработало."

        reminder = {"text": text, "time": time.time() + seconds, "created": time.time()}

        reminders = _load_reminders()
        reminders.append(reminder)
        _save_reminders(reminders)

        t = threading.Timer(seconds, self._fire, args=[reminder])
        t.daemon = True
        t.start()
        with self._lock:
            self.timers.append(t)

        time_str = self._format_time(seconds)
        logger.info(f"⏰ Напоминание установлено: «{text}» через {time_str}")
        return f"Хорошо, сэр. Я напомню {time_str}."

    @staticmethod
    def _plural(n: int, one: str, few: str, many: str) -> str:
        n = abs(n) % 100
        if 11 <= n <= 19:
            return many
        d = n % 10
        if d == 1:
            return one
        if 2 <= d <= 4:
            return few
        return many

    def _format_time(self, seconds: int) -> str:
        if seconds < 60:
            w = self._plural(seconds, "секунду", "секунды", "секунд")
            return f"через {seconds} {w}"
        elif seconds < 3600:
            m = seconds // 60
            w = self._plural(m, "минуту", "минуты", "минут")
            return f"через {m} {w}"
        h, m = seconds // 3600, seconds % 3600 // 60
        hw = self._plural(h, "час", "часа", "часов")
        part = f" {m} {self._plural(m, 'минуту', 'минуты', 'минут')}" if m else ""
        return f"через {h} {hw}{part}"

    @staticmethod
    def list_active() -> list:
        reminders = _load_reminders()
        now = time.time()
        return [(r["text"], int(r["time"] - now)) for r in reminders if r["time"] > now]

    def shutdown(self):
        """Graceful shutdown: сохраняет невыполненные напоминания, отменяет таймеры"""
        logger.info("⏰ Shutdown ReminderManager...")

        cancelled = 0
        with self._lock:
            for t in self.timers:
                if t.is_alive():
                    t.cancel()
                    cancelled += 1
            self.timers.clear()

        now = time.time()
        reminders = [r for r in _load_reminders() if r["time"] > now]
        _save_reminders(reminders)

        logger.info(
            f"⏰ ReminderManager shutdown: отменено {cancelled} таймеров, сохранено {len(reminders)} напоминаний"
        )
