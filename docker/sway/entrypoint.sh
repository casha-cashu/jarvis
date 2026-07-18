#!/bin/bash
set +e

export XDG_RUNTIME_DIR=/tmp/runtime-root
export WAYLAND_DISPLAY=wayland-0
export WLR_BACKENDS=headless
export WLR_LIBINPUT_NO_DEVICES=1
export WLR_RENDERER=pixman

mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"

echo "=== 1. DBus ==="
dbus-daemon --session --fork 2>/dev/null || echo "dbus skipped"

echo "=== 2. seatd ==="
seatd -g root > /tmp/seatd.log 2>&1 &
SEATD_PID=$!
sleep 2
if kill -0 $SEATD_PID 2>/dev/null; then
    echo "seatd running (PID=$SEATD_PID)"
else
    echo "seatd failed. log:"
    cat /tmp/seatd.log
fi

echo "=== 3. sway validate ==="
sway --validate -c /etc/sway/config 2>&1
echo "validate exit: $?"

echo "=== 4. sway start ==="
for FLAG in "--unsupported-gpu" "--my-next-gpu-wont-be-nvidia" ""; do
    echo "--- Trying sway $FLAG ---"
    sway $FLAG -c /etc/sway/config > /tmp/sway.log 2>&1 &
    SWAY_PID=$!
    for i in $(seq 1 10); do
        sleep 1
        SOCK=$(find /tmp -name 'sway-ipc*' -type s 2>/dev/null | head -1)
        if [ -n "$SOCK" ]; then
            export SWAYSOCK="$SOCK"
            if swaymsg -t get_workspaces > /dev/null 2>&1; then
                echo "=== SWAY RUNNING (PID=$SWAY_PID, sock=$SOCK, flag=$FLAG) ==="
                break 2
            fi
        fi
    done
    kill $SWAY_PID 2>/dev/null
    wait $SWAY_PID 2>/dev/null
    echo "sway$FLAG failed:"
    cat /tmp/sway.log
done

if [ -z "$SWAYSOCK" ]; then
    echo "=== FATAL: Sway not starting ==="
    echo "--- sway pkg ---"
    dpkg -l sway 2>/dev/null | tail -2
    echo "--- /var/log/seatd ---"
    ls -la /var/log/ 2>/dev/null
    echo "--- /run ---"
    ls -la /run/ 2>/dev/null
    echo "--- ls -la /dev ---"
    ls -la /dev/ | head -20
    kill $SEATD_PID 2>/dev/null || true
    exit 1
fi

# Run integration tests
cd /app
JARVIS_TEST_DE=sway venv/bin/python -m pytest tests/integration/ -v --timeout=30 || true

kill $SWAY_PID $SEATD_PID 2>/dev/null || true
wait 2>/dev/null || true
echo "=== Done ==="
