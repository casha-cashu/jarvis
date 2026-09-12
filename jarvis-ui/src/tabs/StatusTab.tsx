import { useEffect, useRef, useState } from "react";
import { Activity, Cpu, Clock, AlertCircle, Monitor, RefreshCw, Square, Play, Mic, MicOff, Bug } from "lucide-react";
import { listen } from "@tauri-apps/api/event";
import {
  getBackendStatus,
  getSystemStats,
  getBackendTimers,
  getVoiceMode,
  setVoiceMode,
  startBackend,
  stopBackend,
  restartBackend,
  exportDiagnostics,
  type BackendStatus,
  type BackendTimer,
  type SystemStats,
} from "../api/backend";
import { getActiveModel, loadProviders } from "../api/providers";

interface StatItem {
  label: string;
  value: string;
  percent: number;
  icon: typeof Activity;
  color?: string;
}

function formatUptime(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}ч ${minutes}мин`;
}

interface StatusTabProps {
  isActive?: boolean;
}

export default function StatusTab({ isActive = true }: StatusTabProps) {
  const [backend, setBackend] = useState<BackendStatus>({ running: false, connected: false });
  const [backendActionLoading, setBackendActionLoading] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [system, setSystem] = useState<SystemStats | null>(null);
  const [timers, setTimers] = useState<BackendTimer[] | null>(null);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<string>("Отключен");
  const [voiceText, setVoiceText] = useState<string | null>(null);
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [diagLoading, setDiagLoading] = useState(false);
  const [diagPath, setDiagPath] = useState<string | null>(null);
  const [diagError, setDiagError] = useState<string | null>(null);
  const activeModel = getActiveModel();
  const activeProvider = activeModel
    ? loadProviders().find((p) => p.id === activeModel.providerId)
    : null;

  const ramPercent =
    system && system.memoryTotalMb > 0
      ? Math.min(100, Math.max(0, Math.round((system.memoryUsedMb / system.memoryTotalMb) * 100)))
      : 0;

  const cpuPercent =
    system && typeof system.loadAverage === "number"
      ? Math.min(100, Math.max(0, Math.round(system.loadAverage * 25)))
      : 0;

  const stats: StatItem[] = [
    {
      label: "Платформа",
      value: system?.platform ? system.platform.toUpperCase() : "—",
      percent: 100,
      icon: Monitor,
      color: "text-accent",
    },
    {
      label: "Нагрузка CPU",
      value:
        system && typeof system.loadAverage === "number"
          ? `${system.loadAverage.toFixed(2)} (${cpuPercent}%)`
          : "—",
      percent: cpuPercent,
      icon: Cpu,
    },
    {
      label: "Память RAM",
      value: system ? `${system.memoryUsedMb} / ${system.memoryTotalMb} МБ` : "—",
      percent: ramPercent,
      icon: Activity,
    },
    {
      label: "Время работы",
      value:
        system && typeof system.uptimeSeconds === "number"
          ? formatUptime(system.uptimeSeconds)
          : "—",
      percent: 100,
      icon: Clock,
    },
  ];

  const warnings: { title: string; detail: string }[] = [];
  if (!activeModel && !backend.connected) {
    warnings.push({
      title: "Модель не выбрана",
      detail: "Откройте Чат и выберите модель в шапке (провайдеры настраиваются в Настройках)",
    });
  }
  if (!backend.connected) {
    warnings.push({
      title: "JARVIS отключён",
      detail: "Запустите backend сервиса кнопкой вверху справа для работы голосовых команд и агента",
    });
  }

  const backendRef = useRef(backend);
  useEffect(() => {
    backendRef.current = backend;
  }, [backend]);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    listen<string | { status: string; text?: string }>("voice-event", (event) => {
      if (cancelled) return;
      let data: { status: string; text?: string };
      if (typeof event.payload === "string") {
        try {
          data = JSON.parse(event.payload);
        } catch {
          data = { status: event.payload };
        }
      } else {
        data = event.payload;
      }
      if (data.status === "listening") {
        setVoiceStatus("Ожидает «Джарвис»");
        setVoiceEnabled(true);
      } else if (data.status === "stopped") {
        setVoiceStatus("Отключен");
        setVoiceEnabled(false);
        setVoiceText(null);
      } else if (data.status === "partial") {
        setVoiceStatus("Слышит речь...");
        if (data.text) setVoiceText(data.text);
      } else if (data.status === "wake_word_required") {
        setVoiceStatus("Требуется «Джарвис»");
        if (data.text) setVoiceText(data.text);
      } else if (data.status === "recognized" || data.status === "processing") {
        setVoiceStatus("Обработка...");
        if (data.text) setVoiceText(data.text);
      } else if (data.status === "speaking") {
        setVoiceStatus("Озвучивает ответ...");
      } else if (data.status === "finished") {
        setVoiceStatus("Готово");
      }
    })
      .then((fn) => {
        if (cancelled) {
          fn();
        } else {
          unlisten = fn;
        }
      })
      .catch(() => undefined);

    const onVoiceModeChange = (e: Event) => {
      const customEvent = e as CustomEvent<boolean>;
      setVoiceEnabled(customEvent.detail);
      if (!customEvent.detail) {
        setVoiceStatus("Отключен");
      }
    };
    window.addEventListener("jarvis:voice-mode-change", onVoiceModeChange);

    return () => {
      cancelled = true;
      if (unlisten) unlisten();
      window.removeEventListener("jarvis:voice-mode-change", onVoiceModeChange);
    };
  }, []);

  useEffect(() => {
    if (!isActive) return;
    let active = true;
    const refresh = () => {
      getBackendStatus()
        .then((status) => active && setBackend(status))
        .catch(() => {
          if (active) setBackend((prev) => ({ ...prev, connected: false }));
        });
      getSystemStats()
        .then((stats) => active && setSystem(stats))
        .catch(() => undefined);
      if (backendRef.current.running || backendRef.current.connected) {
        getBackendTimers()
          .then((t) => active && setTimers(t))
          .catch(() => active && setTimers([]));
        getVoiceMode()
          .then((enabled) => {
            if (active) {
              setVoiceEnabled(enabled);
              if (!enabled) setVoiceStatus("Отключен");
            }
          })
          .catch(() => undefined);
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [isActive]);


  const handleStart = async () => {
    setBackendActionLoading(true);
    setBackendError(null);
    try {
      await startBackend();
      setBackend(await getBackendStatus());
    } catch (error) {
      setBackend((prev) => ({ ...prev, connected: false }));
      setBackendError(error instanceof Error ? error.message : "Не удалось запустить backend");
    } finally {
      setBackendActionLoading(false);
    }
  };

  const handleStop = async () => {
    setBackendActionLoading(true);
    setBackendError(null);
    try {
      await stopBackend();
      setBackend(await getBackendStatus());
      setTimers([]);
      setVoiceEnabled(false);
      setVoiceStatus("Отключен");
      setVoiceText(null);
    } catch (error) {
      setBackend((prev) => ({ ...prev, connected: false }));
      setBackendError(error instanceof Error ? error.message : "Не удалось остановить backend");
    } finally {
      setBackendActionLoading(false);
    }
  };

  const handleRestart = async () => {
    setBackendActionLoading(true);
    setBackendError(null);
    try {
      await restartBackend();
      setBackend(await getBackendStatus());
    } catch (error) {
      setBackend((prev) => ({ ...prev, connected: false }));
      setBackendError(error instanceof Error ? error.message : "Не удалось перезапустить backend");
    } finally {
      setBackendActionLoading(false);
    }
  };

  const toggleVoiceMode = async () => {
    if (!backend.connected) return;
    setVoiceLoading(true);
    try {
      const next = !voiceEnabled;
      const res = await setVoiceMode(next);
      setVoiceEnabled(res);
      setVoiceStatus(res ? "Слушает микрофон..." : "Отключен");
      if (!res) setVoiceText(null);
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : "Не удалось изменить режим микрофона");
    } finally {
      setVoiceLoading(false);
    }
  };

  const handleExportDiagnostics = async () => {
    if (!backend.connected) return;
    setDiagLoading(true);
    setDiagError(null);
    setDiagPath(null);
    try {
      const bundlePath = await exportDiagnostics();
      setDiagPath(bundlePath);
    } catch (error) {
      setDiagError(error instanceof Error ? error.message : "Не удалось сформировать отчёт");
    } finally {
      setDiagLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto px-6 py-6">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
        {/* Header & Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-medium text-text">Статус системы</h2>
            <p className="text-xs text-text-muted">
              Мониторинг ресурсов, фонового сервиса и активных таймеров
            </p>
          </div>

          <div className="flex items-center gap-2">
            {!backend.running ? (
              <button
                onClick={handleStart}
                disabled={backendActionLoading}
                className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:brightness-110 disabled:opacity-50"
              >
                <Play size={13} />
                Запустить сервис
              </button>
            ) : (
              <>
                <button
                  onClick={handleRestart}
                  disabled={backendActionLoading}
                  className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-text-muted hover:text-text disabled:opacity-50"
                  title="Перезапустить сервис"
                >
                  <RefreshCw size={13} className={backendActionLoading ? "animate-spin" : ""} />
                  Перезапуск
                </button>
                <button
                  onClick={handleStop}
                  disabled={backendActionLoading}
                  className="flex items-center gap-1.5 rounded-lg border border-danger/40 bg-danger/10 px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger/20 disabled:opacity-50"
                  title="Остановить сервис"
                >
                  <Square size={13} />
                  Остановить
                </button>
              </>
            )}
          </div>
        </div>

        {/* Connection status card */}
        <div className="flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3 text-sm">
          <div className="flex items-center gap-2.5">
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                backend.connected
                  ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]"
                  : backend.running
                  ? "bg-amber-500"
                  : "bg-neutral-500"
              }`}
            />
            <span className="font-medium text-text">
              {backend.connected
                ? "JARVIS активен и подключён"
                : backend.running
                ? "Сервис запускается..."
                : "Сервис остановлен"}
            </span>
            {activeModel && (
              <span className="rounded bg-surface-2 px-2 py-0.5 text-xs text-text-muted">
                {activeProvider?.name ?? "Провайдер"}: {activeModel.model}
              </span>
            )}
          </div>
          {backendError && <p className="text-xs text-danger">{backendError}</p>}
        </div>

        {/* Voice Assistant / Microphone control */}
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div
                className={`flex h-9 w-9 items-center justify-center rounded-lg border ${
                  voiceEnabled
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400 animate-pulse"
                    : "border-border bg-surface-2 text-text-muted"
                }`}
              >
                {voiceEnabled ? <Mic size={18} /> : <MicOff size={18} />}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-text">Голосовой ассистент</span>
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      voiceEnabled
                        ? "border border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                        : "bg-surface-2 text-text-muted"
                    }`}
                  >
                    {voiceEnabled ? voiceStatus : "Выключен"}
                  </span>
                </div>
                <p className="text-xs text-text-muted">
                  {voiceEnabled
                    ? voiceText
                      ? `Последняя фраза: «${voiceText}»`
                      : "Слушает микрофон в фоне, активация по слову «Джарвис»"
                    : "Микрофон отключен. Нажмите кнопку справа для активации голоса"}
                </p>
              </div>
            </div>

            <button
              onClick={toggleVoiceMode}
              disabled={voiceLoading || !backend.connected}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all disabled:opacity-40 ${
                voiceEnabled
                  ? "border border-danger/40 bg-danger/10 text-danger hover:bg-danger/20"
                  : "bg-accent text-white shadow-sm hover:brightness-110"
              }`}
            >
              {voiceEnabled ? (
                <>
                  <MicOff size={13} />
                  Отключить микрофон
                </>
              ) : (
                <>
                  <Mic size={13} />
                  Включить микрофон
                </>
              )}
            </button>
          </div>
        </div>

        {/* Diagnostics report */}
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-surface-2 text-text-muted">
                <Bug size={18} />
              </div>
              <div>
                <span className="text-sm font-semibold text-text">Отчёт об ошибке</span>
                <p className="text-xs text-text-muted">
                  Санитизированный zip: системное инфо, замаскированный конфиг, хвост логов. Без переписок.
                </p>
              </div>
            </div>

            <button
              onClick={handleExportDiagnostics}
              disabled={diagLoading || !backend.connected}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-text-muted hover:text-text disabled:opacity-40"
              title="Сформировать отчёт об ошибке"
            >
              <Bug size={13} className={diagLoading ? "animate-spin" : ""} />
              {diagLoading ? "Формирую..." : "Сформировать отчёт"}
            </button>
          </div>
          {diagPath && (
            <p className="truncate font-mono text-xs text-emerald-400" title={diagPath}>
              Отчёт готов: {diagPath}
            </p>
          )}
          {diagError && <p className="text-xs text-danger">{diagError}</p>}
        </div>

        {/* Stats grid with REAL calculated percentages */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {stats.map((s) => {
            const Icon = s.icon;
            return (
              <div
                key={s.label}
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium tracking-wider text-text-muted">
                    {s.label.toUpperCase()}
                  </span>
                  <Icon size={14} className={s.color ?? "text-text-muted"} />
                </div>
                <span className="truncate text-sm font-semibold text-text">
                  {s.value}
                </span>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={`h-full transition-all duration-500 ${
                      s.color ? "bg-accent" : "bg-accent/80"
                    }`}
                    style={{ width: `${s.percent}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* Active timers */}
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold tracking-wider text-text-muted">
            АКТИВНЫЕ ТАЙМЕРЫ И НАПОМИНАНИЯ
          </h3>
          {!timers || timers.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">
              Нет активных таймеров
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {timers.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <Clock size={16} className="text-accent" />
                    <span className="text-sm font-medium text-text">{t.text}</span>
                  </div>
                  <span className="font-mono text-sm font-semibold text-accent">
                    {t.left}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Warnings */}
        {warnings.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wider text-text-muted">ПРЕДУПРЕЖДЕНИЯ</h3>
            {warnings.map((w) => (
              <div
                key={w.title}
                className="flex items-start gap-2.5 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3"
              >
                <AlertCircle size={16} className="mt-0.5 shrink-0 text-amber-500" />
                <div>
                  <p className="text-sm font-medium text-text">{w.title}</p>
                  <p className="text-xs text-text-muted">{w.detail}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
