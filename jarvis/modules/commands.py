#!/usr/bin/env python3
"""
Commands module — локальная обработка команд БЕЗ LLM.

Pipeline (строгий порядок):
  1. Exact match   — точное совпадение с commands.json
  2. Fuzzy match   — нечёткое совпадение (>= fuzzy_threshold)
  3. Pattern match — «открой {app}», «запусти {app}», «найди {query}»
  4. App by name   — отдельное название приложения («браузер» → Firefox)
  5. Voice cmd     — mute/unmute/диктовка/напоминание/выход (возврат маркеров)
  6. → LLM (возврат None)
"""

import json
import re
import shlex
import subprocess
import logging
import urllib.parse
from typing import Optional, Protocol, Tuple

# P12: rapidfuzz — C-extension, ~10-100x быстрее SequenceMatcher
# на типичных размерах словарей команд. Используем fuzz.ratio (0-100)
# и нормализуем в [0, 1] для обратной совместимости с порогами в конфиге.
try:
    from rapidfuzz import fuzz as _rf_fuzz

    _HAVE_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher  # graceful fallback

    _HAVE_RAPIDFUZZ = False

from jarvis._env import sanitized_env

from .platform_adapter import PlatformAdapter

logger = logging.getLogger(__name__)

# Сентинел провала исполнения: None — «команда ничего не вывела» (легально),
# _RUN_FAILED — «запуск не удался» (бинаря нет, таймаут, ошибка). Нужен,
# чтобы TTS не объявлял успех упавшей команды.
_RUN_FAILED = object()


class _NluRouter(Protocol):
    """Структурный тип IntentRouter (избегает циклического импорта)."""

    def parse(self, query: str) -> dict: ...


class CommandExecutor:
    """Выполняет системные команды (без LLM)"""

    def __init__(
        self,
        commands_file: str,
        apps_file: str,
        fuzzy_threshold: float = 0.8,
        platform_adapter: Optional[PlatformAdapter] = None,
        execution_timeout: int = 30,
        nlu_router: "Optional[_NluRouter]" = None,
        nlu_confidence_threshold: float = 0.65,
    ):
        self.fuzzy_threshold = fuzzy_threshold
        self.platform = platform_adapter or PlatformAdapter()
        # Timeout для блокирующих команд. _run ждёт завершения процесса
        # до execution_timeout секунд, после чего шлёт SIGTERM (и SIGKILL
        # через grace-период). Это гарантирует что зависшая команда
        # (ждущая password, interactive prompt, deadlock IPC) не оставит
        # зомби-процесс и не зависит в main loop.
        self.execution_timeout = max(1, int(execution_timeout))
        # NLU front-end — optional. When provided, executes before fuzzy
        # matching. If NLU returns confident intent + slots, dispatches
        # directly; otherwise falls through to existing pipeline.
        self.nlu: "Optional[_NluRouter]" = nlu_router
        self.nlu_confidence_threshold = nlu_confidence_threshold

        # Загружаем словари
        json_data = self._load_json(commands_file)
        self.commands = json_data if "commands" in json_data else {}
        self.apps = self._load_json(apps_file)

        if "commands" not in self.commands:
            self.commands["commands"] = {}

        # Платформенные команды — поверх JSON (приоритет у платформы)
        self._add_platform_commands()

        cmds_count = len(self.commands.get("commands", {}))
        apps_count = len(self.apps.get("apps", {}))
        logger.info(f"✅ Загружено команд: {cmds_count}, приложений: {apps_count}")

    # ── Загрузка ──────────────────────────────────────────────

    def _load_json(self, file_path: str) -> dict:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {file_path}: {e}")
            return {}

    def _add_platform_commands(self):
        """Добавляет платформозависимые команды (Hyprland/KDE/…)."""
        pc = {}
        if "commands" not in self.commands:
            self.commands["commands"] = {}

        # Воркспейсы 1–10 (число + прописью)
        nums = {
            1: "первый",
            2: "второй",
            3: "третий",
            4: "четвёртый",
            5: "пятый",
            6: "шестой",
            7: "седьмой",
            8: "восьмой",
            9: "девятый",
            10: "десятый",
        }
        for i in range(1, 11):
            cmd = self.platform.workspace_switch(i)
            for variant in [
                f"{i} воркспейс",
                f"воркспейс {i}",
                f"{nums[i]} воркспейс",
                f"{nums[i]} ворог спэйс",
                f"переключи на {nums[i]} воркспейс",
                f"переключи на {i} воркспейс",
            ]:
                pc[variant] = {"cmd": cmd, "say": f"Воркспейс {i}"}

        # Навигация
        pc["следующий воркспейс"] = {
            "cmd": self.platform.workspace_next(),
            "say": "Следующий",
        }
        pc["предыдущий воркспейс"] = {
            "cmd": self.platform.workspace_prev(),
            "say": "Предыдущий",
        }
        pc["воркспейс вправо"] = {"cmd": self.platform.workspace_next(), "say": ""}
        pc["воркспейс влево"] = {"cmd": self.platform.workspace_prev(), "say": ""}

        # Окна
        pc["закрой окно"] = {"cmd": self.platform.window_close(), "say": "Закрываю"}
        pc["закрой это"] = {"cmd": self.platform.window_close(), "say": "Закрываю"}
        pc["закрой это окно"] = {"cmd": self.platform.window_close(), "say": "Закрываю"}
        pc["полный экран"] = {
            "cmd": self.platform.window_fullscreen(),
            "say": "Полный экран",
        }
        pc["сверни окно"] = {
            "cmd": self.platform.window_minimize(),
            "say": "Сворачиваю",
        }
        pc["разверни окно"] = {
            "cmd": self.platform.window_maximize(),
            "say": "Разворачиваю",
        }
        pc["плавающее окно"] = {
            "cmd": self.platform.window_floating(),
            "say": "Переключаю",
        }
        pc["следующее окно"] = {"cmd": self.platform.window_next(), "say": "Следующее"}
        pc["предыдущее окно"] = {
            "cmd": self.platform.window_prev(),
            "say": "Предыдущее",
        }

        # Скриншоты — храним ссылки на методы (callable), а не результаты.
        # Иначе timestamp в имени файла «замораживается» на момент старта
        # и каждый новый скриншот перезаписывает предыдущий.
        pc["скриншот"] = {"cmd": self.platform.screenshot_screen, "say": "Скриншот"}
        pc["скриншот экрана"] = {
            "cmd": self.platform.screenshot_screen,
            "say": "Скриншот экрана",
        }
        pc["скриншот области"] = {
            "cmd": self.platform.screenshot_area,
            "say": "Выберите область",
        }
        pc["скриншот окна"] = {
            "cmd": self.platform.screenshot_window,
            "say": "Скриншот окна",
        }

        # Звук
        pc["громче"] = {"cmd": self.platform.volume_up(5), "say": "Громче"}
        pc["тише"] = {"cmd": self.platform.volume_down(5), "say": "Тише"}
        pc["выключи звук"] = {
            "cmd": self.platform.volume_mute(),
            "say": "Звук выключен",
        }
        pc["включи звук"] = {
            "cmd": self.platform.volume_unmute(),
            "say": "Звук включён",
        }

        # Система
        pc["заблокируй экран"] = {"cmd": self.platform.lock_screen(), "say": "Блокирую"}
        pc["заблокируй"] = {"cmd": self.platform.lock_screen(), "say": "Блокирую"}
        pc["перезагрузка"] = {
            "cmd": self.platform.system_reboot(),
            "say": "Перезагружаюсь",
        }
        pc["выключение"] = {"cmd": self.platform.system_shutdown(), "say": "Выключаюсь"}

        # Приложения (платформенные)
        pc["открой терминал"] = {
            "cmd": self.platform.get_terminal(),
            "say": "Открываю терминал",
        }
        pc["открой файлы"] = {
            "cmd": self.platform.get_file_manager(),
            "say": "Открываю файлы",
        }
        pc["диспетчер задач"] = {
            "cmd": self.platform.get_task_manager(),
            "say": "Диспетчер задач",
        }

        self.commands["commands"].update(pc)

    # ── Matching ──────────────────────────────────────────────

    def _fuzzy_score(self, a: str, b: str) -> float:
        if _HAVE_RAPIDFUZZ:
            return _rf_fuzz.ratio(a.lower(), b.lower()) / 100.0
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    # Пары команд, которые шумный STT путает между собой ("включи" -
    # "выключи"). Для них fuzzy-порог повышен: неоднозначность -> LLM.
    _FUZZY_CONFLICT_PAIRS = [
        frozenset({"включи звук", "выключи звук"}),
        frozenset({"включи микрофон", "выключи микрофон"}),
        frozenset({"громче", "тише"}),
    ]

    def _best_fuzzy(self, query: str, candidates: dict) -> Optional[Tuple[str, dict]]:
        best_key: Optional[str] = None
        best_data: Optional[dict] = None
        best_score = 0.0
        for key, data in candidates.items():
            score = self._fuzzy_score(query, key)
            if score > best_score:
                best_score, best_key, best_data = score, key, data
        if best_score >= self.fuzzy_threshold:
            for pair in self._FUZZY_CONFLICT_PAIRS:
                if best_key in pair and best_score < 0.93:
                    logger.info(
                        "🎚 Ambiguous fuzzy %.2f ('%s') — fallback to LLM",
                        best_score,
                        query,
                    )
                    return None
            if best_key is not None and best_data is not None:
                return best_key, best_data
        return None

    def _find_app_cmd(self, name: str) -> Optional[str]:
        """Ищет команду запуска приложения по любому имени/алиасу."""
        apps = self.apps.get("apps", {})
        name_lower = name.lower()

        # 1. Точное или частичное совпадение
        for app_id, app_data in apps.items():
            for alias in app_data.get("names", []):
                if (
                    name_lower == alias.lower()
                    or name_lower in alias.lower()
                    or alias.lower() in name_lower
                ):
                    return app_data.get("cmd")

        # 2. Fuzzy
        for app_id, app_data in apps.items():
            for alias in app_data.get("names", []):
                if self._fuzzy_score(name_lower, alias) >= self.fuzzy_threshold:
                    return app_data.get("cmd")

        return None

    # ── Основной pipeline ─────────────────────────────────────

    def execute(self, query: str) -> Optional[str]:
        """
        Пытается выполнить команду.
        Возвращает текст для озвучки или None (→ LLM).

        Pipeline order:
          1. Exact match
          1.5. NLU (если подключён) — intent + slots dispatch
          2. Fuzzy match
          3. Pattern match (открой/запусти {app}, найди {query})
          4. Standalone app name
          5. Voice command markers
          6. → LLM
        """
        q = query.strip().lower()
        if not q:
            return None

        commands = self.commands.get("commands", {})

        # ── Шаг 1: Exact match ──
        if q in commands:
            logger.info(f"🎯 Exact match: '{q}'")
            entry = commands[q]
            out = self._run(entry["cmd"], capture=bool(entry.get("capture")))
            if out is _RUN_FAILED:
                return "Не получилось, сэр."
            return self._compose_say(entry, out)

        # ── Шаг 1.2: Громкость с числом («громче на 20») ──
        # Командная таблица замораживает volume_up(5) строкой; здесь
        # количество из фразы доходит до адаптера.
        vol_match = re.fullmatch(r"(громче|тише)\s+на\s+(\d+)\s*(?:%)?", q)
        if vol_match:
            direction, amount = vol_match.group(1), int(vol_match.group(2))
            amount = max(0, min(amount, 100))
            cmd = (
                self.platform.volume_up(amount)
                if direction == "громче"
                else self.platform.volume_down(amount)
            )
            if cmd and self._run(cmd) is _RUN_FAILED:
                return "Не получилось, сэр."
            return f"Меняю громкость на {amount}"

        # ── Шаг 1.5: NLU (если подключён) ──
        if self.nlu is not None:
            nlu_resp = self._nlu_dispatch(q)
            if nlu_resp is not None:
                return nlu_resp

        # ── Шаг 2: Fuzzy match ──
        match = self._best_fuzzy(q, commands)
        if match:
            key, data = match
            logger.info(f"🎯 Fuzzy match: '{q}' → '{key}'")
            out = self._run(data["cmd"], capture=bool(data.get("capture")))
            if out is _RUN_FAILED:
                return "Не получилось, сэр."
            return self._compose_say(data, out)

        # ── Шаг 3: Pattern match (открой/запусти {app}) ──
        app_prefixes = ["открой ", "запусти ", "открыть ", "запустить ", "включи "]
        for prefix in app_prefixes:
            if q.startswith(prefix):
                app_name = q[len(prefix) :].strip()
                if app_name:
                    app_cmd = self._find_app_cmd(app_name)
                    if app_cmd:
                        logger.info(f"🎯 App match: '{prefix}{app_name}' → '{app_cmd}'")
                        if self._run(app_cmd) is _RUN_FAILED:
                            return f"Не удалось запустить {app_name}"
                        return f"Запускаю {app_name}"
                break  # нашли префикс — не ищем другие

        # ── Шаг 3b: «найди {query}» ──
        if q.startswith("найди "):
            search = q[6:].strip()
            if search:
                logger.info(f"🔍 Веб-поиск: '{search}'")
                self._web_search(search)
                return f"Ищу {search}"

        # ── Шаг 4: Standalone app name (без «открой») ──
        # Любой одиночный запрос проверяем как имя приложения
        app_cmd = self._find_app_cmd(q)
        if app_cmd:
            logger.info(f"🎯 App standalone: '{q}' → '{app_cmd}'")
            if self._run(app_cmd) is _RUN_FAILED:
                return f"Не удалось запустить {q}"
            return f"Запускаю {q}"

        # ── Шаг 5: Voice commands (маркеры для main loop) ──
        voice_marker = self.parse_voice_command(q)
        if voice_marker:
            return voice_marker

        # ── Команда не найдена → LLM ──
        return None

    def _nlu_dispatch(self, query: str) -> Optional[str]:
        """NLU-driven dispatch. Returns response str or None to fall through.

        Strategy: invoke ``IntentRouter.parse()``. If intent confidence is
        high enough AND slots contain actionable entities (app/search/
        workspace), dispatch directly — skipping fuzzy/pattern steps.

        Bare intent without slots (e.g. "system") is NOT enough — fuzzy
        matching on the existing command table stays authoritative there,
        since NLU's category is coarse-grained.
        """
        if self.nlu is None:
            return None
        try:
            result = self.nlu.parse(query)
        except Exception as e:
            logger.warning(f"NLU parse failed: {e}")
            return None

        confidence = result.get("intent_confidence", 0.0)
        if confidence < self.nlu_confidence_threshold:
            return None

        slots = result.get("slots") or {}
        intent = result.get("intent")

        # open_app + app slot → launch app
        if intent == "open_app" and "app" in slots:
            app_name = slots["app"]
            app_cmd = self._find_app_cmd(app_name)
            if app_cmd:
                logger.info(
                    f"🎯 NLU open_app: '{app_name}' → '{app_cmd}' (conf={confidence:.2f})"
                )
                if self._run(app_cmd) is _RUN_FAILED:
                    return f"Не удалось запустить {app_name}"
                return f"Запускаю {app_name}"

        # search + query slot → web search
        if intent == "search" and "search" in slots:
            search = slots["search"]
            logger.info(f"🔍 NLU search: '{search}' (conf={confidence:.2f})")
            self._web_search(search)
            return f"Ищу {search}"

        # workspace switch via slot
        if intent == "system" and "workspace" in slots:
            ws = slots["workspace"]
            try:
                ws_num = int(ws)
            except (TypeError, ValueError):
                return None
            if 1 <= ws_num <= 10:
                cmd = self.platform.workspace_switch(ws_num)
                if cmd:
                    logger.info(f"🎯 NLU workspace: {ws_num} (conf={confidence:.2f})")
                    self._run(cmd)
                    return f"Воркспейс {ws_num}"

        return None

    # ── Исполнение ────────────────────────────────────────────

    def _run(self, cmd, capture: bool = False):
        """Запускает команду через subprocess (shell=False).

        ``cmd`` может быть строкой или callable -> str. Callable вычисляется
        в момент исполнения — это нужно для команд, у которых часть аргументов
        зависит от runtime-состояния (timestamp скриншота, geom от slurp).
        Пустая строка после вычисления означает «нечего запускать» (например,
        пользователь отменил выбор области) и тихо пропускается.

        ``capture=True`` собирает stdout и возвращает его (stripped) — для
        информационных команд типа ``date '+%H:%M'``, чей вывод подставляется
        в ответ. Иначе запускается fire-and-forget Popen и возвращается None.

        Блокирует до ``execution_timeout`` секунд, затем шлёт SIGTERM (и
        SIGKILL через 2s grace). Для fire-and-forget launcher'ов (firefox,
        telegram) это безопасно — они форкаются и отсоединяются мгновенно.
        """
        try:
            if callable(cmd):
                cmd = cmd()
            if not cmd:
                return None
            logger.info(f"🔧 Выполняю: {cmd}")
            # shlex.split корректно парсит команды с кавычками
            # (notify-send 'title' 'message', date '+%H:%M', etc.)
            # НЕ поддерживает shell-операторы (||, |, ;, 2>/dev/null)
            # — это сделано намеренно для безопасности.
            if capture:
                proc = subprocess.run(
                    shlex.split(cmd),
                    capture_output=True,
                    text=True,
                    timeout=self.execution_timeout,
                    env=sanitized_env(),
                )
                return (proc.stdout or "").strip()
            launcher = subprocess.Popen(
                shlex.split(cmd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=sanitized_env(),
            )
            # Short-lived commands (notify-send, xdotool) finish quickly and
            # are reaped here. Long-lived launchers (firefox, telegram) are
            # deliberately DETACHED after 2s — waiting the full timeout used
            # to SIGTERM every GUI app 30s after opening it.
            try:
                launcher.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.debug(f"🚀 Detached long-running process: {cmd}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения: {e}")
            return _RUN_FAILED

    @staticmethod
    def _compose_say(entry: dict, output) -> str:
        """Формирует ответ: say-шаблон + захваченный вывод команды."""
        say = entry.get("say", "")
        if output:
            return f"{say} {output}".strip() if say else str(output)
        return say or "Готово, сэр."

    def _web_search(self, query: str):
        encoded = urllib.parse.quote_plus(query)
        self._run(f"xdg-open 'https://www.google.com/search?q={encoded}'")

    # ── Voice command markers ─────────────────────────────────

    def parse_voice_command(self, query: str) -> Optional[str]:
        """
        Публичный метод. Возвращает маркеры для main loop:
          __MUTE__, __UNMUTE__, __DICTATE__,
          __REMINDER__:сек:текст, __REMINDER_LIST__, __EXIT__
        """
        q = query.lower().strip()

        # Mute/unmute
        if q in (
            "заткнись",
            "замолчи",
            "тихо",
            "молчать",
            "хватит",
            "отстань",
            "выключи микрофон",
            "выключись",
            "стоп",
            "умолкни",
        ):
            return "__MUTE__"
        if q in (
            "продолжить",
            "продолжай",
            "говори",
            "включи микрофон",
            "слушай",
            "снова работай",
            "вернись",
            "проснись",
        ):
            return "__UNMUTE__"

        # Диктовка
        if (
            q.startswith("диктовк")
            or q.startswith("печатай")
            or q
            in (
                "режим диктовки",
                "начать диктовку",
                "запустить диктовку",
                "включи диктовку",
                "голосовой ввод",
            )
        ):
            return "__DICTATE__"

        # Напоминания — только явные интенты или голая длительность.
        # Иначе "подожди пять минут и скажи анекдот" перехватится как
        # reminder "...и скажи анекдот" и не дойдёт до LLM.
        from .reminder import parse_time

        explicit_intent = bool(
            re.match(
                r"^(напомни|напоминание|таймер|будильник|поставь таймер|через\s+\d)", q
            )
        )
        bare_duration = re.fullmatch(r"(через\s+)?\d+\s*(секунд\w*|минут\w*|час\S*)", q)
        parsed = parse_time(q) if (explicit_intent or bare_duration) else None
        if parsed:
            seconds, text = parsed
            safe = text.replace(":", " ").replace("|", " ")
            return f"__REMINDER__:{seconds}:{safe}"

        if q in (
            "список напоминаний",
            "какие напоминания",
            "что на сегодня",
            "мои напоминания",
            "покажи напоминания",
        ):
            return "__REMINDER_LIST__"

        # Выход
        if q in (
            "выйти",
            "завершить работу",
            "выключись полностью",
            "останови джарвис",
            "стоп джарвис",
            "пока",
            "до свидания",
            "отключись",
            "на сегодня всё",
        ):
            return "__EXIT__"

        return None


class CommandManager:
    """Главный менеджер команд — владеет CommandExecutor."""

    def __init__(self, config: dict, nlu_router: "Optional[_NluRouter]" = None):
        commands_cfg = config.get("commands", {})
        self.platform = PlatformAdapter()

        # Словари могут быть упакованы в PyInstaller-бинарь (_MEIPASS) —
        # резолвим через resource_path, а не голый относительный путь.
        from jarvis.resources import resource_path

        dictionary_path = resource_path(
            commands_cfg.get("dictionary_path", "data/commands.json")
        )
        apps_path = resource_path(
            commands_cfg.get("apps_dictionary_path", "data/apps.json")
        )

        # NLU: if caller provides a router ( tests, or wiring from outside ),
        # use it. Otherwise, default-enable NLU if not explicitly disabled
        # in config and training data files exist.
        if nlu_router is None:
            nlu_router = self._maybe_init_nlu(
                dictionary_path, apps_path, commands_cfg.get("nlu_enabled", True)
            )

        self.executor = CommandExecutor(
            commands_file=dictionary_path,
            apps_file=apps_path,
            fuzzy_threshold=commands_cfg.get("fuzzy_threshold", 0.8),
            platform_adapter=self.platform,
            execution_timeout=commands_cfg.get("execution_timeout", 30),
            nlu_router=nlu_router,
            nlu_confidence_threshold=commands_cfg.get("nlu_confidence_threshold", 0.65),
        )
        logger.info("✅ CommandManager инициализирован")

    @staticmethod
    def _maybe_init_nlu(
        cmds_path: str, apps_path: str, nlu_enabled: bool = True
    ) -> "Optional[_NluRouter]":
        """Build an IntentRouter from data files unless explicitly disabled."""
        if nlu_enabled is False:
            return None
        try:
            from jarvis.modules.nlu import IntentRouter

            return IntentRouter(
                commands_file=cmds_path,
                apps_file=apps_path,
            )
        except Exception as e:
            logger.warning(f"⚠️ NLU недоступен: {e} — fallback на fuzzy pipeline")
            return None

    def process(self, query: str) -> Optional[str]:
        return self.executor.execute(query)

    @property
    def commands_list(self) -> list:
        """Возвращает список всех известных команд (для справки)."""
        return list(self.executor.commands.get("commands", {}).keys())
