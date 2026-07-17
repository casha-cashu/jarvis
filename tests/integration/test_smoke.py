import subprocess

import pytest

from .conftest import skip_if_not_de


pytestmark = [
    pytest.mark.integration,
]


@skip_if_not_de("i3")
class TestI3Smoke:
    def test_de_process_running(self):
        result = subprocess.run(["pgrep", "i3"], capture_output=True, text=True)
        assert result.returncode == 0, "i3 process not found"
        assert result.stdout.strip(), "i3 PID is empty"

    def test_ipc_connection(self, run_cmd):
        result = run_cmd("i3-msg -t get_workspaces")
        assert result.returncode == 0
        assert result.stdout.strip(), "empty response from i3-msg"

    def test_workspace_switch(self, run_cmd):
        result = run_cmd("i3-msg workspace 3")
        assert result.returncode == 0

    def test_window_fullscreen(self, run_cmd):
        result = run_cmd("i3-msg fullscreen toggle")
        assert result.returncode == 0

    def test_notify(self, run_cmd):
        result = run_cmd("notify-send 'test' 'message'")
        assert result.returncode == 0

    def test_terminal_launch(self, run_cmd):
        result = run_cmd("xterm -e true", timeout=10)
        assert result.returncode == 0


@skip_if_not_de("sway")
class TestSwaySmoke:
    def test_de_process_running(self):
        result = subprocess.run(["pgrep", "sway"], capture_output=True, text=True)
        assert result.returncode == 0, "sway process not found"
        assert result.stdout.strip(), "sway PID is empty"

    def test_ipc_connection(self, run_cmd):
        result = run_cmd("swaymsg -t get_workspaces")
        assert result.returncode == 0
        assert result.stdout.strip(), "empty response from swaymsg"

    def test_workspace_switch(self, run_cmd):
        result = run_cmd("swaymsg workspace 3")
        assert result.returncode == 0

    def test_window_fullscreen(self, run_cmd):
        result = run_cmd("swaymsg fullscreen toggle")
        assert result.returncode == 0

    def test_notify(self, run_cmd):
        result = run_cmd("notify-send 'test' 'message'")
        assert result.returncode == 0

    def test_terminal_launch(self, run_cmd):
        result = run_cmd("foot true", timeout=10)
        assert result.returncode == 0
