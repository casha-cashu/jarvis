#!/usr/bin/env python3
"""Desktop Control MCP Server for Linux / Wayland (Hyprland).

Provides clean, standardized MCP tools for GUI automation:
- mouse_click: Click at exact screen coordinates (x, y).
- type_text: Type string using wtype.
- press_key: Press keyboard key (e.g. Return, Escape, BackSpace).
- take_screenshot: Capture screenshot using grim.
- get_cursor_pos: Return current (x, y) coordinates.
- get_windows: List all open windows from hyprctl clients.
"""

import subprocess
import time
import evdev
from evdev import UInput, ecodes as e
from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="desktop-control",
    version="1.0.0",
    instructions="Native Linux Desktop / Wayland automation tools: mouse clicking, typing, keys, screenshots.",
)

def _get_cursor_pos() -> tuple[int, int]:
    try:
        out = subprocess.check_output(["hyprctl", "cursorpos"], text=True).strip()
        parts = [int(x.strip()) for x in out.split(",")]
        return parts[0], parts[1]
    except Exception:
        return 0, 0

def _move_to(ui: UInput, target_x: int, target_y: int) -> None:
    cur_x, cur_y = _get_cursor_pos()
    dx = target_x - cur_x
    dy = target_y - cur_y
    steps = max(abs(dx), abs(dy)) // 50 + 1
    step_dx = dx / steps
    step_dy = dy / steps

    for _ in range(steps):
        cur_x, cur_y = _get_cursor_pos()
        rem_x = target_x - cur_x
        rem_y = target_y - cur_y
        if abs(rem_x) == 0 and abs(rem_y) == 0:
            break
        mx = int(round(rem_x if abs(rem_x) < abs(step_dx) else step_dx))
        my = int(round(rem_y if abs(rem_y) < abs(step_dy) else step_dy))
        ui.write(e.EV_REL, e.REL_X, mx)
        ui.write(e.EV_REL, e.REL_Y, my)
        ui.syn()
        time.sleep(0.01)

    cur_x, cur_y = _get_cursor_pos()
    if cur_x != target_x or cur_y != target_y:
        ui.write(e.EV_REL, e.REL_X, target_x - cur_x)
        ui.write(e.EV_REL, e.REL_Y, target_y - cur_y)
        ui.syn()
        time.sleep(0.02)


@server.tool()
def mouse_click(x: int, y: int, button: str = "left") -> str:
    """Move cursor to (x, y) and click mouse button ('left', 'right', 'middle')."""
    cap = {
        e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL],
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
    }
    btn_code = e.BTN_LEFT
    if button.lower() == "right":
        btn_code = e.BTN_RIGHT
    elif button.lower() == "middle":
        btn_code = e.BTN_MIDDLE

    ui = UInput(cap, name="mcp-desktop-mouse")
    try:
        time.sleep(0.1)
        _move_to(ui, x, y)
        time.sleep(0.05)
        ui.write(e.EV_KEY, btn_code, 1)
        ui.syn()
        time.sleep(0.05)
        ui.write(e.EV_KEY, btn_code, 0)
        ui.syn()
        time.sleep(0.05)
    finally:
        ui.close()
    return f"Clicked {button} at ({x}, {y})"


@server.tool()
def type_text(text: str) -> str:
    """Type text using wtype."""
    subprocess.run(["wtype", text], check=True)
    return f"Typed: {text}"


@server.tool()
def press_key(key: str) -> str:
    """Press special keyboard key (e.g. Return, Escape, Tab, BackSpace, Up, Down)."""
    subprocess.run(["wtype", "-k", key], check=True)
    return f"Pressed key: {key}"


@server.tool()
def take_screenshot(geometry: str = None, output_path: str = None) -> str:
    """Capture screen or region using grim. Returns output file path."""
    if not output_path:
        output_path = f"/tmp/mcp_screenshot_{int(time.time())}.png"
    cmd = ["grim"]
    if geometry:
        cmd.extend(["-g", geometry])
    cmd.append(output_path)
    subprocess.run(cmd, check=True)
    return output_path


@server.tool()
def get_cursor_pos() -> str:
    """Get current cursor position (x, y) on the screen."""
    x, y = _get_cursor_pos()
    return f"{x}, {y}"


@server.tool()
def get_windows() -> str:
    """List all open windows in Hyprland with titles, classes, and geometry."""
    try:
        return subprocess.check_output(["hyprctl", "clients"], text=True)
    except Exception as exc:
        return f"Error querying hyprctl: {exc}"


if __name__ == "__main__":
    server.run(transport="stdio")
