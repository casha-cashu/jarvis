import os
import tempfile

import pytest

from .conftest import skip_if_not_de


pytestmark = [
    pytest.mark.integration,
]


@skip_if_not_de("i3")
class TestI3Screenshot:
    def test_screenshot_creates_file(self, run_cmd):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            result = run_cmd(f"scrot {tmp.name}")
            assert result.returncode == 0
            assert os.path.exists(tmp.name), "screenshot file was not created"

    def test_screenshot_file_not_empty(self, run_cmd):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            run_cmd(f"scrot --overwrite {tmp.name}")
            assert os.path.getsize(tmp.name) > 0, "screenshot file is empty"


@skip_if_not_de("sway")
class TestSwayScreenshot:
    def test_screenshot_creates_file(self, run_cmd):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            result = run_cmd(f"grim {tmp.name}")
            assert result.returncode == 0
            assert os.path.exists(tmp.name), "screenshot file was not created"

    def test_screenshot_file_not_empty(self, run_cmd):
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            run_cmd(f"grim {tmp.name}")
            assert os.path.getsize(tmp.name) > 0, "screenshot file is empty"
