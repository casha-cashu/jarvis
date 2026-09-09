"""Tests for jarvis.lifecycle (LifecycleManager signal handlers)."""

from unittest.mock import MagicMock, patch

from jarvis.lifecycle import LifecycleManager


def test_install_signal_handlers_ignores_value_error_in_thread():
    """install_signal_handlers shouldn't raise ValueError when called outside main thread."""
    mgr = LifecycleManager()
    callback = MagicMock()

    with patch(
        "signal.signal", side_effect=ValueError("signal only works in main thread")
    ):
        # Should not raise ValueError or OSError
        mgr.install_signal_handlers(callback)
