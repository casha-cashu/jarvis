# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: JARVIS text-mode sidecar for the Tauri UI.

Builds a onefile binary from jarvis/ui_bridge.py (line-delimited JSONL
protocol on stdout). Audio/ML heavies are excluded on purpose — this is
the text core; STT/VAD/TTS never load here (dry_run=True).
"""

from pathlib import Path

REPO_ROOT = Path(SPECPATH)

a = Analysis(
    [str(REPO_ROOT / "jarvis" / "ui_bridge.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    # Словари команд/приложений нужны в packaged-режиме: без них в
    # deb/AppImage не работают локальные команды, запуск приложений и NLU.
    # Резолвятся в рантайме через jarvis.resources.resource_path (_MEIPASS).
    datas=[
        (str(REPO_ROOT / "data" / "commands.json"), "data"),
        (str(REPO_ROOT / "data" / "apps.json"), "data"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # audio / ML heavies
        "torch",
        "torchvision",
        "torchaudio",
        "faster_whisper",
        "ctranslate2",
        "pyaudio",
        "silero_vad",
        "vosk",
        # plotting / data / GUI
        "matplotlib",
        "pandas",
        "PyQt5",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="jarvis-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
