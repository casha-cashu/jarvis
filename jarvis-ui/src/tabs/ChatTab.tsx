import { useState, useRef, useEffect } from "react";
import { Plus, Mic, Send, Volume2, RefreshCw, Trash2, X, MessageSquare } from "lucide-react";
import { listen } from "@tauri-apps/api/event";
import {
  sendBackendMessage,
  configureBackend,
  listApiModels,
  switchBackendSession,
  deleteBackendSession,
  type ModelGroup,
} from "../api/backend";
import {
  loadProviders,
  getActiveModel,
  setActiveModel,
  type ProviderEntry,
} from "../api/providers";

interface ProviderModels {
  provider: ProviderEntry;
  groups: ModelGroup[]; // sub-groups by id prefix inside one provider
  error?: string;
}

interface ToolStep {
  id: string;
  name: string;
  input: string;
  output?: string;
}

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  timestamp: string;
  /** Agent trajectory persisted with the assistant message. */
  steps?: ToolStep[];
}

interface Session {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: string;
  messages: Message[];
}

const CHAT_STORAGE_KEY = "jarvis.ui.chats";
const MODELS_CACHE_KEY = "jarvis.ui.models-cache";
const SKIP_CHAT_DELETE_CONFIRM_KEY = "jarvis.ui.skip-chat-delete-confirm";

const mockSessions: Session[] = [
  {
    id: "1",
    title: "Сеть и таймеры",
    lastMessage: "Таймер запущен",
    timestamp: "14:22",
    messages: [
      { id: "m1", role: "user", text: "какой пакет отвечает за сеть", timestamp: "14:20" },
      { id: "m2", role: "assistant", text: "NetworkManager, через команду nmcli", timestamp: "14:20" },
      { id: "m3", role: "user", text: "поставь таймер на 5 минут", timestamp: "14:22" },
      { id: "m4", role: "assistant", text: "Таймер на 5 минут запущен", timestamp: "14:22" },
    ],
  },
  {
    id: "2",
    title: "Погода",
    lastMessage: "Днём +22, без осадков",
    timestamp: "11:05",
    messages: [
      { id: "m5", role: "user", text: "какая погода сегодня", timestamp: "11:05" },
      { id: "m6", role: "assistant", text: "Днём +22, без осадков. Ветер 3 м/с", timestamp: "11:05" },
    ],
  },
  {
    id: "3",
    title: "Установка пакетов",
    lastMessage: "yt-dlp установлен",
    timestamp: "Вчера",
    messages: [
      { id: "m7", role: "user", text: "установи yt-dlp", timestamp: "18:30" },
      { id: "m8", role: "assistant", text: "yt-dlp установлен через pip", timestamp: "18:31" },
    ],
  },
];

function loadSessions(): Session[] {
  try {
    const stored = localStorage.getItem(CHAT_STORAGE_KEY);
    return stored ? JSON.parse(stored) as Session[] : mockSessions;
  } catch {
    return mockSessions;
  }
}

function loadModelsCache(): Record<string, ModelGroup[]> {
  try {
    return JSON.parse(localStorage.getItem(MODELS_CACHE_KEY) ?? "{}") as Record<string, ModelGroup[]>;
  } catch {
    return {};
  }
}

function cacheModels(providerId: string, groups: ModelGroup[]): void {
  const cache = loadModelsCache();
  cache[providerId] = groups;
  localStorage.setItem(MODELS_CACHE_KEY, JSON.stringify(cache));
}

export default function ChatTab() {
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [activeSession, setActiveSession] = useState<string>(() => loadSessions()[0]?.id ?? "");
  const [listening, setListening] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [providers] = useState<ProviderEntry[]>(loadProviders);
  const [active, setActive] = useState(getActiveModel);
  const [providerModels, setProviderModels] = useState<ProviderModels[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Session | null>(null);
  const [skipConfirm, setSkipConfirm] = useState(
    () => localStorage.getItem(SKIP_CHAT_DELETE_CONFIRM_KEY) === "1",
  );
  /** Ordered live trajectory: tool steps and streamed text chunks. */
  const [liveSegments, setLiveSegments] = useState<Array<{ kind: "tool"; step: ToolStep } | { kind: "text"; text: string }>>([]);
  // Ref mirror so the finalize step reads the streamed text synchronously.
  const liveSegmentsRef = useRef<typeof liveSegments>([]);
  useEffect(() => {
    liveSegmentsRef.current = liveSegments;
  }, [liveSegments]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const current = sessions.find((s) => s.id === activeSession) ?? sessions[0];

  useEffect(() => {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [current?.messages.length, activeSession, sending]);

  // Keep backend LLM context aligned with the open chat.
  useEffect(() => {
    if (activeSession) void switchBackendSession(activeSession).catch(() => undefined);
  }, [activeSession]);

  // Stream deltas from the backend into the live bubble.
  useEffect(() => {
    const unlistenDelta = listen<string>("chat-stream", (event) => {
      setLiveSegments((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.kind === "text") {
          return [...prev.slice(0, -1), { kind: "text", text: last.text + event.payload }];
        }
        return [...prev, { kind: "text", text: event.payload }];
      });
    });
    const unlistenTool = listen<string>("chat-tool", (event) => {
      try {
        const parsed = JSON.parse(event.payload) as { name: string; args: Record<string, unknown> };
        const step: ToolStep = {
          id: crypto.randomUUID(),
          name: parsed.name,
          input: String(parsed.args?.cmd ?? JSON.stringify(parsed.args)),
        };
        setLiveSegments((prev) => [...prev, { kind: "tool", step }]);
      } catch {
        /* ignore malformed tool payloads */
      }
    });
    const unlistenResult = listen<string>("chat-tool-result", (event) => {
      try {
        const parsed = JSON.parse(event.payload) as { name: string; output?: string };
        setLiveSegments((prev) => {
          for (let i = prev.length - 1; i >= 0; i--) {
            const seg = prev[i];
            if (seg.kind === "tool" && seg.step.output === undefined && seg.step.name === parsed.name) {
              return [
                ...prev.slice(0, i),
                { kind: "tool" as const, step: { ...seg.step, output: parsed.output ?? "" } },
                ...prev.slice(i + 1),
              ];
            }
          }
          return prev;
        });
      } catch {
        /* ignore malformed payloads */
      }
    });
    return () => {
      void unlistenDelta.then((fn) => fn());
      void unlistenTool.then((fn) => fn());
      void unlistenResult.then((fn) => fn());
    };
  }, []);

  const createSession = () => {
    const id = crypto.randomUUID();
    const session: Session = {
      id,
      title: "Новый чат",
      lastMessage: "Пустой чат",
      timestamp: "Сейчас",
      messages: [],
    };
    setSessions((previous) => [session, ...previous]);
    setActiveSession(id);
    setError(null);
  };

  const requestDeleteSession = (session: Session) => {
    if (skipConfirm) void doDeleteSession(session);
    else setPendingDelete(session);
  };

  const doDeleteSession = async (session: Session) => {
    setPendingDelete(null);
    const remaining = sessions.filter((s) => s.id !== session.id);
    setSessions(remaining);
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(remaining));
    if (activeSession === session.id) setActiveSession(remaining[0]?.id ?? "");
    await deleteBackendSession(session.id).catch(() => undefined);
  };

  const confirmDeleteSession = () => {
    if (!pendingDelete) return;
    if (skipConfirm) localStorage.setItem(SKIP_CHAT_DELETE_CONFIRM_KEY, "1");
    void doDeleteSession(pendingDelete);
  };

  /** Fetch models for every provider (cached), grouped per provider. */
  const fetchModels = async () => {
    if (providers.length === 0) return;
    setLoadingModels(true);
    const results: ProviderModels[] = [];
    for (const provider of providers) {
      const cached = loadModelsCache()[provider.id];
      if (cached && cached.length > 0) {
        results.push({ provider, groups: cached });
        continue;
      }
      try {
        const groups = await listApiModels({
          type: provider.type,
          endpoint: provider.endpoint,
          apiKey: provider.apiKey,
          model: "",
        });
        cacheModels(provider.id, groups);
        results.push({ provider, groups });
      } catch (err) {
        results.push({
          provider,
          groups: [],
          error: err instanceof Error ? err.message : "недоступен",
        });
      }
    }
    setProviderModels(results);
    setLoadingModels(false);
  };

  // Reload when the provider set changes (settings edits, first mount).
  useEffect(() => {
    void fetchModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers.map((p) => p.id + p.endpoint).join(",")]);

  const changeModel = async (compositeKey: string) => {
    const sep = compositeKey.indexOf("::");
    if (sep < 0) return;
    const providerId = compositeKey.slice(0, sep);
    const modelId = compositeKey.slice(sep + 2);
    const provider = providers.find((p) => p.id === providerId);
    if (!provider || !modelId || switching) return;
    setSwitching(true);
    setError(null);
    setActiveModel(providerId, modelId);
    setActive({ providerId, model: modelId });
    try {
      await configureBackend({
        type: provider.type,
        endpoint: provider.endpoint,
        apiKey: provider.apiKey,
        model: modelId,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сменить модель");
    } finally {
      setSwitching(false);
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    setLiveSegments([]);
    setInput("");
    const now = new Date().toLocaleTimeString("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
    });
    const userMessage: Message = { id: crypto.randomUUID(), role: "user", text, timestamp: now };
    setSessions((previous) => previous.map((session) => session.id === activeSession ? {
      ...session,
      title: session.messages.length === 0 ? text.slice(0, 36) : session.title,
      lastMessage: text,
      timestamp: now,
      messages: [...session.messages, userMessage],
    } : session));
    try {
      const response = await sendBackendMessage(text, activeSession);
      const steps = liveSegmentsRef.current
        .filter((s): s is { kind: "tool"; step: ToolStep } => s.kind === "tool")
        .map((s) => s.step);
      const streamedText = liveSegmentsRef.current
        .filter((s): s is { kind: "text"; text: string } => s.kind === "text")
        .map((s) => s.text)
        .join("");
      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: response || streamedText || "Готово.",
        timestamp: now,
        ...(steps.length > 0 ? { steps } : {}),
      };
      setSessions((previous) => previous.map((session) => session.id === activeSession ? {
        ...session,
        lastMessage: assistantMessage.text,
        messages: [...session.messages, assistantMessage],
      } : session));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось связаться с JARVIS");
      setInput(text);
    } finally {
      setLiveSegments([]);
      setSending(false);
    }
  };

  return (
    <div className="relative flex h-full">
      {/* Sessions sidebar */}
      <div className="flex w-64 flex-col border-r border-border bg-surface">
        <div className="flex items-center justify-between px-3 py-2.5">
          <span className="text-xs font-medium tracking-wide text-text-muted">
            СЕССИИ
          </span>
          <button
            onClick={createSession}
            className="rounded p-1 text-text-muted hover:bg-surface-2 hover:text-text"
            title="Новая сессия"
          >
            <Plus size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sessions.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-text-muted">
              <MessageSquare size={22} className="opacity-40" />
              <span className="text-xs">Чатов нет — создайте первый</span>
            </div>
          )}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`group relative flex w-full cursor-pointer flex-col gap-0.5 border-l-2 px-3 py-2.5 text-left transition-colors animate-fade-in ${
                activeSession === s.id
                  ? "border-accent bg-surface-2"
                  : "border-transparent hover:bg-surface-2/50"
              }`}
              onClick={() => setActiveSession(s.id)}
            >
              <div className="flex items-center justify-between gap-1 pr-6">
                <span className="truncate text-xs font-medium text-text">
                  {s.title}
                </span>
                <span className="ml-auto shrink-0 text-[10px] text-text-muted group-hover:opacity-0">
                  {s.timestamp}
                </span>
              </div>
              <span className="truncate text-[11px] text-text-muted">
                {s.lastMessage}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  requestDeleteSession(s);
                }}
                className="absolute right-2 top-2.5 rounded p-1 text-text-muted opacity-0 transition-all hover:bg-danger/15 hover:text-danger focus:opacity-100 group-hover:opacity-100"
                title={`Удалить «${s.title}»`}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex flex-1 flex-col">
        {/* Chat header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text">
              {current?.title ?? "Новый чат"}
            </span>
          </div>
          {listening ? (
            <div className="flex items-center gap-1.5">
              <div className="flex items-center gap-1">
                <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                <span className="text-xs text-accent">Слушает</span>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <Volume2 size={12} className="text-text-muted" />
              {providerModels.length > 0 ? (
                <select
                  value={active ? `${active.providerId}::${active.model}` : ""}
                  onChange={(e) => void changeModel(e.target.value)}
                  disabled={switching}
                  className="max-w-60 rounded bg-transparent text-xs text-text-muted focus:outline-none"
                  title="Модель (сгруппированы по провайдерам)"
                >
                  {!active && <option value="">Выберите модель</option>}
                  {providerModels.map(({ provider, groups, error }) =>
                    error ? (
                      <optgroup key={provider.id} label={`${provider.name} (ошибка)`}>
                        <option value="">{error.slice(0, 80)}</option>
                      </optgroup>
                    ) : (
                      groups.map((sub) => {
                        const label = sub.provider === "other"
                          ? provider.name
                          : `${provider.name} · ${sub.provider}`;
                        return (
                          <optgroup key={`${provider.id}-${sub.provider}`} label={label}>
                            {sub.models.map((id) => (
                              <option
                                key={`${provider.id}::${id}`}
                                value={`${provider.id}::${id}`}
                              >
                                {id}
                              </option>
                            ))}
                          </optgroup>
                        );
                      })
                    ),
                  )}
                </select>
              ) : (
                <span className="text-xs text-text-muted">
                  {active
                    ? (() => {
                        const p = providers.find((x) => x.id === active.providerId);
                        return `${p?.name ?? "?"}/${active.model}`;
                      })()
                    : "Провайдеров нет — добавьте в Настройках"}
                </span>
              )}
              {switching && (
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent/30 border-t-accent" />
              )}
              <button
                onClick={() => void fetchModels()}
                disabled={loadingModels}
                className="rounded p-0.5 text-text-muted transition-colors hover:text-accent disabled:opacity-30"
                title="Обновить список моделей"
              >
                {loadingModels
                  ? <span className="block h-3 w-3 animate-spin rounded-full border-2 border-current/30 border-t-current" />
                  : <RefreshCw size={11} />}
              </button>
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {error && (
            <div className="mx-auto mb-3 max-w-3xl rounded-lg border border-danger/40 bg-surface-2 px-3 py-2 text-xs text-danger" role="alert">
              {error}
            </div>
          )}
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
            {(current?.messages ?? []).length === 0 && !sending && (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <div className="flex h-12 w-12 animate-glow items-center justify-center rounded-2xl bg-accent-bg">
                  <MessageSquare size={20} className="text-accent" />
                </div>
                <p className="text-sm text-text-muted">
                  Напишите что-нибудь — или нажмите микрофон
                </p>
              </div>
            )}
            {(current?.messages ?? []).map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            {sending && liveSegments.map((seg, i) =>
              seg.kind === "tool" ? (
                <ToolStepView key={seg.step.id} step={seg.step} running={i === liveSegments.length - 1 && seg.step.output === undefined} />
              ) : (
                <LiveBubble key={`t-${i}`} text={seg.text} />
              ),
            )}
            {sending && liveSegments.length === 0 && <ThinkingIndicator />}
            {listening && !sending && <ListeningIndicator />}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input bar */}
        <div className="flex items-center gap-2 border-t border-border bg-surface/80 px-4 py-3">
          <button
            onClick={() => setListening(!listening)}
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition-all ${
              listening
                ? "border-accent bg-accent text-white shadow-sm shadow-accent/30"
                : "border-border bg-surface-2 text-text-muted hover:border-accent/50 hover:text-text"
            }`}
            title={listening ? "Остановить" : "Голосовой ввод"}
          >
            <Mic size={16} />
          </button>
          <div className="flex flex-1 items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-1.5 transition-colors focus-within:border-accent/60 focus-within:ring-2 focus-within:ring-accent/15">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="Написать сообщение..."
              className="flex-1 bg-transparent text-sm text-text placeholder:text-text-muted focus:outline-none"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent text-white transition-all hover:brightness-110 disabled:bg-transparent disabled:text-text-muted disabled:opacity-50"
              title="Отправить"
            >
              {sending ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" /> : <Send size={14} />}
            </button>
          </div>
        </div>
      </div>

      {/* Confirm chat deletion */}
      {pendingDelete && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
          <div className="flex w-full max-w-sm flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-2xl animate-pop-in">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-base font-medium text-text">Удалить чат?</h3>
              <button
                onClick={() => setPendingDelete(null)}
                className="rounded p-0.5 text-text-muted hover:text-text"
              >
                <X size={16} />
              </button>
            </div>
            <p className="text-sm text-text-muted">
              «{pendingDelete.title}» будет удалён вместе с памятью модели об
              этом диалоге. Действие необратимо.
            </p>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-text-muted">
              <input
                type="checkbox"
                checked={skipConfirm}
                onChange={(e) => setSkipConfirm(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--color-accent)]"
              />
              Больше не спрашивать
            </label>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setPendingDelete(null)}
                className="rounded-lg px-4 py-2 text-sm text-text-muted hover:bg-surface-2"
              >
                Отмена
              </button>
              <button
                onClick={confirmDeleteSession}
                className="rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white hover:brightness-110"
              >
                Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ListeningIndicator() {
  return (
    <div className="flex animate-fade-in justify-start" role="status" aria-live="polite">
      <div className="flex items-center gap-2 rounded-lg bg-accent-bg px-3 py-2 text-sm text-accent">
        <span>Слушаю</span>
        <Dots />
      </div>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="flex animate-fade-in justify-start" role="status" aria-live="polite">
      <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-4 py-2.5">
        <span className="text-xs text-text-muted">Думаю</span>
        <Dots muted />
      </div>
    </div>
  );
}

function LiveBubble({ text }: { text: string }) {
  return (
    <div className="flex animate-fade-in justify-start" role="status" aria-live="polite">
      <div className="max-w-[80%] rounded-lg bg-surface-2 px-3 py-2 text-sm text-text">
        {text}
        <span className="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-pulse bg-accent" />
      </div>
    </div>
  );
}

function ToolStepView({ step, running }: { step: ToolStep; running?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex animate-fade-in justify-start">
      <div className="w-full max-w-[85%] overflow-hidden rounded-lg border border-accent/25 bg-surface">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-left font-mono text-xs transition-colors hover:bg-surface-2"
          title={open ? "Скрыть вывод" : "Показать вывод"}
        >
          <span className="shrink-0 rounded bg-accent px-1 py-0.5 text-[10px] font-medium uppercase text-white">
            {step.name}
          </span>
          <span className="min-w-0 flex-1 truncate text-text-muted">{step.input}</span>
          {running && <Dots muted />}
          <span className={`shrink-0 text-text-muted transition-transform ${open ? "rotate-90" : ""}`}>›</span>
        </button>
        {open && (
          <pre className="max-h-44 overflow-y-auto border-t border-border bg-bg px-3 py-2 whitespace-pre-wrap break-words font-mono text-[11px] text-text-muted">
            {step.output || (running ? "выполняется…" : "(пусто)")}
          </pre>
        )}
      </div>
    </div>
  );
}

function Dots({ muted }: { muted?: boolean }) {
  const color = muted ? "bg-text-muted" : "bg-current";
  return (
    <span className="flex gap-1" aria-hidden="true">
      <span className={`h-1.5 w-1.5 animate-bounce rounded-full ${color} [animation-delay:-0.3s]`} />
      <span className={`h-1.5 w-1.5 animate-bounce rounded-full ${color} [animation-delay:-0.15s]`} />
      <span className={`h-1.5 w-1.5 animate-bounce rounded-full ${color}`} />
    </span>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex animate-fade-in ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`flex max-w-[80%] flex-col gap-1 ${
          isUser ? "items-end" : "items-start"
        }`}
      >
        {message.steps?.map((step) => (
          <div key={step.id} className="w-full">
            <ToolStepView step={step} />
          </div>
        ))}
        <div
          className={`rounded-lg px-3 py-2 text-sm transition-colors ${
            isUser
              ? "bg-accent-bg text-text"
              : "bg-surface-2 text-text"
          }`}
        >
          {message.text}
        </div>
        <span className="px-1 text-[11px] text-text-muted">
          {message.timestamp}
        </span>
      </div>
    </div>
  );
}
