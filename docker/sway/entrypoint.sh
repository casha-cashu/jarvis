#!/bin/bash
set +e

export XDG_RUNTIME_DIR=/tmp/runtime-root
export WAYLAND_DISPLAY=wayland-0
export LIBSEAT_BACKEND=builtin
export WLR_BACKENDS=headless
export WLR_LIBINPUT_NO_DEVICES=1
export WLR_RENDERER=pixman

mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

# Pre-flight: validate & check deps
sway --validate -c /etc/sway/config > /tmp/validate.log 2>&1
if [ $? -ne 0 ]; then
    echo "FAIL: config validation failed"
    cat /tmp/validate.log
    exit 1
fi

# Try different GPU flags
for FLAG in "--unsupported-gpu" "--my-next-gpu-wont-be-nvidia" ""; do
    echo "=== Trying sway $FLAG ==="
    sway $FLAG -c /etc/sway/config > /tmp/sway.log 2>&1 &
    SWAY_PID=$!

    # Wait up to 10 seconds for IPC socket
    for i in $(seq 1 10); do
        sleep 1
        SOCK=$(find "$XDG_RUNTIME_DIR" -name 'sway-ipc*' -type s 2>/dev/null | head -1)
        if [ -n "$SOCK" ]; then
            export SWAYSOCK="$SOCK"
            if swaymsg -t get_workspaces > /dev/null 2>&1; then
                echo "=== Sway running (PID=$SWAY_PID, flag=$FLAG) ==="
                break 2  # break out of both loops
            fi
        fi
    done

    # Sway failed to start with this flag
    kill $SWAY_PID 2>/dev/null || true
    wait $SWAY_PID 2>/dev/null || true
    echo "sway$FLAG failed. Log:"
    cat /tmp/sway.log 2>/dev/null
done

# Check if we found a working flag
if [ -z "$SWAYSOCK" ]; then
    echo "=== FATAL: Sway won't start with any flag ==="
    echo "--- dpkg info ---"
    dpkg -l sway 2>/dev/null || echo "sway not installed"
    dpkg -l 'libwlroots*' 2>/dev/null || echo "wlroots not found"
    echo "--- ldd ---"
    ldd /usr/bin/sway 2>/dev/null | grep "not found" || echo "all libs resolved"
    echo "--- /var/log ---"
    ls /var/log/ 2>/dev/null
    echo "--- dmesg ---"
    dmesg 2>/dev/null | tail -5 || echo "no dmesg"
    exit 1
fi

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

# Cleanup
kill $SWAY_PID 2>/dev/null || true
wait $SWAY_PID 2>/dev/null || true
echo "=== Done ==="
