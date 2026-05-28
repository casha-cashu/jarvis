import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest


def detect_de() -> str:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session = os.environ.get("DESKTOP_SESSION", "").lower()
    if "i3" in session or os.environ.get("I3SOCK"):
        return "i3"
    if "sway" in session or os.environ.get("SWAYSOCK"):
        return "sway"
    if "hyprland" in desktop or "hyprland" in session:
        return "hyprland"
    if "kde" in desktop or "plasma" in desktop:
        return "kde"
    if "gnome" in desktop:
        return "gnome"
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=2
        )
        procs = result.stdout.lower()
        if "hyprland" in procs:
            return "hyprland"
        if "i3" in procs and "sway" not in procs:
            return "i3"
        if "sway" in procs:
            return "sway"
    except Exception:
        pass
    return "unknown"


@pytest.fixture
def de_name() -> str:
    return os.environ.get("JARVIS_TEST_DE") or detect_de()


def get_adapter(de: str):
    from jarvis.modules.platform_adapter import get_adapter_class

    return get_adapter_class(de)()


@pytest.fixture
def adapter(de_name: str):
    return get_adapter(de_name)


@pytest.fixture
def run_cmd():
    def _run(cmd: str, timeout: int = 15) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )

    return _run


@pytest.fixture
def i3_msg(run_cmd):
    def _i3(msg: str) -> subprocess.CompletedProcess:
        return run_cmd(f"i3-msg {msg}")

    return _i3


@pytest.fixture
def sway_msg(run_cmd):
    def _sway(msg: str) -> subprocess.CompletedProcess:
        return run_cmd(f"swaymsg {msg}")

    return _sway


def pytest_configure(config):
    config.addinivalue_line("markers", "i3: tests specific to i3")
    config.addinivalue_line("markers", "sway: tests specific to Sway")
    config.addinivalue_line("markers", "x11: tests that need X11 display")
    config.addinivalue_line("markers", "wayland: tests that need Wayland display")
    config.addinivalue_line(
        "markers", "integration: integration tests that need a real DE/WM"
    )


def skip_if_not_de(de_names):
    if isinstance(de_names, str):
        de_names = [de_names]
    return pytest.mark.skipif(
        not any(
            os.environ.get("JARVIS_TEST_DE") == de or detect_de() == de
            for de in de_names
        ),
        reason=f"requires one of: {', '.join(de_names)}",
    )
