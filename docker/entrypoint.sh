#!/bin/bash
set -x  # debug mode — log every command

# D-Bus (optional)
dbus-daemon --session --fork 2>/dev/null || true

# XDG_RUNTIME_DIR — required by Sway
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

echo "=== Starting sway with debug ==="
sway --unsupported-gpu -c /etc/sway/config --debug > /tmp/sway.log 2>&1 &
SWAY_PID=$!

# Wait for Sway to be ready
for i in $(seq 1 15); do
    sleep 1
    if swaymsg -t get_workspaces > /dev/null 2>&1; then
        echo "=== Sway is running ==="
        break
    fi
    if [ "$i" = 15 ]; then
        echo "=== FAIL: Sway not running after 15s ==="
        echo "--- sway.log ---"
        cat /tmp/sway.log 2>/dev/null || echo "(no log)"
        echo "--- pgrep ---"
        ps aux | grep -i sway | head -10
        echo "--- env ---"
        env | grep -E 'WLR|XDG|WAYLAND|DISPLAY' || true
        kill $SWAY_PID 2>/dev/null || true
        exit 1
    fi
done

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

# Cleanup
kill $SWAY_PID 2>/dev/null || true
