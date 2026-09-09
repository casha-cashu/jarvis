import { useEffect, useState } from "react";
import type { Tab } from "../hooks/useTab";
import { MessageSquare, Sliders, Gauge, History, Radio, type LucideIcon } from "lucide-react";
import { getContinuousMode, setContinuousMode } from "../api/backend";

const items: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "chat", label: "Чат", icon: MessageSquare },
  { id: "settings", label: "Настройки", icon: Sliders },
  { id: "status", label: "Статус", icon: Gauge },
  { id: "history", label: "История", icon: History },
];

interface SidebarProps {
  tab: Tab;
  setTab: (tab: Tab) => void;
}

export default function Sidebar({ tab, setTab }: SidebarProps) {
  const [continuous, setContinuous] = useState(false);

  useEffect(() => {
    getContinuousMode().then(setContinuous).catch(() => undefined);
    const handler = (e: Event) => {
      const custom = e as CustomEvent<boolean>;
      if (typeof custom.detail === "boolean") {
        setContinuous(custom.detail);
      }
    };
    window.addEventListener("jarvis:continuous-change", handler);
    return () => {
      window.removeEventListener("jarvis:continuous-change", handler);
    };
  }, []);

  const toggleContinuous = async () => {
    const next = !continuous;
    setContinuous(next);
    try {
      await setContinuousMode(next, true);
    } catch {
      setContinuous(!next);
    }
  };

  return (
    <nav className="relative z-20 flex w-14 shrink-0 flex-col items-center justify-between border-r border-border bg-surface py-2">
      <div className="flex w-full flex-col items-center gap-1">
        {items.map((item) => {
          const Icon = item.icon;
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`group relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors ${
                active
                  ? "bg-accent-bg text-accent"
                  : "text-text-muted hover:bg-surface-2 hover:text-text"
              }`}
              aria-label={item.label}
            >
              <Icon size={18} className="shrink-0" />
              <span className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-2 whitespace-nowrap rounded-md bg-surface-2 px-2 py-1 text-xs text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100 z-50">
                {item.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* Quick continuous mode status/toggle button */}
      <div className="flex w-full flex-col items-center gap-1 pb-1">
        <button
          onClick={toggleContinuous}
          className={`group relative flex h-10 w-10 items-center justify-center rounded-lg transition-all ${
            continuous
              ? "bg-accent/20 text-accent animate-pulse"
              : "text-text-muted hover:bg-surface-2 hover:text-text"
          }`}
          aria-label={continuous ? "Постоянная прослушка: ВКЛ" : "Постоянная прослушка: ВЫКЛ"}
        >
          <Radio size={18} className="shrink-0" />
          <span className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-2 whitespace-nowrap rounded-md bg-surface-2 px-2 py-1 text-xs text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100 z-50">
            {continuous ? "Прослушка: ВКЛ (слушает всё)" : "Прослушка: по 'Джарвис'"}
          </span>
        </button>
      </div>
    </nav>
  );
}
