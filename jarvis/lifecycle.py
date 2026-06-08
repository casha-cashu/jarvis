"""Сигнал-хендлеры и координация shutdown'а.

Раньше Jarvis сам регистрировал signal handlers и вызывал shutdown по
очереди. Здесь это собрано в один компонент с регистрацией компонентов
по интерфейсу stop().
"""

from __future__ import annotations

import logging
import signal
from typing import Callable

logger = logging.getLogger(__name__)


class LifecycleManager:
    """Регистрирует SIGINT/SIGTERM и координирует shutdown компонентов."""

    def __init__(self):
        self._components: list[object] = []
        self._on_stop: Callable[[], None] | None = None
        self._installed = False

    def register(self, *components: object) -> None:
        """Добавляет компонент с методом stop() в очередь shutdown'а."""
        for c in components:
            if c is None:
                continue
            self._components.append(c)

    def install_signal_handlers(self, on_stop: Callable[[], None]) -> None:
        """Регистрирует SIGINT/SIGTERM. on_stop вызывается ОДИН раз;
        дальше повторные сигналы игнорируются — это не Ctrl-C-spam-friendly,
        но защищает от частичного shutdown'а на агрессивный сигнал."""
        self._on_stop = on_stop
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)
        self._installed = True

    def _handle(self, signum, _frame) -> None:
        logger.info(f"\n🛑 Получен сигнал {signum}")
        if self._on_stop is not None:
            cb = self._on_stop
            self._on_stop = None  # один раз
            try:
                cb()
            except Exception as e:
                logger.error(f"on_stop callback failed: {e}")

    def shutdown(self) -> None:
        """Корректно завершает зарегистрированные компоненты."""
        for c in reversed(self._components):
            stop = getattr(c, 'stop', None) or getattr(c, 'shutdown', None)
            if not stop:
                continue
            try:
                stop()
            except Exception as e:
                logger.error(f"shutdown error in {type(c).__name__}: {e}")
