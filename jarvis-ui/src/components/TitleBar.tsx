import { Moon, Sun, Laptop, Minus, Maximize2, X } from "lucide-react";
import { useTheme, type Theme } from "../hooks/useTheme";
import { useState, useRef, useEffect } from "react";

function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  return "__TAURI_INTERNALS__" in window;
}

async function tauriCommand(
  cmd: "minimize" | "toggleMaximize" | "close",
): Promise<void> {
  if (!isTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const w = getCurrentWindow();
  if (cmd === "minimize") await w.minimize();
  else if (cmd === "toggleMaximize") await w.toggleMaximize();
  else if (cmd === "close") await w.close();
}

export default function TitleBar() {
  const { theme, setTheme } = useTheme();
  const [themeOpen, setThemeOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const minimize = () => tauriCommand("minimize");
  const toggleMaximize = () => tauriCommand("toggleMaximize");
  const close = () => tauriCommand("close");

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setThemeOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const cycleTheme = (t: Theme) => {
    setTheme(t);
    setThemeOpen(false);
  };

  const ThemeIcon =
    theme === "dark" ? Moon : theme === "light" ? Sun : Laptop;

  return (
    <div
      data-tauri-drag-region
      className="flex h-9 items-center justify-between border-b border-border bg-surface px-3"
    >
      <div className="flex items-center gap-2">
        <div className="h-2.5 w-2.5 rounded-full bg-accent shadow-[0_0_6px_var(--color-accent)]" />
        <span className="text-xs font-medium tracking-wide text-text-muted">
          JARVIS
        </span>
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-1">
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setThemeOpen(!themeOpen)}
            className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
            title="Тема"
          >
            <ThemeIcon size={14} />
          </button>
          {themeOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-36 rounded-md border border-border bg-surface py-1 shadow-xl">
              {([
                ["dark", "Тёмная", Moon],
                ["light", "Светлая", Sun],
                ["system", "Системная", Laptop],
              ] as const).map(([t, label, Icon]) => (
                <button
                  key={t}
                  onClick={() => cycleTheme(t)}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface-2 ${
                    theme === t ? "text-accent" : "text-text"
                  }`}
                >
                  <Icon size={14} />
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mx-1.5 h-4 w-px bg-border" />

        <button
          onClick={minimize}
          className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
          title="Свернуть"
        >
          <Minus size={14} />
        </button>
        <button
          onClick={toggleMaximize}
          className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
          title="Развернуть"
        >
          <Maximize2 size={12} />
        </button>
        <button
          onClick={close}
          className="rounded p-1.5 text-text-muted hover:bg-danger hover:text-white"
          title="Закрыть"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
