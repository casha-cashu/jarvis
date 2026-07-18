"""Тесты для jarvis._env.sanitized_env."""

from jarvis._env import sanitized_env


def test_drops_known_secret_vars(monkeypatch):
    """API ключи и токены не должны попадать в окружение child-процессов."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak-me")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-leak-me")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-leak-me")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-leak-me")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-leak-me")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/user")

    env = sanitized_env()

    for forbidden in (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
    ):
        assert forbidden not in env, f"{forbidden} leaked into sanitized_env()"


def test_keeps_essential_vars(monkeypatch):
    """Окружение должно содержать PATH/HOME и переменные DE/audio,
    иначе дочерние процессы (notify-send, paplay) не запустятся."""
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")

    env = sanitized_env()

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/user"
    assert env["DISPLAY"] == ":0"
    assert env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["DBUS_SESSION_BUS_ADDRESS"].startswith("unix:")


def test_extra_can_add_keys(monkeypatch):
    """Вызывающий код может явно добавить переменную (например LD_LIBRARY_PATH
    для piper) через extra=."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leak-me")  # должен быть выкинут
    monkeypatch.setenv("PATH", "/usr/bin")

    env = sanitized_env(extra={"LD_LIBRARY_PATH": "/opt/piper/lib"})

    assert env["LD_LIBRARY_PATH"] == "/opt/piper/lib"
    assert "ANTHROPIC_API_KEY" not in env


def test_arbitrary_vars_dropped(monkeypatch):
    """Любая переменная, не входящая в allowlist, должна быть отброшена —
    даже если выглядит безобидно (защита от непредвиденных утечек)."""
    monkeypatch.setenv("MY_CUSTOM_SECRET", "x")
    monkeypatch.setenv("DATABASE_URL", "postgres://...")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = sanitized_env()

    assert "MY_CUSTOM_SECRET" not in env
    assert "DATABASE_URL" not in env
