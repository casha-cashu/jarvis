"""Tests for PR-BRIDGE-1: Guard _setup_runtime_paths() behind sys.frozen or env override."""

from __future__ import annotations

import sys


from jarvis.ui_bridge import _setup_runtime_paths, should_setup_runtime_paths


class TestRuntimePathsGuards:
    def test_should_setup_runtime_paths_normal_mode(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delenv("JARVIS_ENABLE_RUNTIME_PATHS", raising=False)
        assert should_setup_runtime_paths() is False

    def test_should_setup_runtime_paths_frozen_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delenv("JARVIS_ENABLE_RUNTIME_PATHS", raising=False)
        assert should_setup_runtime_paths() is True

    def test_should_setup_runtime_paths_env_override(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setenv("JARVIS_ENABLE_RUNTIME_PATHS", "1")
        assert should_setup_runtime_paths() is True

    def test_setup_runtime_paths_does_not_mutate_sys_path_in_normal_mode(
        self, monkeypatch
    ):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delenv("JARVIS_ENABLE_RUNTIME_PATHS", raising=False)

        original_sys_path = list(sys.path)
        _setup_runtime_paths()
        assert sys.path == original_sys_path

    def test_setup_runtime_paths_mutates_when_forced_or_frozen(
        self, monkeypatch, tmp_path
    ):
        fake_sp = tmp_path / "lib" / "python3.14" / "site-packages"
        fake_sp.mkdir(parents=True)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        original_sys_path = list(sys.path)

        # Candidate path injection
        with monkeypatch.context() as m:
            m.setattr(
                "jarvis.ui_bridge._CANDIDATE_PATHS",
                [str(fake_sp)],
                raising=False,
            )
            _setup_runtime_paths(force=True)
            assert str(fake_sp) in sys.path

        # Cleanup sys.path after test
        sys.path[:] = original_sys_path
