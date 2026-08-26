---
name: adapter-pattern
description: "Use when creating or editing platform adapters in jarvis/adapters/. Covers i3, Sway, Hyprland, KDE, GNOME, and macOS adapters."
---

# Adapter Pattern Skill

## Architecture

Platform adapters in `jarvis/adapters/` encapsulate DE/WM-specific behavior:

```
Jarvis.detect_platform() → AdapterBase subclass
    ├── i3.py     — i3 (X11) window manager
    ├── sway.py   — Sway (Wayland) compositor
    ├── hyprland.py — Hyprland (Wayland) compositor
    ├── kde.py    — KDE Plasma desktop
    ├── gnome.py  — GNOME desktop
    └── macos.py  — macOS
```

## Conventions

- Adapters extend `AdapterBase` (`jarvis/adapters/base.py`)
- Commands are registered via `_add_platform_commands()` in `jarvis/__init__.py`
  at import time
- **No `shell=True`** — adapter command strings go through `shlex.split` and
  `subprocess.Popen(env=sanitized_env())`
- For time-sensitive commands (timestamps, interactive geometry via `slurp`),
  pass a **callable** as `cmd`, not the call result. `CommandExecutor._run`
  invokes callables at execute time.

## Screenshot Behavior

- `i3.py`, `gnome.py`, `macos.py`, `sway.py` — resolve `~` and `datetime.now()`
  in Python
- `kde.py` and `hyprland.py` — use tools (spectacle / grimblast) that own
  their own naming — leave those alone

## Input Text

`input_text` in `base.py` uses shell-style `wtype || xdotool`. Live dictation
goes through `jarvis/modules/dictation.py:_type_text`. Two adapter tests assert
`input_text` return type — watch them if touching `base.py`.

## Adding a New Adapter

1. Create `jarvis/adapters/<name>.py` extending `AdapterBase`
2. Implement `detect()`, `_add_platform_commands()`, `_get_platform_info()`
3. Register in `jarvis/__init__.py` platform detection chain
4. Add tests in `tests/test_adapters.py`
5. All subprocess calls must use `env=sanitized_env()`