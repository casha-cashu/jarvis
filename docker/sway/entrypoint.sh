#!/bin/bash
set -e

# D-Bus
dbus-daemon --session --fork 2>/dev/null || true

# seatd
seatd -g root &
sleep 1

# XDG_RUNTIME_DIR
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p $XDG_RUNTIME_DIR
chmod 0700 $XDG_RUNTIME_DIR

# Sway headless
sway -c /etc/sway/config &
SWAY_PID=$!
sleep 3

# Verify
swaymsg -t get_workspaces > /dev/null 2>&1 || {
    echo "FAIL: Sway not running"
    exit 1
}
echo "Sway is running"

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

# Cleanup
kill $SWAY_PID 2>/dev/null || true
