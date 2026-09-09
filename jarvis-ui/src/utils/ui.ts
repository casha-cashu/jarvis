export function checkIsAtBottom(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  threshold = 80,
): boolean {
  const distFromBottom = scrollHeight - scrollTop - clientHeight;
  return distFromBottom <= threshold;
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    if (typeof document !== "undefined" && document.createElement) {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(textarea);
      return ok;
    }
    return false;
  } catch (err) {
    console.warn("Failed to copy to clipboard:", err);
    return false;
  }
}

function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  return "__TAURI_INTERNALS__" in window;
}

export async function tauriCommand(
  cmd: "minimize" | "toggleMaximize" | "close",
): Promise<void> {
  if (!isTauri()) return;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const w = getCurrentWindow();
    if (cmd === "minimize") await w.minimize();
    else if (cmd === "toggleMaximize") await w.toggleMaximize();
    else if (cmd === "close") await w.close();
  } catch (err) {
    console.warn(`Window control '${cmd}' failed:`, err);
  }
}

export function clampNumber(val: unknown, min: number, max: number, fallback: number): number {
  const n = typeof val === "number" ? val : parseFloat(String(val));
  if (isNaN(n) || !isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

export function clampInt(val: unknown, min: number, max: number, fallback: number): number {
  const n = typeof val === "number" ? val : parseInt(String(val), 10);
  if (isNaN(n) || !isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(n)));
}
