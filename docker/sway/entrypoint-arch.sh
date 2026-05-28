#!/bin/bash
set +e

export XDG_RUNTIME_DIR=/tmp/runtime-root
export WAYLAND_DISPLAY=wayland-0
export WLR_BACKENDS=headless
export WLR_LIBINPUT_NO_DEVICES=1
export WLR_RENDERER=pixman

mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

echo "=== Starting seatd ==="
seatd -g root &
sleep 2

echo "=== Starting sway ==="
sway -c /etc/sway/config > /tmp/sway.log 2>&1 &
SWAY_PID=$!

# Wait for sway to be ready
for i in $(seq 1 10); do
    sleep 1
    SOCK=$(find "$XDG_RUNTIME_DIR" -name 'sway-ipc*' -type s 2>/dev/null | head -1)
    if [ -n "$SOCK" ]; then
        export SWAYSOCK="$SOCK"
        if swaymsg -t get_workspaces > /dev/null 2>&1; then
            echo "=== Sway running (PID=$SWAY_PID) ==="
            break
        fi
    fi
    if [ "$i" = 10 ]; then
        echo "=== FAIL: Sway not running ==="
        cat /tmp/sway.log
        ps aux | grep -i sway
        kill $SWAY_PID 2>/dev/null || true
        exit 1
    fi
done

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

kill $SWAY_PID 2>/dev/null || true
echo "=== Done ==="
