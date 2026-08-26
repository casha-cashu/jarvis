import pytest

from .conftest import skip_if_not_de


pytestmark = [
    pytest.mark.integration,
    pytest.mark.x11,
]


def _i3_vol(run_cmd, cmd):
    return run_cmd(f"pactl {cmd}")


def _sway_vol(run_cmd, cmd):
    return run_cmd(f"pactl {cmd}")


@skip_if_not_de("i3")
class TestI3Volume:
    def test_volume_up(self, run_cmd):
        result = _i3_vol(run_cmd, "set-sink-volume @DEFAULT_SINK@ +5%")
        assert result.returncode == 0

    def test_volume_down(self, run_cmd):
        result = _i3_vol(run_cmd, "set-sink-volume @DEFAULT_SINK@ -5%")
        assert result.returncode == 0

    def test_volume_mute(self, run_cmd):
        result = _i3_vol(run_cmd, "set-sink-mute @DEFAULT_SINK@ toggle")
        assert result.returncode == 0


@skip_if_not_de("sway")
class TestSwayVolume:
    def test_volume_up(self, run_cmd):
        result = _sway_vol(run_cmd, "set-sink-volume @DEFAULT_SINK@ +5%")
        assert result.returncode == 0

    def test_volume_down(self, run_cmd):
        result = _sway_vol(run_cmd, "set-sink-volume @DEFAULT_SINK@ -5%")
        assert result.returncode == 0

    def test_volume_mute(self, run_cmd):
        result = _sway_vol(run_cmd, "set-sink-mute @DEFAULT_SINK@ toggle")
        assert result.returncode == 0
