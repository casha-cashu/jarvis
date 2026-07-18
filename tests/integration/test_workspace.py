import pytest

from .conftest import skip_if_not_de


pytestmark = [
    pytest.mark.integration,
]


@skip_if_not_de("i3")
class TestI3Workspace:
    def test_switch_to_1_then_2(self, run_cmd):
        assert run_cmd("i3-msg workspace 1").returncode == 0
        assert run_cmd("i3-msg workspace 2").returncode == 0

    def test_next_and_prev(self, run_cmd):
        assert run_cmd("i3-msg workspace next").returncode == 0
        assert run_cmd("i3-msg workspace prev").returncode == 0

    def test_cycle_through_workspaces(self, run_cmd):
        for w in range(1, 6):
            result = run_cmd(f"i3-msg workspace {w}")
            assert result.returncode == 0, f"failed to switch to workspace {w}"


@skip_if_not_de("sway")
class TestSwayWorkspace:
    def test_switch_to_1_then_2(self, run_cmd):
        assert run_cmd("swaymsg workspace 1").returncode == 0
        assert run_cmd("swaymsg workspace 2").returncode == 0

    def test_next_and_prev(self, run_cmd):
        assert run_cmd("swaymsg workspace next").returncode == 0
        assert run_cmd("swaymsg workspace prev").returncode == 0

    def test_cycle_through_workspaces(self, run_cmd):
        for w in range(1, 6):
            result = run_cmd(f"swaymsg workspace {w}")
            assert result.returncode == 0, f"failed to switch to workspace {w}"
