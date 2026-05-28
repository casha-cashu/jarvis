#!/bin/bash
set +e

# D-Bus (optional, don't fail if unavailable)
dbus-daemon --session --fork 2>/dev/null || true

# XDG_RUNTIME_DIR — required by Sway
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

# Sway headless (root in Docker — no seatd needed)
sway --unsupported-gpu -c /etc/sway/config 2>&1 &
SWAY_PID=$!

# Wait for Sway to be ready
for i in $(seq 1 10); do
    sleep 1
    if swaymsg -t get_workspaces > /dev/null 2>&1; then
        echo "Sway is running"
        break
    fi
    if [ "$i" = 10 ]; then
        echo "FAIL: Sway not running after 10s"
        swaymsg -t get_workspaces 2>&1 || true
        kill $SWAY_PID 2>/dev/null || true
        exit 1
    fi
done

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

# Cleanup
kill $SWAY_PID 2>/dev/null || true
