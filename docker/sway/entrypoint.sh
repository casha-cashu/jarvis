#!/bin/bash
set +e  # don't exit on error — we handle errors ourselves

# D-Bus (optional)
dbus-daemon --session --fork 2>/dev/null || true

# XDG_RUNTIME_DIR — required by Wayland/Sway
export XDG_RUNTIME_DIR=/tmp/runtime-root
export WAYLAND_DISPLAY=wayland-0
mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

# For root in Docker: use builtin seat backend (no seatd daemon needed)
export LIBSEAT_BACKEND=builtin
export WLR_BACKENDS=headless
export WLR_LIBINPUT_NO_DEVICES=1
export WLR_RENDERER=pixman

echo "=== DEBUG: env ==="
env | grep -E 'WLR|XDG|WAYLAND|LIBSEAT|DISPLAY'

echo "=== Trying sway --validate ==="
sway --validate -c /etc/sway/config 2>&1
echo "(validate exit code: $?)"

echo "=== Starting sway (timeout 20s) ==="
sway --unsupported-gpu -c /etc/sway/config > /tmp/sway.log 2>&1 &
SWAY_PID=$!

# Try both old and new unsupported-gpu flags if first attempt fails
sleep 2
if ! kill -0 $SWAY_PID 2>/dev/null; then
    echo "=== sway exited quickly, trying with --my-next-gpu-wont-be-nvidia ==="
    sway --my-next-gpu-wont-be-nvidia -c /etc/sway/config > /tmp/sway.log 2>&1 &
    SWAY_PID=$!
fi

# Wait for Sway to be ready
for i in $(seq 1 20); do
    sleep 1
    SWAYSOCK=$(find "$XDG_RUNTIME_DIR" -name 'sway-ipc*' -type s 2>/dev/null | head -1)
    if [ -n "$SWAYSOCK" ]; then
        export SWAYSOCK
        if swaymsg -t get_workspaces > /dev/null 2>&1; then
            echo "=== Sway is running (PID=$SWAY_PID, socket=$SWAYSOCK) ==="
            break
        fi
    fi
    if [ "$i" = 20 ]; then
        echo "=== FAIL: Sway not running after 20s ==="
        echo "--- sway.log ---"
        cat /tmp/sway.log 2>/dev/null || echo "(no log file)"
        echo "--- pgrep -a sway ---"
        pgrep -a sway 2>/dev/null || echo "(no sway process)"
        echo "--- ps aux | grep -i sway ---"
        ps aux | grep -i sway | grep -v grep || echo "(no sway in ps)"
        echo "--- ls -la /tmp/runtime-root/ ---"
        ls -la /tmp/runtime-root/ 2>/dev/null || echo "(no runtime dir)"
        echo "--- ENV ---"
        env | grep -E 'WLR|XDG|WAYLAND|LIBSEAT|DISPLAY|SWAY' || echo "(no matching env)"
        kill $SWAY_PID 2>/dev/null || true
        exit 1
    fi
done

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

# Cleanup
kill $SWAY_PID 2>/dev/null || true
wait $SWAY_PID 2>/dev/null || true
