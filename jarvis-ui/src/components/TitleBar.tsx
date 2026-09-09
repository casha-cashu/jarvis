import { Moon, Sun, Laptop, Minus, Maximize2, X } from "lucide-react";
import { useTheme, type Theme } from "../hooks/useTheme";
import { useState, useRef, useEffect } from "react";
import { getBackendStatus, type BackendStatus } from "../api/backend";
import { tauriCommand } from "../utils/ui";


export default function TitleBar() {
  const { theme, setTheme } = useTheme();
  const [themeOpen, setThemeOpen] = useState(false);
  const [status, setStatus] = useState<BackendStatus>({ running: false, connected: false });
  const dropdownRef = useRef<HTMLDivElement>(null);

  const minimize = () => void tauriCommand("minimize");
  const toggleMaximize = () => void tauriCommand("toggleMaximize");
  const close = () => void tauriCommand("close");


  useEffect(() => {
    let active = true;
    const poll = () => {
      getBackendStatus()
        .then((s) => active && setStatus(s))
        .catch(() => undefined);
    };
    poll();
    const interval = window.setInterval(poll, 3000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

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

  const statusColor = status.connected
    ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]"
    : status.running
    ? "bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.7)]"
    : "bg-neutral-500";

  const statusTitle = status.connected
    ? "JARVIS: подключён и готов к работе"
    : status.running
    ? "JARVIS: сервис запускается..."
    : "JARVIS: отключён";

  return (
    <div
      data-tauri-drag-region
      className="flex h-9 items-center justify-between border-b border-border bg-surface px-3 select-none"
    >
      <div className="flex items-center gap-2">
        <div
          className={`h-2.5 w-2.5 rounded-full transition-colors ${statusColor}`}
          title={statusTitle}
        />
        <span className="text-xs font-semibold tracking-wider text-text">
          JARVIS
        </span>
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-1">
        {/* Theme dropdown */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setThemeOpen(!themeOpen)}
            className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
            title="Выбор темы оформления"
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

        <div className="mx-1 h-3.5 w-px bg-border" />

        <button
          onClick={minimize}
          className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
          title="Свернуть"
        >
          <Minus size={13} />
        </button>
        <button
          onClick={toggleMaximize}
          className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
          title="Развернуть"
        >
          <Maximize2 size={13} />
        </button>
        <button
          onClick={close}
          className="rounded p-1.5 text-text-muted hover:bg-danger/20 hover:text-danger"
          title="Закрыть"
        >
          <X size={13} />
        </button>
      </div>
    </div>
  );
}
