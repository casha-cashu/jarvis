#!/bin/bash
set +e

# D-Bus: адрес экспортируем — notify-send/pulseaudio должны видеть одну шину
dbus-daemon --session --fork --print-address > /tmp/dbus-addr 2>/dev/null || true
if [ -s /tmp/dbus-addr ]; then
    export DBUS_SESSION_BUS_ADDRESS="$(cat /tmp/dbus-addr)"
fi

# PulseAudio с null-sink: pactl-команды требуют живой сервер
pulseaudio --start --disallow-exit --exit-idle-time=-1 2>/dev/null || true
pactl load-module module-null-sink sink_name=jarvis 2>/dev/null || true

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

# Демон уведомлений: только после X (до Xvfb dunst крушится, signal 5)
dunst >/dev/null 2>&1 &

# Run integration tests
cd /app
JARVIS_TEST_DE=i3 venv/bin/python -m pytest tests/integration/ -v --timeout=30
RC=$?

# Cleanup
if [ "${RC:-0}" -ne 0 ]; then
    echo "FAIL: integration tests exited $RC"
fi
kill $I3_PID 2>/dev/null || true
if [ "${RC:-0}" -ne 0 ]; then
    exit $RC
fi
