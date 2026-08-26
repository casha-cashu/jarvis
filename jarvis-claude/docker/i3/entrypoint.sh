#!/bin/bash
set +e

# D-Bus (optional)
dbus-daemon --session --fork 2>/dev/null || true

# Virtual display
export DISPLAY=:99
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!

# i3
i3 -c /etc/i3/config 2>&1 &
I3_PID=$!

# Wait for i3 to be ready
for i in $(seq 1 10); do
    sleep 1
    if i3-msg -t get_workspaces > /dev/null 2>&1; then
        echo "i3 is running"
        break
    fi
    if [ "$i" = 10 ]; then
        echo "FAIL: i3 not running after 10s"
        kill $I3_PID $XVFB_PID 2>/dev/null || true
        exit 1
    fi
done

# Run integration tests
cd /app
JARVIS_TEST_DE=i3 venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

# Cleanup
kill $I3_PID 2>/dev/null || true
