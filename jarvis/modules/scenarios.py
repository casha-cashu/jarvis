"""Scenario and automation macro manager for JARVIS.

Allows defining multi-step automation macros triggered by voice, UI, or LLM agent:
- Workspace switching
- App launching
- Shell commands
- Volume adjustments
- TTS voice responses
- Delays
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

from filelock import FileLock

logger = logging.getLogger(__name__)

DEFAULT_SCENARIOS_PATH = Path("data/scenarios.json")


def get_user_scenarios_path() -> Path:
    return (
        Path(os.environ.get("JARVIS_DATA_DIR", "~/.local/share/jarvis")).expanduser()
        / "scenarios.json"
    )


class _UserScenariosPath:
    """Dynamic path resolving against JARVIS_DATA_DIR at runtime."""

    @staticmethod
    def _path() -> Path:
        return get_user_scenarios_path()

    def resolve(self) -> Path:
        return self._path().resolve()

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return repr(self._path())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._path(), name)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _UserScenariosPath):
            return self._path() == other._path()
        return self._path() == other

    def __hash__(self) -> int:
        return hash(self._path())


USER_SCENARIOS_PATH: Any = _UserScenariosPath()


class ScenarioManager:
    """Thread- and process-safe manager for user scenarios/macros."""

    def __init__(self, scenarios_path: Optional[str] = None):
        if scenarios_path:
            self.path = Path(scenarios_path).expanduser().resolve()
        else:
            self.path = USER_SCENARIOS_PATH.resolve()

        self.lock_path = self.path.with_suffix(".lock")
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Ensures scenarios file exists, initializing from data/scenarios.json if available."""
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if DEFAULT_SCENARIOS_PATH.exists():
            try:
                shutil.copyfile(DEFAULT_SCENARIOS_PATH, self.path)
                self.path.chmod(0o600)
                return
            except Exception as e:
                logger.warning(f"Could not copy default scenarios: {e}")

        # Fallback empty dict
        try:
            self.path.write_text("{}", encoding="utf-8")
            self.path.chmod(0o600)
        except Exception as e:
            logger.error(f"Failed to create scenarios file {self.path}: {e}")

    def list_scenarios(self) -> dict[str, Any]:
        """Returns all scenarios as a dictionary."""
        self._ensure_file()
        with FileLock(str(self.lock_path), timeout=5):
            try:
                content = self.path.read_text(encoding="utf-8").strip()
                if not content:
                    return {}
                return json.loads(content)
            except Exception as e:
                logger.error(f"Error reading scenarios from {self.path}: {e}")
                return {}

    def get_scenario(self, scenario_id: str) -> Optional[dict[str, Any]]:
        """Gets a single scenario by its ID."""
        scenarios = self.list_scenarios()
        return scenarios.get(scenario_id)

    def save_scenario(self, scenario_id: str, data: dict[str, Any]) -> bool:
        """Creates or updates a scenario atomically."""
        self._ensure_file()
        with FileLock(str(self.lock_path), timeout=5):
            try:
                scenarios = {}
                if self.path.exists():
                    try:
                        scenarios = json.loads(
                            self.path.read_text(encoding="utf-8") or "{}"
                        )
                    except Exception:
                        scenarios = {}
                scenarios[scenario_id] = data
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(scenarios, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.chmod(0o600)
                tmp.replace(self.path)
                return True
            except Exception as e:
                logger.error(f"Error saving scenario {scenario_id}: {e}")
                return False

    def delete_scenario(self, scenario_id: str) -> bool:
        """Deletes a scenario by ID."""
        self._ensure_file()
        with FileLock(str(self.lock_path), timeout=5):
            try:
                if not self.path.exists():
                    return False
                scenarios = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                if scenario_id in scenarios:
                    del scenarios[scenario_id]
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text(
                        json.dumps(scenarios, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    tmp.chmod(0o600)
                    tmp.replace(self.path)
                    return True
                return False
            except Exception as e:
                logger.error(f"Error deleting scenario {scenario_id}: {e}")
                return False

    def find_matching_scenario(
        self, query: str
    ) -> Optional[tuple[str, dict[str, Any]]]:
        """Finds a scenario matching the given voice or text query."""
        q = query.lower().strip()
        scenarios = self.list_scenarios()

        # 1. Exact match on scenario key
        if q in scenarios:
            return q, scenarios[q]

        # 2. Match on phrases array
        for sc_id, sc in scenarios.items():
            phrases = [p.lower().strip() for p in sc.get("phrases", [])]
            if q in phrases:
                return sc_id, sc

        # 3. Match on key or phrases using word boundaries if query is long enough
        if len(q) >= 4:
            for sc_id, sc in scenarios.items():
                if re.search(rf"\b{re.escape(sc_id.lower())}\b", q):
                    return sc_id, sc
                for phrase in sc.get("phrases", []):
                    if phrase and re.search(rf"\b{re.escape(phrase.lower())}\b", q):
                        return sc_id, sc

        return None

    def execute_scenario(
        self,
        scenario: dict[str, Any],
        executor: Any,
        speak_fn: Optional[Callable[[str], None]] = None,
    ) -> list[str]:
        """Executes the sequence of actions in a scenario.

        Returns a list of log messages for each executed action.
        """
        logs = []
        actions = scenario.get("actions", [])
        platform = getattr(executor, "platform", None)
        run_fn = getattr(executor, "_run", None)

        for action in actions:
            act_type = action.get("type", "").lower()
            try:
                if act_type == "workspace":
                    target = action.get("target")
                    if (
                        target is not None
                        and platform
                        and hasattr(platform, "workspace_switch")
                    ):
                        cmd = platform.workspace_switch(int(target))
                        if cmd and run_fn:
                            run_fn(cmd)
                        logs.append(f"Переключен воркспейс на {target}")
                elif act_type == "launch":
                    target = action.get("target")
                    if target:
                        find_app = getattr(executor, "_find_app_cmd", None)
                        cmd = find_app(str(target)) if find_app else None
                        if not cmd:
                            cmd = str(target)
                        if run_fn:
                            run_fn(cmd)
                        logs.append(f"Запущено приложение: {target}")
                elif act_type == "command":
                    target = action.get("target")
                    if target and run_fn:
                        run_fn(str(target))
                        logs.append(f"Выполнена команда: {target}")
                elif act_type == "volume":
                    amount = action.get("amount")
                    if amount is not None and platform:
                        val = int(amount)
                        direction = str(action.get("direction", "")).lower()
                        abs_val = abs(val)
                        if direction == "down" or val < 0:
                            if hasattr(platform, "volume_down"):
                                cmd = platform.volume_down(abs_val)
                                if cmd and run_fn:
                                    run_fn(cmd)
                        else:
                            if hasattr(platform, "volume_up"):
                                cmd = platform.volume_up(abs_val)
                                if cmd and run_fn:
                                    run_fn(cmd)
                        logs.append(f"Громкость изменена: {amount}")
                elif act_type == "speak":
                    text = action.get("text", "")
                    if text and speak_fn:
                        speak_fn(text)
                        logs.append(f"Озвучено: {text}")
                elif act_type == "delay":
                    seconds = min(float(action.get("seconds", 1.0)), 10.0)
                    time.sleep(seconds)
                    logs.append(f"Пауза {seconds} сек")
            except Exception as e:
                err = f"Ошибка в действии {act_type}: {e}"
                logger.warning(err)
                logs.append(err)

        return logs
