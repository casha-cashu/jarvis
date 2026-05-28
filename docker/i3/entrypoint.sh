#!/bin/bash
set -e

# D-Bus
dbus-daemon --session --fork 2>/dev/null || true

# Virtual display
export DISPLAY=:99
Xvfb :99 -screen 0 1280x720x24 &
sleep 1

# i3
i3 -c /etc/i3/config &
I3_PID=$!
sleep 2

# Verify
i3-msg -t get_workspaces > /dev/null 2>&1 || {
    echo "FAIL: i3 not running"
    exit 1
}
echo "i3 is running"

# Run integration tests
cd /app
JARVIS_TEST_DE=i3 venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

# Cleanup
kill $I3_PID 2>/dev/null || true
