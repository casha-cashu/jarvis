import pytest

from .conftest import skip_if_not_de


pytestmark = [
    pytest.mark.integration,
]


@skip_if_not_de("i3")
class TestI3Window:
    def test_window_close(self, run_cmd):
        result = run_cmd("i3-msg kill")
        assert result.returncode == 0

    def test_window_fullscreen(self, run_cmd):
        result = run_cmd("i3-msg fullscreen toggle")
        assert result.returncode == 0

    def test_window_minimize(self, run_cmd):
        result = run_cmd("i3-msg move scratchpad")
        assert result.returncode == 0


@skip_if_not_de("sway")
class TestSwayWindow:
    def test_window_close(self, run_cmd):
        result = run_cmd("swaymsg kill")
        assert result.returncode == 0

    def test_window_fullscreen(self, run_cmd):
        result = run_cmd("swaymsg fullscreen toggle")
        assert result.returncode == 0

    def test_window_minimize(self, run_cmd):
        # На пустом воркспейсе sway отвечает rc=2
        # ("Can't move an empty workspace to the scratchpad") —
        # сначала создаём окно, потом минимизируем.
        run_cmd("swaymsg exec foot")
        import time

        time.sleep(1.5)
        result = run_cmd("swaymsg move scratchpad")
        assert result.returncode == 0
