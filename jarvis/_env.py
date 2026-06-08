"""Sanitized environment for subprocess calls.

Any child process spawned from JARVIS must NOT inherit API keys
(ANTHROPIC_API_KEY, OPENROUTER_API_KEY, KIRO_API_KEY, …) or other
sensitive variables — they have no business in screenshot tools,
audio players, or the like.

Use ``sanitized_env()`` whenever building a ``subprocess.Popen``/
``subprocess.run`` call. The returned dict contains only the
variables needed by GUI/audio/i18n tooling to function.
"""

from __future__ import annotations

import os

# Variables a child process legitimately needs to function:
#   PATH              — locate the binary itself
#   HOME              — config files, ~/.cache, …
#   USER, LOGNAME     — some tools read these
#   LANG, LC_ALL      — locale (i18n / unicode handling)
#   DISPLAY           — X11
#   WAYLAND_DISPLAY   — Wayland
#   XDG_RUNTIME_DIR   — required by Wayland clients + pulse/pipewire
#   XDG_CURRENT_DESKTOP, XDG_SESSION_TYPE — DE adapters parse these
#   DBUS_SESSION_BUS_ADDRESS — notify-send, qdbus, gdbus, ...
#   PULSE_SERVER, PIPEWIRE_RUNTIME_DIR — audio playback
#
# Anything else (incl. *_API_KEY, *_TOKEN, *_SECRET, AWS_*, GH_TOKEN, …)
# is dropped on the floor.
_ALLOWED = frozenset({
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_TYPE",
    "DBUS_SESSION_BUS_ADDRESS",
    "PULSE_SERVER",
    "PIPEWIRE_RUNTIME_DIR",
    # macOS keychain / Aqua need these for `osascript`, `pmset`, etc.
    "TMPDIR",
    "SHELL",
})


def sanitized_env(extra: dict | None = None) -> dict:
    """Return a copy of ``os.environ`` filtered to the allowlist.

    ``extra`` lets callers add variables they own (e.g. ``HF_HOME``
    for a Hugging Face downloader). Extras can shadow allowlisted
    values but cannot reintroduce keys silently — be explicit.
    """
    env = {k: v for k, v in os.environ.items() if k in _ALLOWED}
    if extra:
        env.update(extra)
    return env
