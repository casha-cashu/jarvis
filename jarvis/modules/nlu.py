#!/usr/bin/env python3
"""
NLU module: intent classification + slot extraction.

Replaces steps 2 (fuzzy) and 3 (pattern) of the old CommandExecutor pipeline
with a trained intent classifier and regex-based slot extraction. The old
pipeline is preserved as fallback.

Architecture:
  1. IntentClassifier — TF-IDF + LogisticRegression, trained on command phrases
     at startup (or loaded from cache). Maps speech → command_id.
  2. SlotExtractor — regex patterns + context-word clues extract entities
     (app name, search query, city, time duration, workspace number).
  3. IntentRouter — integrates both, returns (command_id, slots_dict) or None.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

CACHE_DIR = Path(
    os.environ.get(
        "JARVIS_NLU_CACHE",
        os.path.expanduser("~/.local/share/jarvis/nlu"),
    )
)

logger = logging.getLogger(__name__)


# ── Slot patterns ───────────────────────────────────────────────────────────
# Each pattern is (regex, slot_name, priority). Higher priority wins on overlaps.

NUM_WORDS_MAP = {
    "один": "1",
    "одна": "1",
    "одну": "1",
    "первый": "1",
    "первая": "1",
    "два": "2",
    "две": "2",
    "второй": "2",
    "вторая": "2",
    "три": "3",
    "третий": "3",
    "третья": "3",
    "четыре": "4",
    "четвёртый": "4",
    "четвёртая": "4",
    "пять": "5",
    "пятый": "5",
    "пятая": "5",
    "шесть": "6",
    "шестой": "6",
    "семь": "7",
    "седьмой": "7",
    "восемь": "8",
    "восьмой": "8",
    "девять": "9",
    "девятый": "9",
    "десять": "10",
    "десятый": "10",
}

_SLOT_PATTERNS: List[Tuple[re.Pattern, str, int]] = []


def _norm_ws(raw: str) -> str:
    return NUM_WORDS_MAP.get(raw.lower(), raw)


def _build_slot_patterns() -> None:
    global _SLOT_PATTERNS
    if _SLOT_PATTERNS:
        return

    num_words = "|".join(NUM_WORDS_MAP.keys())
    prefix = r"(?:открой|запусти|открыть|запустить|включи)"
    ws = r"(?:воркспейс|рабочий стол)"

    _SLOT_PATTERNS = [
        (re.compile(rf"{prefix}\s+(.+)", re.IGNORECASE), "app", 10),
        (re.compile(r"найди\s+(.+)", re.IGNORECASE), "search", 10),
        (re.compile(rf"{ws}\s+(\d+|{num_words})", re.IGNORECASE), "workspace", 9),
        (re.compile(rf"({num_words})\s+{ws}", re.IGNORECASE), "workspace", 9),
        (
            re.compile(r"(?:громче|тише)\s+(?:на\s+)?(\d+)", re.IGNORECASE),
            "volume_amount",
            5,
        ),
    ]


def extract_slots(text: str) -> Dict[str, str]:
    _build_slot_patterns()
    slots: Dict[str, str] = {}
    for pattern, name, priority in sorted(_SLOT_PATTERNS, key=lambda x: -x[2]):
        m = pattern.search(text)
        if m and name not in slots:
            groups = m.groups()
            if name == "app":
                slots[name] = groups[0].strip()
            elif name == "workspace":
                slots[name] = _norm_ws(groups[0].strip())
            elif name == "reminder":
                slots["reminder_seconds"] = groups[0]
                slots["reminder_text"] = groups[2] if len(groups) > 2 else ""
            elif name == "volume_amount":
                slots[name] = groups[0]
            else:
                slots[name] = groups[0].strip() if groups[0] else ""
    return slots


# ── Intent classifier ───────────────────────────────────────────────────────


@dataclass
class IntentExample:
    phrase: str
    intent: str


class IntentClassifier:
    def __init__(self, phrases: List[IntentExample]):
        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            lowercase=True,
            token_pattern=r"(?u)\b\w+\b",
        )
        self.clf = LogisticRegression(
            C=5.0,
            max_iter=500,
            random_state=42,
        )
        self._fitted = False
        self._intent_labels: List[str] = []
        if phrases:
            self.train(phrases)

    @property
    def fitted(self) -> bool:
        return self._fitted

    def train(self, examples: List[IntentExample]) -> None:
        if not examples or len(set(e.intent for e in examples)) < 2:
            # Need at least 2 classes for LogisticRegression. With a single
            # intent, every phrase maps to it — classifier is degenerate
            # and we'd just hardcode that label. Skip training.
            self._fitted = False
            return
        texts = [e.phrase.lower() for e in examples]
        labels = [e.intent for e in examples]
        idx_to_label = sorted(set(labels))
        label_ids = [idx_to_label.index(lbl) for lbl in labels]

        X = self.vectorizer.fit_transform(texts)
        self.clf.fit(X, label_ids)
        self._intent_labels = idx_to_label
        self._fitted = True
        logger.info(
            "Intent classifier trained on %d phrases, %d intents",
            len(texts),
            len(idx_to_label),
        )

    def predict(self, text: str) -> Optional[Tuple[str, float]]:
        """Returns (intent_label, confidence) or None."""
        if not self._fitted:
            return None
        X = self.vectorizer.transform([text.lower()])
        proba = self.clf.predict_proba(X)[0]
        best_idx = int(np.argmax(proba))
        confidence = float(proba[best_idx])
        if confidence < 0.65:
            return None
        return self._intent_labels[best_idx], confidence


# ── Training data builder ────────────────────────────────────────────────────


def build_training_data(
    commands_json: dict,
    apps_json: dict,
    platform_commands: Dict[str, str] | None = None,
) -> List[IntentExample]:
    training: List[IntentExample] = []
    has_cmds = bool(commands_json.get("commands"))
    has_apps = bool(apps_json.get("apps"))

    # From commands.json — each phrase maps to a command_id
    cmds = commands_json.get("commands", {})
    for phrase, data in cmds.items():
        cat = data.get("category", "general")
        training.append(IntentExample(phrase=phrase, intent=cat))

    # From apps.json — app names + aliases
    apps = apps_json.get("apps", {})
    for app_id, data in apps.items():
        for alias in data.get("names", []):
            training.append(IntentExample(phrase=f"открой {alias}", intent="open_app"))
            training.append(IntentExample(phrase=f"запусти {alias}", intent="open_app"))
            training.append(
                IntentExample(phrase=f"запустить {alias}", intent="open_app")
            )
            training.append(IntentExample(phrase=alias, intent="open_app"))

    # Platform commands — workspace, window, screenshot, volume, etc.
    if platform_commands:
        for phrase in platform_commands:
            training.append(IntentExample(phrase=phrase, intent="system"))

    # Synthetic patterns — only if there are real commands/apps to contextualise
    if has_cmds or has_apps:
        for prefix in ["найди ", "поиск ", "ищи "]:
            for noun in [
                "рецепт",
                "новости",
                "python",
                "погоду",
                "курс доллара",
                "кота",
                "картинку",
                "файл",
                "видео",
            ]:
                training.append(
                    IntentExample(phrase=f"{prefix}{noun}", intent="search")
                )

        for phrase in [
            "сколько будет дважды два",
            "расскажи анекдот",
            "как дела",
            "что нового",
            "привет",
            "спасибо",
            "как тебя зовут",
            "что ты умеешь",
        ]:
            training.append(IntentExample(phrase=phrase, intent="unknown"))

    return training


# ── IntentRouter (public API) ────────────────────────────────────────────────


class IntentRouter:
    """NLU front-end: intent classification + slot extraction → dispatch."""

    def __init__(
        self,
        commands_file: str = "data/commands.json",
        apps_file: str = "data/apps.json",
    ):
        self._commands = self._load_json(commands_file)
        self._apps = self._load_json(apps_file)
        self._classifier: Optional[IntentClassifier] = None
        self._train()

    def _load_json(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _train(self) -> None:
        examples = build_training_data(self._commands, self._apps)
        if examples:
            self._classifier = IntentClassifier(examples)
        else:
            logger.warning("No training data — IntentRouter will always fallback")

    def classify(self, text: str) -> Optional[Tuple[str, float]]:
        if self._classifier is None:
            return None
        return self._classifier.predict(text)

    def parse(self, text: str) -> Dict[str, object]:
        """Full NLU parse: intent + slots."""
        result: Dict[str, object] = {"raw": text}
        intent = self.classify(text)
        if intent:
            result["intent"] = intent[0]
            result["intent_confidence"] = intent[1]
        slots = extract_slots(text)
        if slots:
            result["slots"] = slots
        return result
