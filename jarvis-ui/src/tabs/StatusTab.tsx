import { useEffect, useRef, useState } from "react";
import { Activity, Mic, Cpu, Clock, AlertCircle } from "lucide-react";
import {
  getBackendStatus,
  getSystemStats,
  getBackendTimers,
  startBackend,
  type BackendStatus,
  type BackendTimer,
  type SystemStats,
} from "../api/backend";
import { getActiveModel, loadProviders } from "../api/providers";

interface Stat {
  label: string;
  value: string;
  icon: typeof Activity;
  color?: string;
}

function formatUptime(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}ч ${minutes}мин`;
}

export default function StatusTab() {
  const [backend, setBackend] = useState<BackendStatus>({ running: false, connected: false });
  const [backendError, setBackendError] = useState<string | null>(null);
  const [system, setSystem] = useState<SystemStats | null>(null);
  const [timers, setTimers] = useState<BackendTimer[] | null>(null);
  const activeModel = getActiveModel();
  const activeProvider = activeModel
    ? loadProviders().find((p) => p.id === activeModel.providerId)
    : null;

  const stats: Stat[] = [
    { label: "Платформа", value: system?.platform ?? "—", icon: Mic, color: "text-accent" },
    { label: "Нагрузка", value: system ? system.loadAverage.toFixed(2) : "—", icon: Cpu },
    { label: "Память", value: system ? `${system.memoryUsedMb}/${system.memoryTotalMb} МБ` : "—", icon: Activity },
    { label: "Uptime", value: system ? formatUptime(system.uptimeSeconds) : "—", icon: Clock },
  ];

  const warnings: { title: string; detail: string }[] = [];
  if (!activeModel) {
    warnings.push({
      title: "Модель не выбрана",
      detail: "Откройте Чат и выберите модель в шапке (провайдеры задаются в Настройках)",
    });
  }

  // Ref вместо захвата state в замыкании interval'а: deps [] фиксировали
  // начальный {running:false} — секция таймеров никогда не грузилась.
  const backendRef = useRef(backend);
  useEffect(() => {
    backendRef.current = backend;
  }, [backend]);

  useEffect(() => {
    let active = true;
    const refresh = () => {
      getBackendStatus().then((status) => active && setBackend(status)).catch(() => undefined);
      getSystemStats().then((stats) => active && setSystem(stats)).catch(() => undefined);
      if (backendRef.current.running || backendRef.current.connected) {
        getBackendTimers()
          .then((t) => active && setTimers(t))
          .catch(() => active && setTimers([]));
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { active = false; window.clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleStart = async () => {
    setBackendError(null);
    try {
      await startBackend();
      setBackend(await getBackendStatus());
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : "Не удалось запустить backend");
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto px-6 py-6">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-medium text-text">Статус системы</h2>
          <button onClick={handleStart} disabled={backend.running} className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
            {backend.running ? "Backend запущен" : "Запустить backend"}
          </button>
        </div>
        <div className="rounded-lg border border-border bg-surface px-4 py-3 text-sm">
          <span className={backend.connected ? "text-accent" : "text-text-muted"}>● </span>
          {backend.connected ? "Текстовый backend подключён" : "Backend не подключён"}
          {activeModel && (
            <span className="ml-3 text-xs text-text-muted">
              {activeProvider?.name ?? "?"}/{activeModel.model}
            </span>
          )}
          {backendError && <p className="mt-1 text-xs text-danger">{backendError}</p>}
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {stats.map((s) => {
            const Icon = s.icon;
            return (
              <div
                key={s.label}
                className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium tracking-wide text-text-muted">
                    {s.label.toUpperCase()}
                  </span>
                  <Icon
                    size={14}
                    className={s.color ?? "text-text-muted"}
                  />
                </div>
                <span className="truncate text-sm font-medium text-text">
                  {s.value}
                </span>
                <div
                  className={`h-1 w-full rounded-full ${
                    s.color ? "bg-accent/20" : "bg-surface-2"
                  }`}
                >
                  <div
                    className={`h-1 rounded-full ${
                      s.color ? "bg-accent" : "bg-text-muted"
                    }`}
                    style={{ width: "100%" }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* Active timers — real data from backend */}
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-text-muted">
            АКТИВНЫЕ ТАЙМЕРЫ
          </h3>
          {!timers || timers.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">
              Нет активных таймеров
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {timers.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between rounded-lg border border-border bg-surface px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <Clock size={16} className="text-accent" />
                    <span className="text-sm text-text">{t.text}</span>
                  </div>
                  <span className="font-mono text-sm text-accent">
                    {t.left}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Warnings — only dynamic ones */}
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-text-muted">ПРЕДУПРЕЖДЕНИЯ</h3>
          {warnings.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">
              Всё в порядке
            </div>
          ) : (
            warnings.map((w) => (
              <div key={w.title} className="flex items-start gap-2 rounded-lg border border-border bg-surface px-4 py-3">
                <AlertCircle size={16} className="mt-0.5 shrink-0 text-warn" />
                <div>
                  <p className="text-sm text-text">{w.title}</p>
                  <p className="text-xs text-text-muted">{w.detail}</p>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
