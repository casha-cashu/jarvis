import { invoke } from "@tauri-apps/api/core";

export interface BackendStatus {
  running: boolean;
  connected: boolean;
}

function isTauri(): boolean {
  const isVitest =
    typeof globalThis !== "undefined" &&
    Boolean(
      (
        globalThis as unknown as {
          process?: { env?: { VITEST?: string; NODE_ENV?: string } };
        }
      ).process?.env?.VITEST,
    );
  if (isVitest) {
    return true;
  }
  return (
    typeof window !== "undefined" &&
    Boolean((window as unknown as { __TAURI_INTERNALS__?: { invoke?: unknown } }).__TAURI_INTERNALS__?.invoke)
  );
}

async function safeInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauri()) {
    return handleBrowserMock<T>(cmd, args);
  }
  try {
    return await invoke<T>(cmd, args);
  } catch (err: unknown) {
    if (err instanceof Error) {
      throw err;
    }
    if (typeof err === "string") {
      throw new Error(err);
    }
    if (
      err &&
      typeof err === "object" &&
      "message" in err &&
      typeof (err as { message: unknown }).message === "string"
    ) {
      throw new Error((err as { message: string }).message);
    }
    throw new Error(String(err ?? "Неизвестная ошибка Tauri IPC"));
  }
}

async function unwrap(response: { ok: boolean; error?: string }): Promise<void> {
  if (!response.ok) throw new Error(response.error ?? "Ошибка backend");
}

export async function startBackend(): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_start");
  await unwrap(response);
}

export async function stopBackend(): Promise<void> {
  await safeInvoke("backend_stop");
}

export async function restartBackend(): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_restart");
  await unwrap(response);
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent("jarvis:backend-restarted"));
  }
}

export async function getBackendStatus(): Promise<BackendStatus> {
  return safeInvoke<BackendStatus>("backend_status");
}

export interface ApiPresetConfig {
  type: "openai" | "anthropic";
  endpoint: string;
  apiKey: string;
  model: string;
  agentEnabled?: boolean;
  approvalMode?: string;
}

export interface MicrophoneDevice {
  name: string;
  description: string;
  isDefault: boolean;
}

export interface SystemStats {
  uptimeSeconds: number;
  memoryUsedMb: number;
  memoryTotalMb: number;
  loadAverage: number;
  platform: string;
}

export interface ModelGroup {
  provider: string;
  models: string[];
}

export interface BackendTimer {
  id: string;
  text: string;
  left: string;
}

export async function configureBackend(config: ApiPresetConfig): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_configure", { config });
  await unwrap(response);
}

export async function listApiModels(config: ApiPresetConfig): Promise<ModelGroup[]> {
  const response = await safeInvoke<{ ok: boolean; groups?: ModelGroup[]; error?: string }>("backend_list_models", { config });
  if (!response.ok) throw new Error(response.error ?? "Не удалось получить модели");
  const groups = response.groups ?? [];
  return groups.filter(
    (g): g is ModelGroup =>
      Boolean(
        g &&
        typeof g === "object" &&
        typeof g.provider === "string" &&
        Array.isArray(g.models) &&
        g.models.length > 0,
      ),
  );
}

export async function getBackendTimers(): Promise<BackendTimer[]> {
  const response = await safeInvoke<{ ok: boolean; timers?: BackendTimer[]; error?: string }>("backend_timers");
  if (!response.ok) throw new Error(response.error ?? "Таймеры недоступны");
  return response.timers ?? [];
}

export async function clearBackendHistory(): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_clear_history");
  await unwrap(response);
}

export async function switchBackendSession(id: string): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_switch_session", { id });
  await unwrap(response);
}

export async function deleteBackendSession(id: string): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_delete_session", { id });
  await unwrap(response);
}

export async function purgeBackendSession(id: string): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_purge_session", { id });
  await unwrap(response);
}

export async function purgeAllBackendSessions(): Promise<void> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_purge_all_sessions");
  await unwrap(response);
}

export async function exportDiagnostics(): Promise<string> {
  const response = await safeInvoke<{ ok: boolean; path?: string; error?: string }>("backend_export_diagnostics");
  if (!response.ok || !response.path) throw new Error(response.error ?? "Не удалось сформировать отчёт");
  return response.path;
}

export interface BackendConfigTree {
  audio?: {
    microphone?: { device_name?: string | null; sample_rate?: number };
    output?: { device_name?: string | null; sample_rate?: number };
  };
  stt?: {
    engine?: string;
    sample_rate?: number;
    wake_word?: string;
    wake_word_alternatives?: string[];
    continuous?: boolean;
    phrase_time_limit?: number;
    silence_threshold?: number | null;
    multi_turn_timeout?: number;
    wake_mode?: string;
    vosk?: { model_path?: string; model_size?: string };
    whisper?: {
      model_path?: string | null;
      model_size?: string;
      partial_interval_ms?: number;
    };
  };
  vad?: {
    enabled?: boolean;
    engine?: string;
    silero?: { model_path?: string; threshold?: number };
  };
  tts?: {
    engine?: string;
    piper?: {
      binary_path?: string | null;
      model_path?: string | null;
      config_path?: string | null;
      speaker_id?: number;
      length_scale?: number;
    };
    gtts?: { lang?: string; slow?: boolean };
    speecht5?: {
      model?: string | null;
      vocoder_path?: string | null;
      device?: string;
      speaker_id?: number;
    };
  };
  llm?: {
    provider?: string;
    model?: string | null;
    agent_enabled?: boolean;
    agent_approval_mode?: string;
    agent_max_iterations?: number;
    max_history?: number;
    system_prompt?: string | null;
    temperature?: number | null;
    max_tokens?: number | null;
    ollama?: { base_url?: string; model?: string; temperature?: number; timeout?: number };
    openai?: { model?: string; temperature?: number; max_tokens?: number; timeout?: number };
    anthropic?: { model?: string; temperature?: number; max_tokens?: number; timeout?: number };
    openrouter?: { model?: string; temperature?: number; max_tokens?: number; timeout?: number };
  };
  commands?: {
    fuzzy_threshold?: number;
    execution_timeout?: number;
    nlu_enabled?: boolean;
    nlu_confidence_threshold?: number;
    scenarios_path?: string;
  };
  web_search?: {
    enabled?: boolean;
    provider?: string;
    brave_api_key?: string | null;
    tavily_api_key?: string | null;
    max_results?: number;
  };
  logging?: {
    level?: string;
    file?: string;
    max_size?: number;
  };
  telegram?: {
    enabled?: boolean;
    bot_token?: string | null;
    allowed_chat_ids?: number[];
  };
  misc?: {
    temp_dir?: string;
  };
}

export type BackendConfigInfo = BackendConfigTree;

export async function getBackendConfig(): Promise<BackendConfigTree> {
  const response = await safeInvoke<{ ok: boolean; config?: BackendConfigTree; error?: string }>(
    "backend_get_config",
  );
  if (!response.ok) throw new Error(response.error ?? "Конфиг недоступен");
  return response.config ?? {};
}

export async function setBackendConfigValue(
  section: string,
  key: string,
  value: unknown,
): Promise<string> {
  const response = await safeInvoke<{ ok: boolean; note?: string; error?: string }>(
    "backend_set_config_value",
    { section, key, value },
  );
  if (!response.ok) throw new Error(response.error ?? "Не удалось сохранить");
  return response.note ?? "Сохранено";
}

export async function getContinuousMode(): Promise<boolean> {
  const response = await safeInvoke<{ ok: boolean; continuous?: boolean; error?: string }>("backend_get_continuous");
  await unwrap(response);
  return Boolean(response.continuous);
}

export async function setContinuousMode(enabled: boolean, persist = true): Promise<boolean> {
  const response = await safeInvoke<{ ok: boolean; continuous?: boolean; error?: string }>("backend_set_continuous", {
    enabled,
    persist,
  });
  await unwrap(response);
  const continuous = Boolean(response.continuous);
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent("jarvis:continuous-change", { detail: continuous }));
  }
  return continuous;
}

export async function getVoiceMode(): Promise<boolean> {
  const response = await safeInvoke<{ ok: boolean; voice_enabled?: boolean; error?: string }>("backend_get_voice_mode");
  await unwrap(response);
  return Boolean(response.voice_enabled);
}

export async function setVoiceMode(enabled: boolean): Promise<boolean> {
  const response = await safeInvoke<{ ok: boolean; voice_enabled?: boolean; error?: string }>("backend_set_voice_mode", {
    enabled,
  });
  await unwrap(response);
  const voiceEnabled = Boolean(response.voice_enabled);
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent("jarvis:voice-mode-change", { detail: voiceEnabled }));
  }
  return voiceEnabled;
}

export interface ScenarioAction {
  type: "workspace" | "launch" | "command" | "volume" | "speak" | "delay";
  target?: string | number;
  amount?: number;
  text?: string;
  seconds?: number;
}

export interface ScenarioItem {
  name: string;
  description?: string;
  phrases?: string[];
  actions: ScenarioAction[];
}

export async function getScenarios(): Promise<Record<string, ScenarioItem>> {
  const response = await safeInvoke<{ ok: boolean; scenarios?: Record<string, ScenarioItem>; error?: string }>(
    "backend_get_scenarios",
  );
  if (!response.ok) throw new Error(response.error ?? "Не удалось загрузить сценарии");
  return response.scenarios ?? {};
}

export async function saveScenario(id: string, data: ScenarioItem): Promise<boolean> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_save_scenario", { id, data });
  if (!response.ok) throw new Error(response.error ?? "Не удалось сохранить сценарий");
  return true;
}

export async function deleteScenario(id: string): Promise<boolean> {
  const response = await safeInvoke<{ ok: boolean; error?: string }>("backend_delete_scenario", { id });
  if (!response.ok) throw new Error(response.error ?? "Не удалось удалить сценарий");
  return true;
}

export async function listMicrophones(): Promise<MicrophoneDevice[]> {
  return safeInvoke("list_microphones");
}

export async function setDefaultMicrophone(name: string): Promise<void> {
  await safeInvoke("set_default_microphone", { name });
}

export async function getSystemStats(): Promise<SystemStats> {
  return safeInvoke("system_stats");
}

export async function sendBackendMessage(message: string, sessionId?: string): Promise<string> {
  const response = await safeInvoke<{ ok: boolean; text?: string; error?: string }>(
    "backend_send_message",
    { message, session: sessionId ?? null },
  );
  if (!response.ok) throw new Error(response.error ?? "Ошибка backend");
  return response.text ?? "";
}

// ── Browser Mock Implementation ───────────────────────────────────────────────

export const DEFAULT_SYSTEM_PROMPT = `Ты — JARVIS, персональный ИИ-ассистент, инженер и эксперт по Linux и разработке ПО ({platform}).
Сейчас: {datetime}.

# Тон и стиль общения (Tone & Style)
- Отвечай кратко, прямо и строго по существу задачи.
- Минимизируй количество токенов без потери качества и точности. Если можно ответить в 1-3 предложениях или одним словом — так и сделай.
- Не используй вводных фраз («Конечно!», «Рад помочь», «Вот ваш ответ:», «Основываясь на данных...») и не повторяй вопрос пользователя.
- Не используй эмодзи, если пользователь явно об этом не попросил.
- Ответы выводятся в интерфейс и могут озвучиваться голосовым движком: строй фразы естественно, избегая визуального и текстового шума.

# Профессиональная объективность (Professional Objectivity)
- Ставь техническую точность и факты выше ложной вежливости.
- Отвечай прямо и объективно, без лести, похвалы или эмоциональной валидации.
- Честно указывай на ошибки в коде или неоптимальные решения, даже если пользователь ожидал согласия. Объективное руководство и аргументированная коррекция ценнее ложного согласия.
- При наличии сомнений исследуй систему и код инструментами, а не угадывай.

# Работа с инструментами и Bash
- Для получения актуальных фактов о системе и выполнения действий используй инструменты (bash/read/write/web_search), а не догадки.
- При запуске нетривиальных команд кратко поясняй, что команда делает, особенно если она вносит изменения в систему.
- Всегда отдавай предпочтение безопасным и неразрушающим операциям. Предупреждай перед выполнением потенциально опасных действий.
- После выполнения команды или редактирования файла кратко подведи итог или остановись, не пересказывая код целиком без просьбы пользователя.

# Соглашения и разработка (Conventions & Code)
- Пиши чистый, идиоматичный и безопасный код с обработкой граничных случаев.
- Изучай и соблюдай стиль существующего проекта, используемые библиотеки и архитектуру.
- Никогда не предполагай наличие библиотеки, пока не убедишься, что она уже используется в проекте.
- Не добавляй лишних комментариев в код, если пользователь об этом не просил.
- Не создавай новые файлы, если задачу можно решить редактированием существующих.
- Никогда не выводи и не коммить секреты, токены и API-ключи.`;

const DEFAULT_MOCK_CONFIG: BackendConfigTree = {
  audio: {
    microphone: { device_name: "Fifine K669 USB", sample_rate: 16000 },
    output: { device_name: null, sample_rate: 48000 },
  },
  stt: {
    engine: "whisper",
    sample_rate: 16000,
    wake_word: "джарвис",
    wake_word_alternatives: ["жарвис", "джервис", "jarvis"],
    continuous: false,
    phrase_time_limit: 10,
    silence_threshold: 1.0,
    multi_turn_timeout: 10,
    wake_mode: "classic",
    vosk: { model_size: "small-ru", model_path: "auto" },
    whisper: { model_size: "tiny", partial_interval_ms: 1000 },
  },
  vad: {
    enabled: true,
    engine: "silero",
    silero: { threshold: 0.5 },
  },
  tts: {
    engine: "piper",
    piper: { speaker_id: 0, length_scale: 1.0 },
  },
  llm: {
    provider: "openai",
    model: "gpt-4o",
    agent_enabled: true,
    agent_approval_mode: "auto",
    agent_max_iterations: 5,
    max_history: 20,
    system_prompt: DEFAULT_SYSTEM_PROMPT,
    temperature: 0.7,
    max_tokens: null,
  },
  commands: {
    fuzzy_threshold: 0.8,
    execution_timeout: 30,
    nlu_enabled: true,
    nlu_confidence_threshold: 0.65,
  },
  web_search: {
    enabled: true,
    provider: "duckduckgo",
    max_results: 5,
  },
  logging: { level: "INFO", file: "logs/jarvis.log", max_size: 10485760 },
  telegram: { enabled: false, allowed_chat_ids: [] },
};

function getMockConfig(): BackendConfigTree {
  try {
    if (typeof localStorage !== "undefined") {
      const raw = localStorage.getItem("jarvis.mock_config");
      if (raw) return JSON.parse(raw);
    }
  } catch {
    /* ignore */
  }
  return JSON.parse(JSON.stringify(DEFAULT_MOCK_CONFIG));
}

function saveMockConfig(conf: BackendConfigTree): void {
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("jarvis.mock_config", JSON.stringify(conf));
    }
  } catch {
    /* ignore */
  }
}

function setNestedConfig(target: Record<string, unknown>, path: string[], value: unknown): void {
  let cur = target;
  for (let i = 0; i < path.length - 1; i++) {
    const p = path[i];
    if (!cur[p] || typeof cur[p] !== "object") {
      cur[p] = {};
    }
    cur = cur[p] as Record<string, unknown>;
  }
  cur[path[path.length - 1]] = value;
}

const DEFAULT_MOCK_SCENARIOS: Record<string, ScenarioItem> = {
  "начинаем работу": {
    name: "Начинаем работу",
    description: "Переключает на воркспейс 2, запускает редактор кода и терминал",
    phrases: ["начинаем работу", "рабочий режим", "пора за работу"],
    actions: [
      { type: "workspace", target: 2 },
      { type: "launch", target: "code" },
      { type: "speak", text: "Рабочее окружение запущено, сэр." },
    ],
  },
  "режим отдыха": {
    name: "Режим отдыха",
    description: "Ставит комфортную громкость и включает музыку",
    phrases: ["режим отдыха", "время отдыхать"],
    actions: [
      { type: "volume", amount: 40 },
      { type: "speak", text: "Приятного отдыха, сэр." },
    ],
  },
};

function getMockScenarios(): Record<string, ScenarioItem> {
  try {
    if (typeof localStorage !== "undefined") {
      const raw = localStorage.getItem("jarvis.mock_scenarios");
      if (raw) return JSON.parse(raw);
    }
  } catch {
    /* ignore */
  }
  return JSON.parse(JSON.stringify(DEFAULT_MOCK_SCENARIOS));
}

function saveMockScenarios(items: Record<string, ScenarioItem>): void {
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("jarvis.mock_scenarios", JSON.stringify(items));
    }
  } catch {
    /* ignore */
  }
}

let browserStatus = { running: true, connected: true };
let browserContinuous = false;
let browserVoiceMode = false;

async function handleBrowserMock<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (cmd === "backend_status") {
    return browserStatus as T;
  }
  if (cmd === "backend_start") {
    browserStatus = { running: true, connected: true };
    return { ok: true, started: true } as T;
  }
  if (cmd === "backend_stop") {
    browserStatus = { running: false, connected: false };
    browserVoiceMode = false;
    return { ok: true, started: false } as T;
  }
  if (cmd === "backend_restart") {
    browserStatus = { running: true, connected: true };
    return { ok: true, started: true } as T;
  }
  if (cmd === "backend_get_voice_mode") {
    return { ok: true, voice_enabled: browserVoiceMode } as T;
  }
  if (cmd === "backend_set_voice_mode") {
    browserVoiceMode = Boolean(args?.enabled);
    return { ok: true, voice_enabled: browserVoiceMode } as T;
  }
  if (cmd === "backend_get_config") {
    return { ok: true, config: getMockConfig() } as T;
  }
  if (cmd === "backend_set_config_value") {
    const sec = String(args?.section ?? "");
    const key = String(args?.key ?? "");
    const val = args?.value;
    const path = (sec ? `${sec}.${key}` : key).split(".").filter(Boolean);
    const conf = getMockConfig();
    setNestedConfig(conf as unknown as Record<string, unknown>, path, val);
    saveMockConfig(conf);
    return { ok: true, note: `Сохранено: ${path.join(".")} = ${JSON.stringify(val)}` } as T;
  }
  if (cmd === "backend_get_continuous") {
    const conf = getMockConfig();
    browserContinuous = Boolean(conf.stt?.continuous ?? browserContinuous);
    return { ok: true, continuous: browserContinuous } as T;
  }
  if (cmd === "backend_set_continuous") {
    browserContinuous = Boolean(args?.enabled);
    const conf = getMockConfig();
    if (!conf.stt) conf.stt = {};
    conf.stt.continuous = browserContinuous;
    saveMockConfig(conf);
    return { ok: true, continuous: browserContinuous } as T;
  }
  if (cmd === "backend_get_scenarios") {
    return { ok: true, scenarios: getMockScenarios() } as T;
  }
  if (cmd === "backend_save_scenario") {
    const id = String(args?.id ?? "").trim();
    if (id && args?.data) {
      const all = getMockScenarios();
      all[id] = args.data as ScenarioItem;
      saveMockScenarios(all);
    }
    return { ok: true } as T;
  }
  if (cmd === "backend_delete_scenario") {
    const id = String(args?.id ?? "").trim();
    const all = getMockScenarios();
    delete all[id];
    saveMockScenarios(all);
    return { ok: true } as T;
  }
  if (cmd === "list_microphones") {
    return [
      { name: "default", description: "Встроенный микрофон (системный)", isDefault: true },
      { name: "fifine", description: "Fifine K669 USB Microphone", isDefault: false },
    ] as T;
  }
  if (cmd === "set_default_microphone") {
    const name = String(args?.name ?? "");
    const conf = getMockConfig();
    if (!conf.audio) conf.audio = {};
    if (!conf.audio.microphone) conf.audio.microphone = {};
    conf.audio.microphone.device_name = name;
    saveMockConfig(conf);
    return { ok: true } as T;
  }
  if (cmd === "system_stats") {
    return {
      uptimeSeconds: 14400,
      memoryUsedMb: 3200,
      memoryTotalMb: 16000,
      loadAverage: 0.85,
      platform: "linux",
    } as T;
  }
  if (cmd === "backend_timers") {
    return { ok: true, timers: [] } as T;
  }
  if (cmd === "backend_list_models") {
    const conf = (args?.config as ApiPresetConfig | undefined) ?? { type: "openai", endpoint: "", apiKey: "", model: "" };
    const ep = conf.endpoint?.trim() || "";
    try {
      const u = new URL(ep);
      if (!u.protocol.startsWith("http")) throw new Error();
      if (u.hostname.includes("dsdasd") || u.hostname.endsWith(".fake") || u.hostname.endsWith(".dsadasd")) {
        throw new Error("Хост не существует");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "";
      return {
        ok: false,
        error: msg.includes("Хост")
          ? "Хост недоступен или не существует"
          : "Некорректный URL эндпоинта (должен начинаться с http:// или https://)",
      } as T;
    }

    const isTestEnv = Boolean(import.meta.env?.MODE === "test");

    if (typeof fetch !== "undefined" && !isTestEnv) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 2500);
        await fetch(ep, { method: "HEAD", mode: "no-cors", signal: controller.signal });
        clearTimeout(timer);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          ok: false,
          error: `Не удалось подключиться к эндпоинту (${msg.includes("abort") ? "таймаут подключения" : "сервер недоступен или ошибка сети"})`,
        } as T;
      }
    }

    if (conf.type === "anthropic") {
      return {
        ok: true,
        groups: [
          { provider: "anthropic", models: ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"] },
        ],
      } as T;
    }
    return {
      ok: true,
      groups: [
        { provider: "openai", models: ["gpt-4o", "gpt-4o-mini", "o1-mini", "qwen2.5:3b", "llama3.2:3b"] },
      ],
    } as T;
  }
  if (cmd === "backend_send_message") {
    return { ok: true, text: "Ответ Джарвиса: Команда принята." } as T;
  }
  return { ok: true } as T;
}
