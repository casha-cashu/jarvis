import type { Tab } from "../hooks/useTab";
import { MessageSquare, Sliders, Gauge, History, type LucideIcon } from "lucide-react";

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

  return (
    <nav className="flex w-14 flex-col items-center gap-1 border-r border-border bg-surface py-2">
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
            title={item.label}
          >
            <Icon size={18} />
            <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap rounded-md bg-surface-2 px-2 py-1 text-xs text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
              {item.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
