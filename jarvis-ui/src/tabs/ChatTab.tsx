import { useState, useRef, useEffect, useMemo } from "react";
import {
  Plus,
  Mic,
  Send,
  Volume2,
  RefreshCw,
  Trash2,
  X,
  MessageSquare,
  Paperclip,
  FileText,
  Image,
  Brain,
  Thermometer,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { listen } from "@tauri-apps/api/event";
import {
  sendBackendMessage,
  getLastResponseThinking,
  configureBackend,
  listApiModels,
  switchBackendSession,
  deleteBackendSession,
  getVoiceMode,
  setVoiceMode,
  getBackendConfig,
  setBackendConfigValue,
  type ModelGroup,
} from "../api/backend";
import {
  loadProviders,
  getActiveModel,
  setActiveModel,
  isLocalProvider,
  loadModelsCache,
  cacheModels,
  type ProviderEntry,
} from "../api/providers";

export interface ProviderModels {
  provider: ProviderEntry;
  groups: ModelGroup[]; // sub-groups by id prefix inside one provider
  error?: string;
}

export interface ToolStep {
  id: string;
  name: string;
  input: string;
  output?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  timestamp: string;
  /** Agent trajectory persisted with the assistant message. */
  steps?: ToolStep[];
  /** Reasoning trace persisted with the assistant message. */
  thinking?: string;
  /** Elapsed seconds spent thinking. */
  thinkingDuration?: number;
  /** Attached images (base64 data URLs) displayed on user messages. */
  images?: string[];
}

export interface AttachmentItem {
  id: string;
  file: File;
  name: string;
  size: number;
  isImage: boolean;
  previewUrl?: string;
}

export interface Session {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: string;
  messages: Message[];
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Не удалось прочитать файл"));
    reader.readAsDataURL(file);
  });
}

function formatFileMarkdown(name: string, content: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const langMap: Record<string, string> = {
    py: "python",
    rs: "rust",
    js: "javascript",
    ts: "typescript",
    tsx: "tsx",
    jsx: "jsx",
    json: "json",
    md: "markdown",
    txt: "text",
    log: "text",
    sh: "bash",
    bash: "bash",
    toml: "toml",
    yaml: "yaml",
    yml: "yaml",
    html: "html",
    css: "css",
    sql: "sql",
  };
  const lang = langMap[ext] ?? ext;
  return `### Файл: ${name}\n\`\`\`${lang}\n${content}\n\`\`\``;
}

interface ThinkingBlockProps {
  thinking: string;
  isLive?: boolean;
  duration?: number;
}

export function ThinkingBlock({ thinking, isLive = false, duration = 0 }: ThinkingBlockProps) {
  const [open, setOpen] = useState(isLive);
  const scrollRef = useRef<HTMLPreElement>(null);
  const [elapsed, setElapsed] = useState(duration);
  const startTimeRef = useRef<number>(Date.now() - duration * 1000);

  useEffect(() => {
    if (!isLive) {
      setElapsed(duration);
      return;
    }
    setOpen(true);
    startTimeRef.current = Date.now() - (duration > 0 ? duration * 1000 : 0);
    const interval = setInterval(() => {
      setElapsed(Math.max(1, Math.floor((Date.now() - startTimeRef.current) / 1000)));
    }, 500);
    return () => clearInterval(interval);
  }, [isLive, duration]);

  useEffect(() => {
    if (isLive && open && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [thinking, isLive, open]);

  const displaySeconds = isLive ? elapsed : (duration > 0 ? duration : (elapsed > 0 ? elapsed : 1));
  const timerLabel = `${displaySeconds} сек`;

  return (
    <div className="flex w-full animate-fade-in justify-start" data-testid="thinking-block">
      <div className="w-full overflow-hidden rounded-lg border border-accent/20 bg-surface shadow-xs">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-surface-2 ${
            isLive ? "bg-accent/5" : ""
          }`}
          title={open ? "Скрыть размышления" : "Показать размышления"}
        >
          <div className="flex items-center gap-2">
            {isLive ? (
              <span className="flex items-center gap-1.5 font-medium text-accent">
                <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
                <span>Думает ({timerLabel})...</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5 font-medium text-text-muted">
                <Brain size={14} className="text-accent/80 shrink-0" />
                <span>Размышления ({timerLabel})</span>
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {isLive && <Dots muted />}
            {open ? (
              <ChevronDown size={14} className="shrink-0 text-text-muted transition-transform" />
            ) : (
              <ChevronRight size={14} className="shrink-0 text-text-muted transition-transform" />
            )}
          </div>
        </button>

        {open && (
          <pre
            ref={scrollRef}
            className="max-h-60 overflow-y-auto border-t border-border bg-bg/60 px-3 py-2.5 font-mono text-[11px] leading-relaxed text-text-muted whitespace-pre-wrap break-words"
          >
            {thinking || (isLive ? "формирование мыслей..." : "(нет записей)")}
          </pre>
        )}
      </div>
    </div>
  );
}

const CHAT_STORAGE_KEY = "jarvis.ui.chats";
const SKIP_CHAT_DELETE_CONFIRM_KEY = "jarvis.ui.skip-chat-delete-confirm";
const REASONING_EFFORT_KEY = "jarvis.ui.reasoningEffort";

function loadSessions(): Session[] {
  try {
    const stored = localStorage.getItem(CHAT_STORAGE_KEY);
    return stored ? JSON.parse(stored) as Session[] : [];
  } catch {
    return [];
  }
}

export default function ChatTab() {
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [activeSession, setActiveSession] = useState<string>(() => loadSessions()[0]?.id ?? "");
  const [listening, setListening] = useState(false);
  const [partialVoiceText, setPartialVoiceText] = useState<string | null>(null);
  const [voiceStatus, setVoiceStatus] = useState<string>("Отключен");
  const [audioLevel, setAudioLevel] = useState<number>(0);
  const [voiceLoading, setVoiceLoading] = useState<boolean>(false);
  const lastRecognizedRef = useRef<string | null>(null);
  const activeSessionRef = useRef(activeSession);
  useEffect(() => {
    activeSessionRef.current = activeSession;
    lastRecognizedRef.current = null;
  }, [activeSession]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderEntry[]>(loadProviders);
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

  // Live reasoning state
  const [liveThinking, setLiveThinking] = useState<string>("");
  const liveThinkingRef = useRef<string>("");
  const [isThinkingLive, setIsThinkingLive] = useState<boolean>(false);
  const thinkingStartTimeRef = useRef<number | null>(null);
  const [thinkingDuration, setThinkingDuration] = useState<number>(0);
  const thinkingDurationRef = useRef<number>(0);

  // Reasoning effort control
  const [reasoningEffort, setReasoningEffort] = useState<string>(() => {
    return localStorage.getItem(REASONING_EFFORT_KEY) || "medium";
  });

  const handleReasoningChange = (newEffort: string) => {
    setReasoningEffort(newEffort);
    try {
      localStorage.setItem(REASONING_EFFORT_KEY, newEffort);
    } catch {
      // Ignore storage errors
    }
  };

  // Temperature control (synchronized with settings and backend)
  const [chatTemperature, setChatTemperature] = useState<number>(() => {
    try {
      const saved = localStorage.getItem("jarvis.ui.temperature");
      if (saved !== null) {
        const parsed = parseFloat(saved);
        if (!isNaN(parsed)) return parsed;
      }
    } catch {}
    return 0.7;
  });

  useEffect(() => {
    getBackendConfig()
      .then((cfg) => {
        if (cfg.llm?.temperature !== undefined && cfg.llm.temperature !== null) {
          const num = Number(cfg.llm.temperature);
          if (!isNaN(num)) setChatTemperature(num);
        }
      })
      .catch(() => {});
  }, []);

  const handleTemperatureChange = (val: number) => {
    const clamped = Math.max(0.0, Math.min(2.0, Number(val.toFixed(2))));
    setChatTemperature(clamped);
    try {
      localStorage.setItem("jarvis.ui.temperature", String(clamped));
      void setBackendConfigValue("llm", "temperature", clamped);
    } catch {}
  };

  const activeCapability = useMemo(() => {
    if (!active) return undefined;
    for (const pm of providerModels) {
      if (pm.provider.id === active.providerId) {
        for (const group of pm.groups) {
          if (group.details && group.details[active.model]) {
            return group.details[active.model];
          }
        }
      }
    }
    return undefined;
  }, [active, providerModels]);

  const isReasoningSupported = activeCapability?.reasoning ?? (
    active?.model
      ? /o1|o3|o4|deepseek-r1|-r1|\/r1|r1-|r1:|qwq|reasoner|reasoning|thinking|thought|gemini-2\.5|gemini-3|gemini-2\.0-flash-thinking|claude-3-7|claude-3\.7|grok-3/i.test(active.model)
      : true
  );

  const availableEfforts = useMemo(() => {
    if (activeCapability) {
      if (activeCapability.reasoning && Array.isArray(activeCapability.reasoningEfforts) && activeCapability.reasoningEfforts.length > 0) {
        return activeCapability.reasoningEfforts;
      }
      if (!activeCapability.reasoning) {
        return [];
      }
    }
    if (!isReasoningSupported) {
      return [];
    }
    if (active?.model && /deepseek-r1|-r1|\/r1|r1-|r1:|qwq/i.test(active.model) && !/claude|o1|o3/i.test(active.model)) {
      return ["off", "on"];
    }
    if (active?.model && /claude-3-7|claude-3\.7/i.test(active.model)) {
      return ["off", "low", "medium", "high", "max"];
    }
    return ["off", "low", "medium", "high", "max"];
  }, [activeCapability, isReasoningSupported, active?.model]);

  useEffect(() => {
    if (availableEfforts.length === 0) {
      if (reasoningEffort !== "off") {
        setReasoningEffort("off");
        try {
          localStorage.setItem(REASONING_EFFORT_KEY, "off");
        } catch {}
      }
    } else if (reasoningEffort !== "off" && !availableEfforts.includes(reasoningEffort)) {
      const fallback = availableEfforts.find((e) => e !== "off") || "off";
      setReasoningEffort(fallback);
      try {
        localStorage.setItem(REASONING_EFFORT_KEY, fallback);
      } catch {}
    }
  }, [availableEfforts, reasoningEffort]);

  const isMultimodalSupported = activeCapability?.multimodal ?? (
    active?.model
      ? /gpt-4o|gpt-4-turbo|vision|-vl|\/vl|vl-|vl:|llava|gemini|claude-3|claude-sonnet|claude-opus|claude-haiku|pixtral|minicpm-v|qwen2-vl|qwen2\.5-vl|omni/i.test(active.model)
      : true
  );

  // Attachments state
  const [attachments, setAttachments] = useState<AttachmentItem[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);

  const addFiles = (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    const newAttachments: AttachmentItem[] = files.map((file) => {
      const isImage = file.type.startsWith("image/") || /\.(png|jpe?g|webp|gif|svg|bmp)$/i.test(file.name);
      return {
        id: crypto.randomUUID(),
        file,
        name: file.name,
        size: file.size,
        isImage,
        previewUrl: isImage ? URL.createObjectURL(file) : undefined,
      };
    });

    setAttachments((prev) => [...prev, ...newAttachments]);
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const item = prev.find((a) => a.id === id);
      if (item?.previewUrl) {
        URL.revokeObjectURL(item.previewUrl);
      }
      return prev.filter((a) => a.id !== id);
    });
  };

  const clearAttachments = () => {
    setAttachments((prev) => {
      prev.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
      return [];
    });
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setIsDragging(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  };

  const current = sessions.find((s) => s.id === activeSession) ?? sessions[0];

  useEffect(() => {
    try {
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(sessions));
    } catch (e) {
      console.warn("Не удалось сохранить историю чатов в localStorage:", e);
    }
  }, [sessions]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [current?.messages.length, activeSession, sending]);

  // Keep backend LLM context aligned with the open chat.
  useEffect(() => {
    if (activeSession) void switchBackendSession(activeSession).catch(() => undefined);
  }, [activeSession]);

  // Listen for history updates from other tabs (HistoryTab)
  useEffect(() => {
    const onHistoryUpdated = (e: Event) => {
      const custom = e as CustomEvent<{ source?: string }>;
      if (custom.detail?.source === "chat") return;
      const reloaded = loadSessions();
      setSessions(reloaded);
      setActiveSession((currentActive) => {
        if (!reloaded.some((s) => s.id === currentActive)) {
          return reloaded[0]?.id ?? "";
        }
        return currentActive;
      });
    };
    window.addEventListener("jarvis:history-updated", onHistoryUpdated);
    return () => window.removeEventListener("jarvis:history-updated", onHistoryUpdated);
  }, []);

  // Sync providers, active model and models cache when changed from Settings
  useEffect(() => {
    const onProvidersChanged = () => {
      const nextProviders = loadProviders();
      setProviders(nextProviders);
      setActive(getActiveModel());
      const cache = loadModelsCache();
      const updatedModels: ProviderModels[] = [];
      for (const p of nextProviders) {
        const c = cache[p.id];
        if (c && c.length > 0) {
          updatedModels.push({ provider: p, groups: c });
        }
      }
      if (updatedModels.length > 0) {
        setProviderModels(updatedModels);
      }
    };
    window.addEventListener("jarvis:providers-changed", onProvidersChanged);
    return () => window.removeEventListener("jarvis:providers-changed", onProvidersChanged);
  }, []);

  // Re-configure backend and switch session after backend restart
  useEffect(() => {
    const onBackendRestarted = async () => {
      const currentActive = getActiveModel();
      const currentProviders = loadProviders();
      if (currentActive) {
        const provider = currentProviders.find((p) => p.id === currentActive.providerId);
        if (provider) {
          await configureBackend({
            type: provider.type,
            endpoint: provider.endpoint,
            apiKey: provider.apiKey,
            model: currentActive.model,
            agentEnabled: localStorage.getItem("jarvis.ui.agentEnabled") !== "0",
            approvalMode: localStorage.getItem("jarvis.ui.approvalMode") ?? "auto",
          }).catch(() => undefined);
        }
      }
      if (activeSession) {
        await switchBackendSession(activeSession).catch(() => undefined);
      }
    };
    window.addEventListener("jarvis:backend-restarted", onBackendRestarted);
    return () => window.removeEventListener("jarvis:backend-restarted", onBackendRestarted);
  }, [activeSession]);

  // Stream deltas from the backend into the live bubble.
  useEffect(() => {
    const unlistenThinking = listen<string>("chat-thinking", (event) => {
      if (thinkingStartTimeRef.current === null) {
        thinkingStartTimeRef.current = Date.now();
      }
      setIsThinkingLive(true);
      liveThinkingRef.current += event.payload;
      setLiveThinking((prev) => prev + event.payload);
    });

    const unlistenDelta = listen<string>("chat-stream", (event) => {
      if (thinkingStartTimeRef.current !== null && thinkingDurationRef.current === 0) {
        const sec = Math.max(1, Math.round((Date.now() - thinkingStartTimeRef.current) / 1000));
        thinkingDurationRef.current = sec;
        setThinkingDuration(sec);
        setIsThinkingLive(false);
      }
      setLiveSegments((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.kind === "text") {
          return [...prev.slice(0, -1), { kind: "text", text: last.text + event.payload }];
        }
        return [...prev, { kind: "text", text: event.payload }];
      });
    });
    const unlistenTool = listen<string>("chat-tool", (event) => {
      if (thinkingStartTimeRef.current !== null && thinkingDurationRef.current === 0) {
        const sec = Math.max(1, Math.round((Date.now() - thinkingStartTimeRef.current) / 1000));
        thinkingDurationRef.current = sec;
        setThinkingDuration(sec);
        setIsThinkingLive(false);
      }
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
    const unlistenVoice = listen<
      string | { status: string; text?: string; query?: string; response?: string; session?: string; level?: number }
    >("voice-event", (event) => {
      let data: {
        status: string;
        text?: string;
        query?: string;
        response?: string;
        session?: string;
        level?: number;
      };
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
        setListening(true);
        setVoiceStatus("Ожидает «Джарвис»");
        setPartialVoiceText(null);
      } else if (data.status === "stopped") {
        setListening(false);
        setVoiceStatus("Отключен");
        setPartialVoiceText(null);
        setAudioLevel(0);
        lastRecognizedRef.current = null;
      } else if (data.status === "partial") {
        setVoiceStatus("Слышит речь...");
        setPartialVoiceText(data.text || null);
      } else if (data.status === "wake_word_required") {
        setVoiceStatus("Требуется «Джарвис»");
        setPartialVoiceText(null);
        const heard = data.text ? `«${data.text}»` : "";
        setError(`Услышано ${heard}: скажите «Джарвис ...» перед запросом или включите постоянный режим`);
      } else if (data.status === "audio_level") {
        const lvl = typeof data.level === "number" ? data.level : 0;
        if (!Number.isNaN(lvl)) {
          setAudioLevel(Math.max(0, Math.min(1, lvl)));
        }
      } else if (data.status === "status") {
        if (data.text) setVoiceStatus(data.text);
      } else if (data.status === "recognized") {
        setVoiceStatus("Обработка...");
        setPartialVoiceText(null);
        const queryText = (data.query || data.text || "").trim();
        if (queryText) {
          if (lastRecognizedRef.current === queryText) return;
          lastRecognizedRef.current = queryText;

          const now = new Date().toLocaleTimeString("ru-RU", {
            hour: "2-digit",
            minute: "2-digit",
          });
          const userMessage: Message = {
            id: crypto.randomUUID(),
            role: "user",
            text: queryText,
            timestamp: now,
          };
          setSessions((prev) => {
            const targetId = activeSessionRef.current || prev[0]?.id;
            if (!targetId) {
              const newId = crypto.randomUUID();
              const newSession: Session = {
                id: newId,
                title: queryText.slice(0, 36) || "Голосовой чат",
                lastMessage: queryText,
                timestamp: now,
                messages: [userMessage],
              };
              setActiveSession(newId);
              return [newSession];
            }
            return prev.map((s) => {
              if (s.id !== targetId) return s;
              const last = s.messages[s.messages.length - 1];
              if (last && last.role === "user" && last.text === queryText) {
                return s;
              }
              return {
                ...s,
                title: s.messages.length === 0 ? queryText.slice(0, 36) : s.title,
                lastMessage: queryText,
                timestamp: now,
                messages: [...s.messages, userMessage],
              };
            });
          });
          setSending(true);
          setLiveSegments([]);
        }
      } else if (data.status === "processing") {
        setVoiceStatus("Обработка...");
        setPartialVoiceText(null);
        setSending(true);
      } else if (data.status === "speaking") {
        setVoiceStatus("Озвучивает ответ...");
        setPartialVoiceText(null);
      } else if (data.status === "finished") {
        setVoiceStatus("Ожидает «Джарвис»");
        setPartialVoiceText(null);
        lastRecognizedRef.current = null;
        if (data.response && data.response.trim()) {
          const now = new Date().toLocaleTimeString("ru-RU", {
            hour: "2-digit",
            minute: "2-digit",
          });
          const steps = liveSegmentsRef.current
            .filter((s): s is { kind: "tool"; step: ToolStep } => s.kind === "tool")
            .map((s) => s.step);
          const finalThinking =
            liveThinkingRef.current.trim() ||
            (typeof (data as Record<string, unknown>).thinking === "string"
              ? ((data as Record<string, unknown>).thinking as string).trim()
              : "");
          let finalDuration = thinkingDurationRef.current;
          if (thinkingStartTimeRef.current !== null && finalDuration === 0) {
            finalDuration = Math.max(1, Math.round((Date.now() - thinkingStartTimeRef.current) / 1000));
          }
          const assistantMessage: Message = {
            id: crypto.randomUUID(),
            role: "assistant",
            text: data.response.trim(),
            timestamp: now,
            ...(steps.length > 0 ? { steps } : {}),
            ...(finalThinking ? { thinking: finalThinking, thinkingDuration: finalDuration || 1 } : {}),
          };
          setLiveThinking("");
          liveThinkingRef.current = "";
          setIsThinkingLive(false);
          thinkingStartTimeRef.current = null;
          setThinkingDuration(0);
          thinkingDurationRef.current = 0;
          setSessions((prev) => {
            const targetId = activeSessionRef.current || prev[0]?.id;
            if (!targetId) {
              const newId = crypto.randomUUID();
              const newSession: Session = {
                id: newId,
                title: "Голосовой чат",
                lastMessage: assistantMessage.text,
                timestamp: now,
                messages: [assistantMessage],
              };
              setActiveSession(newId);
              return [newSession];
            }
            return prev.map((s) => {
              if (s.id !== targetId) return s;
              const last = s.messages[s.messages.length - 1];
              if (last && last.role === "assistant" && last.text === assistantMessage.text) {
                return s;
              }
              return {
                ...s,
                lastMessage: assistantMessage.text,
                messages: [...s.messages, assistantMessage],
              };
            });
          });
          setLiveSegments([]);
          setSending(false);
          if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
            window.dispatchEvent(new CustomEvent("jarvis:history-updated", { detail: { source: "chat" } }));
          }
        }
      }
    });

    getVoiceMode().then((enabled) => {
      setListening(enabled);
      setVoiceStatus(enabled ? "Ожидает «Джарвис»" : "Отключен");
    }).catch(() => undefined);

    const onVoiceModeChange = (e: Event) => {
      const customEvent = e as CustomEvent<boolean>;
      setListening(customEvent.detail);
      setVoiceStatus(customEvent.detail ? "Ожидает «Джарвис»" : "Отключен");
      if (!customEvent.detail) {
        setAudioLevel(0);
        lastRecognizedRef.current = null;
      }
    };
    window.addEventListener("jarvis:voice-mode-change", onVoiceModeChange);

    return () => {
      void unlistenThinking.then((fn) => fn());
      void unlistenDelta.then((fn) => fn());
      void unlistenTool.then((fn) => fn());
      void unlistenResult.then((fn) => fn());
      void unlistenVoice.then((fn) => fn());
      window.removeEventListener("jarvis:voice-mode-change", onVoiceModeChange);
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
    if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      window.dispatchEvent(new CustomEvent("jarvis:history-updated", { detail: { source: "chat" } }));
    }
    await deleteBackendSession(session.id).catch(() => undefined);
  };

  const confirmDeleteSession = () => {
    if (!pendingDelete) return;
    if (skipConfirm) localStorage.setItem(SKIP_CHAT_DELETE_CONFIRM_KEY, "1");
    void doDeleteSession(pendingDelete);
  };

  /** Fetch models for every provider (cached) — only on demand, not on every render. */
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
      // Skip network if key missing (except local providers)
      if (!isLocalProvider(provider) && !provider.apiKey) {
        results.push({ provider, groups: [], error: "нет ключа" });
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

  // Load cached only on mount — network fetch only on Save/Refresh button
  useEffect(() => {
    const cached: ProviderModels[] = [];
    for (const p of providers) {
      const c = loadModelsCache()[p.id];
      if (c) cached.push({ provider: p, groups: c });
    }
    if (cached.length > 0) setProviderModels(cached);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        reasoningEffort: reasoningEffort !== "off" ? reasoningEffort : undefined,
        // Флаги агента хранятся в localStorage (Настройки → LLM). Без них
        // serde-дефолты Rust (true/auto) тихо включали bash-агент при
        // каждой смене модели — даже если пользователь его выключил.
        agentEnabled: localStorage.getItem("jarvis.ui.agentEnabled") !== "0",
        approvalMode: localStorage.getItem("jarvis.ui.approvalMode") ?? "auto",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сменить модель");
    } finally {
      setSwitching(false);
    }
  };

  const handleSend = async () => {
    const textInput = input.trim();
    if ((!textInput && attachments.length === 0) || sending) return;

    setSending(true);
    setError(null);
    setLiveSegments([]);
    setLiveThinking("");
    liveThinkingRef.current = "";
    setIsThinkingLive(false);
    thinkingStartTimeRef.current = null;
    setThinkingDuration(0);
    thinkingDurationRef.current = 0;
    setInput("");

    const currentAttachments = [...attachments];
    clearAttachments();

    const imageAttachments = currentAttachments.filter((a) => a.isImage);
    const fileAttachments = currentAttachments.filter((a) => !a.isImage);

    let base64Images: string[] = [];
    if (imageAttachments.length > 0) {
      try {
        base64Images = await Promise.all(imageAttachments.map((a) => fileToBase64(a.file)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось прочитать изображение");
        setSending(false);
        return;
      }
    }

    let fileMarkdownBlocks: string[] = [];
    if (fileAttachments.length > 0) {
      try {
        fileMarkdownBlocks = await Promise.all(
          fileAttachments.map(async (a) => {
            const content = await a.file.text();
            return formatFileMarkdown(a.name, content);
          }),
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось прочитать файл");
        setSending(false);
        return;
      }
    }

    const fullMessageText = [textInput, ...fileMarkdownBlocks].filter(Boolean).join("\n\n");
    const displayUserText = fullMessageText || (base64Images.length > 0 ? "Изображение" : "");

    const now = new Date().toLocaleTimeString("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
    });

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      text: displayUserText,
      timestamp: now,
      ...(base64Images.length > 0 ? { images: base64Images } : {}),
    };

    const targetSession = sessions.find((s) => s.id === activeSession) ?? sessions[0];
    let sessionKey: string;
    const sessionTitle = textInput || (currentAttachments[0]?.name ?? "Новый чат");

    if (!targetSession) {
      sessionKey = crypto.randomUUID();
      const newSession: Session = {
        id: sessionKey,
        title: sessionTitle.slice(0, 36) || "Новый чат",
        lastMessage: displayUserText,
        timestamp: now,
        messages: [userMessage],
      };
      setSessions([newSession]);
      setActiveSession(sessionKey);
    } else {
      sessionKey = targetSession.id;
      setSessions((previous) =>
        previous.map((session) =>
          session.id === sessionKey
            ? {
                ...session,
                title: session.messages.length === 0 ? sessionTitle.slice(0, 36) : session.title,
                lastMessage: displayUserText,
                timestamp: now,
                messages: [...session.messages, userMessage],
              }
            : session,
        ),
      );
    }

    try {
      const response = await sendBackendMessage(
        fullMessageText,
        sessionKey,
        base64Images.length > 0 ? base64Images : undefined,
        reasoningEffort,
      );

      let finalDuration = thinkingDurationRef.current;
      if (thinkingStartTimeRef.current !== null && finalDuration === 0) {
        finalDuration = Math.max(1, Math.round((Date.now() - thinkingStartTimeRef.current) / 1000));
        thinkingDurationRef.current = finalDuration;
      }
      const responseThinking = getLastResponseThinking();
      const finalThinking = liveThinkingRef.current.trim() || responseThinking?.trim() || "";
      setIsThinkingLive(false);

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
        ...(finalThinking ? { thinking: finalThinking, thinkingDuration: finalDuration || 1 } : {}),
      };
      setSessions((previous) =>
        previous.map((session) =>
          session.id === sessionKey
            ? {
                ...session,
                lastMessage: assistantMessage.text,
                messages: [...session.messages, assistantMessage],
              }
            : session,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось связаться с JARVIS");
      setInput(textInput);
    } finally {
      setLiveSegments([]);
      setLiveThinking("");
      liveThinkingRef.current = "";
      setIsThinkingLive(false);
      thinkingStartTimeRef.current = null;
      setThinkingDuration(0);
      thinkingDurationRef.current = 0;
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

      {/* Chat area with drag & drop support */}
      <div
        className="relative flex flex-1 flex-col overflow-hidden"
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Visual dropzone indicator overlay */}
        {isDragging && (
          <div
            className="pointer-events-none absolute inset-0 z-40 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-accent bg-surface/90 backdrop-blur-xs animate-fade-in"
            aria-label="Dropzone"
            data-testid="dropzone-overlay"
          >
            <div className="flex flex-col items-center gap-2 p-6 text-center text-accent">
              <Paperclip size={36} className="animate-bounce" />
              <span className="text-base font-medium">Перетащите файлы сюда</span>
              <span className="text-xs text-text-muted">Изображения, документы и файлы с кодом</span>
            </div>
          </div>
        )}

        {/* Chat header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text">
              {current?.title ?? "Новый чат"}
            </span>
            {listening && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-accent/15 px-2.5 py-0.5 text-[11px] font-medium text-accent">
                <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                {voiceStatus}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {listening && (
              <div className="flex items-center gap-1.5 rounded-md bg-surface-2 px-2 py-1 border border-border text-[11px]" title={`Уровень микрофона: ${Math.round(audioLevel * 100)}%`}>
                <Mic size={12} className="text-accent shrink-0 animate-pulse" />
                <div className="h-1.5 w-14 overflow-hidden rounded bg-surface border border-border/50">
                  <div
                    className="h-full bg-accent transition-all duration-75"
                    style={{ width: `${Math.max(audioLevel > 0.02 ? 8 : 0, Math.round(audioLevel * 100))}%` }}
                  />
                </div>
              </div>
            )}
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
                            {(sub.models ?? []).map((id) => {
                              const detail = sub.details?.[id];
                              const ctxNum = detail?.contextLength ?? (detail as any)?.context_length;
                              const ctxStr = ctxNum
                                ? ctxNum >= 1000000
                                  ? ` (${(ctxNum / 1000000).toFixed(1)}M)`
                                  : ` (${Math.round(ctxNum / 1000)}k)`
                                : "";
                              return (
                                <option
                                  key={`${provider.id}::${id}`}
                                  value={`${provider.id}::${id}`}
                                  title={detail?.description || undefined}
                                >
                                  {id}{ctxStr}
                                </option>
                              );
                            })}
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

            {/* Reasoning effort selector */}
            <div
              className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs transition-colors ${
                availableEfforts.length === 0
                  ? "border-border/30 bg-surface-2/40 text-text-muted/50 cursor-not-allowed opacity-60"
                  : reasoningEffort !== "off"
                  ? "border-accent/40 bg-accent/10 text-accent font-medium"
                  : "border-border bg-surface-2 text-text-muted"
              }`}
              title={
                availableEfforts.length === 0
                  ? "Модель не поддерживает размышления (Reasoning)"
                  : `Глубина рассуждений (${reasoningEffort})`
              }
            >
              <Brain
                size={13}
                className={
                  availableEfforts.length === 0
                    ? "text-text-muted/40"
                    : reasoningEffort !== "off"
                    ? "text-accent"
                    : "text-text-muted"
                }
              />
              <select
                data-testid="reasoning-effort-select"
                aria-label="Глубина рассуждений"
                value={availableEfforts.length === 0 ? "off" : reasoningEffort}
                onChange={(e) => handleReasoningChange(e.target.value)}
                disabled={sending || availableEfforts.length === 0}
                className={`bg-transparent text-xs text-inherit focus:outline-none ${
                  availableEfforts.length === 0 ? "cursor-not-allowed" : "cursor-pointer"
                }`}
              >
                {availableEfforts.length === 0 ? (
                  <option value="off" className="bg-surface text-text-muted">
                    Мысли: Выкл
                  </option>
                ) : (
                  availableEfforts.map((effort) => {
                    const label =
                      effort === "off"
                        ? "Мысли: Выкл"
                        : effort === "on"
                        ? "Мысли: Вкл"
                        : `Мысли: ${effort.charAt(0).toUpperCase() + effort.slice(1)}`;
                    return (
                      <option key={effort} value={effort} className="bg-surface text-text">
                        {label}
                      </option>
                    );
                  })
                )}
              </select>
            </div>

            {/* Temperature selector */}
            <div
              className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2 py-1 text-xs text-text-muted transition-colors hover:border-accent/40"
              title="Температура генерации (0.0 — точный/код, 1.0+ — креативный)"
            >
              <Thermometer size={13} className="text-text-muted" />
              <span className="text-[11px] font-medium text-text-muted">Темп:</span>
              <input
                data-testid="chat-temperature-input"
                type="number"
                min={0}
                max={2}
                step={0.05}
                value={chatTemperature}
                disabled={sending}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  if (!isNaN(val)) {
                    setChatTemperature(val);
                  }
                }}
                onBlur={(e) => {
                  const val = parseFloat(e.target.value);
                  handleTemperatureChange(isNaN(val) ? 0.7 : val);
                }}
                className="w-11 bg-transparent text-xs font-mono text-text focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Missing provider banner */}
        {providers.length === 0 && (
          <div className="flex items-center justify-between border-b border-amber-500/25 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-500">
            <span className="font-medium">⚠️ Провайдер LLM не настроен. Добавьте OpenAI-совместимый или Anthropic эндпоинт во вкладке «Настройки».</span>
          </div>
        )}

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
            {sending && (liveThinking || isThinkingLive) && (
              <ThinkingBlock
                thinking={liveThinking}
                isLive={isThinkingLive}
                duration={thinkingDuration}
              />
            )}
            {sending && liveSegments.map((seg, i) =>
              seg.kind === "tool" ? (
                <ToolStepView key={seg.step.id} step={seg.step} running={i === liveSegments.length - 1 && seg.step.output === undefined} />
              ) : (
                <LiveBubble key={`t-${i}`} text={seg.text} />
              ),
            )}
            {sending && liveSegments.length === 0 && !liveThinking && !isThinkingLive && <ThinkingIndicator />}
            {listening && !sending && <ListeningIndicator partialText={partialVoiceText} />}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Partial voice speech recognition banner */}
        {partialVoiceText && (
          <div className="flex items-center gap-2 border-t border-accent/30 bg-accent/10 px-4 py-2 text-xs text-accent animate-fade-in shadow-inner">
            <Mic size={14} className="animate-pulse shrink-0 text-accent" />
            <span className="font-medium text-accent">Распознаётся:</span>
            <span className="truncate italic text-text font-normal">«{partialVoiceText}»</span>
          </div>
        )}

        {/* Input bar */}
        <div className="flex flex-col gap-2 border-t border-border bg-surface/80 px-4 py-3">
          {/* Live voice info bar when mic is active */}
          {listening && (
            <div className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-1.5 text-xs border border-border animate-fade-in">
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
                <span className="font-medium text-text">{voiceStatus}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-text-muted">Уровень микрофона:</span>
                <div
                  className="h-2 w-24 overflow-hidden rounded bg-surface border border-border"
                  title={`Громкость микрофона: ${Math.round(audioLevel * 100)}%`}
                >
                  <div
                    className="h-full bg-accent transition-all duration-75"
                    style={{ width: `${Math.max(audioLevel > 0.02 ? 8 : 0, Math.round(audioLevel * 100))}%` }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Attachments preview bar above input box */}
          {attachments.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 pb-1" data-testid="attachments-preview">
              {attachments.map((att) =>
                att.isImage ? (
                  <div
                    key={att.id}
                    className="group relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-surface-2 shadow-xs"
                  >
                    {att.previewUrl ? (
                      <img src={att.previewUrl} alt={att.name} className="h-full w-full object-cover" />
                    ) : (
                      <Image size={20} className="text-text-muted" />
                    )}
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-black/75 text-white transition-opacity hover:bg-danger"
                      title="Удалить файл"
                      aria-label={`Удалить ${att.name}`}
                    >
                      <X size={10} />
                    </button>
                  </div>
                ) : (
                  <div
                    key={att.id}
                    className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2.5 py-1 text-xs text-text shadow-xs"
                  >
                    <FileText size={13} className="text-accent shrink-0" />
                    <span className="max-w-[140px] truncate font-medium" title={att.name}>{att.name}</span>
                    <span className="text-[10px] text-text-muted">({formatFileSize(att.size)})</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="ml-1 rounded p-0.5 text-text-muted hover:bg-danger/20 hover:text-danger"
                      title="Удалить файл"
                      aria-label={`Удалить ${att.name}`}
                    >
                      <X size={12} />
                    </button>
                  </div>
                ),
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              onClick={async () => {
                if (voiceLoading) return;
                setVoiceLoading(true);
                try {
                  const next = !listening;
                  const ok = await setVoiceMode(next);
                  setListening(ok);
                  setVoiceStatus(ok ? "Ожидает «Джарвис»" : "Отключен");
                  if (!ok) {
                    setAudioLevel(0);
                    setPartialVoiceText(null);
                    lastRecognizedRef.current = null;
                  }
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e));
                } finally {
                  setVoiceLoading(false);
                }
              }}
              disabled={voiceLoading}
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition-all ${
                listening
                  ? "border-accent bg-accent text-white shadow-sm shadow-accent/30 animate-pulse"
                  : "border-border bg-surface-2 text-text-muted hover:border-accent/50 hover:text-text"
              } disabled:opacity-60`}
              title={listening ? "Отключить голосовой режим" : "Включить голосовой режим (микрофон)"}
            >
              {voiceLoading ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-current/40 border-t-current" />
              ) : (
                <Mic size={16} />
              )}
            </button>

            {/* Hidden file input for attachment picker */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.txt,.py,.rs,.json,.md,.log,.pdf"
              className="hidden"
              onChange={(e) => {
                if (e.target.files) addFiles(Array.from(e.target.files));
                e.target.value = "";
              }}
            />

            {/* Paperclip attachment button */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={sending}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2 text-text-muted transition-all hover:border-accent/50 hover:text-text disabled:opacity-50"
              title={
                isMultimodalSupported
                  ? "Прикрепить файл или изображение"
                  : "Прикрепить файл (модель не поддерживает изображения)"
              }
              aria-label="Прикрепить файл"
            >
              <Paperclip size={18} />
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
                disabled={(!input.trim() && attachments.length === 0) || sending}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent text-white transition-all hover:brightness-110 disabled:bg-transparent disabled:text-text-muted disabled:opacity-50"
                title="Отправить"
              >
                {sending ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" /> : <Send size={14} />}
              </button>
            </div>
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

function ListeningIndicator({ partialText }: { partialText?: string | null }) {
  return (
    <div className="flex animate-fade-in justify-start" role="status" aria-live="polite">
      <div className="flex items-center gap-2 rounded-lg bg-accent-bg px-3 py-2 text-sm text-accent border border-accent/20 shadow-sm">
        <Mic size={14} className="animate-pulse shrink-0" />
        {partialText ? (
          <span className="font-medium text-text italic">«{partialText}»</span>
        ) : (
          <span>Слушаю</span>
        )}
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
        {!isUser && message.thinking && (
          <div className="w-full">
            <ThinkingBlock
              thinking={message.thinking}
              duration={message.thinkingDuration}
              isLive={false}
            />
          </div>
        )}
        {message.steps?.map((step) => (
          <div key={step.id} className="w-full">
            <ToolStepView step={step} />
          </div>
        ))}
        {isUser && message.images && message.images.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-1">
            {message.images.map((img, idx) => (
              <img
                key={idx}
                src={img}
                alt={`Прикреплённое изображение ${idx + 1}`}
                className="max-h-48 max-w-xs rounded-lg border border-border object-contain shadow-xs"
              />
            ))}
          </div>
        )}
        {message.text && (
          <div
            className={`rounded-lg px-3 py-2 text-sm transition-colors ${
              isUser
                ? "bg-accent-bg text-text"
                : "bg-surface-2 text-text"
            }`}
          >
            {message.text}
          </div>
        )}
        <span className="px-1 text-[11px] text-text-muted">
          {message.timestamp}
        </span>
      </div>
    </div>
  );
}
