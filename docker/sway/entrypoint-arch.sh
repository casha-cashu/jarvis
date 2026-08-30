#!/bin/bash
set +e

export XDG_RUNTIME_DIR=/tmp/runtime-root
export WAYLAND_DISPLAY=wayland-0
export WLR_BACKENDS=headless
export WLR_LIBINPUT_NO_DEVICES=1

mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

# D-Bus: адрес наружу + демон уведомлений (notify-send)
dbus-daemon --session --fork --print-address > /tmp/dbus-addr 2>/dev/null || true
if [ -s /tmp/dbus-addr ]; then
    export DBUS_SESSION_BUS_ADDRESS="$(cat /tmp/dbus-addr)"
fi
# PulseAudio null-sink для pactl-команд
pulseaudio --start --disallow-exit --exit-idle-time=-1 2>/dev/null || true
pactl load-module module-null-sink sink_name=jarvis 2>/dev/null || true

echo "=== Starting sway (headless) ==="
sway -c /etc/sway/config > /tmp/sway.log 2>&1 &
SWAY_PID=$!

# Wait for sway to be ready (up to 20s)
for i in $(seq 1 20); do
    sleep 1
    SOCK=$(find "$XDG_RUNTIME_DIR" -name 'sway-ipc*' -type s 2>/dev/null | head -1)
    if [ -n "$SOCK" ]; then
        export SWAYSOCK="$SOCK"
        if swaymsg -t get_workspaces > /dev/null 2>&1; then
            # wl-сокет: sway мог занять wayland-1, а не wayland-0 —
            # grim/dunst требуют АКТУАЛЬНОЕ имя
            WL=$(find "$XDG_RUNTIME_DIR" -name 'wayland-*' -type s 2>/dev/null | head -1)
            [ -n "$WL" ] && export WAYLAND_DISPLAY="$(basename "$WL")"
            echo "=== Sway running (PID=$SWAY_PID, WAYLAND_DISPLAY=$WAYLAND_DISPLAY) ==="
            break
        fi
    fi
    if [ "$i" = 20 ]; then
        echo "=== FAIL: Sway not running ==="
        cat /tmp/sway.log
        ps aux | grep -i sway
        kill $SWAY_PID 2>/dev/null || true
        exit 1
    fi
done

# Демон уведомлений: только после работающего sway (без композитора
# dunst крушится, как в i3 до Xvfb)
dunst >/dev/null 2>&1 &

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30
RC=$?

if [ "${RC:-0}" -ne 0 ]; then
    echo "FAIL: integration tests exited $RC"
fi
kill $SWAY_PID 2>/dev/null || true
echo "=== Done ==="
if [ "${RC:-0}" -ne 0 ]; then
    exit $RC
fi
