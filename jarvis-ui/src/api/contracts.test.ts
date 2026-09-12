import { beforeEach, describe, expect, it, vi } from "vitest";

// Minimal localStorage mock for Node environment
const store = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  value: {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  },
  configurable: true,
});

// Mock window & CustomEvent for Node environment
const eventLog: string[] = [];
if (typeof window === "undefined" || !window.addEventListener) {
  const listeners = new Map<string, Array<(e: unknown) => void>>();
  const mockWindow = {
    addEventListener: (event: string, cb: (e: unknown) => void) => {
      const list = listeners.get(event) ?? [];
      list.push(cb);
      listeners.set(event, list);
    },
    removeEventListener: (event: string, cb: (e: unknown) => void) => {
      const list = listeners.get(event) ?? [];
      listeners.set(event, list.filter((l) => l !== cb));
    },
    dispatchEvent: (event: { type: string; detail?: unknown }) => {
      eventLog.push(event.type);
      const list = listeners.get(event.type) ?? [];
      for (const cb of list) cb(event);
      return true;
    },
  };
  Object.defineProperty(globalThis, "window", { value: mockWindow, configurable: true });
  class MockCustomEvent {
    type: string;
    detail: unknown;
    constructor(type: string, init?: { detail?: unknown }) {
      this.type = type;
      this.detail = init?.detail;
    }
  }
  Object.defineProperty(globalThis, "CustomEvent", { value: MockCustomEvent, configurable: true });
}

const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import {
  configureBackend,
  deleteScenario,
  getContinuousMode,
  getScenarios,
  listApiModels,
  purgeAllBackendSessions,
  purgeBackendSession,
  saveScenario,
  sendBackendMessage,
  setBackendConfigValue,
  setContinuousMode,
  startBackend,
  stopBackend,
  restartBackend,
  switchBackendSession,
  deleteBackendSession,
  getBackendStatus,
  listMicrophones,
  setDefaultMicrophone,
  getSystemStats,
  getBackendConfig,
  getBackendTimers,
  clearBackendHistory,
  exportDiagnostics,
  type ScenarioItem,
  type ApiPresetConfig,
} from "./backend";

beforeEach(() => {
  store.clear();
  eventLog.length = 0;
  mockInvoke.mockReset();
});

describe("IPC Protocol Contracts (Tauri Invoke Commands)", () => {
  it("all exported frontend API functions invoke expected Tauri command names", async () => {
    // 1. backend_start
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await startBackend();
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_start", undefined);

    // 2. backend_stop
    mockInvoke.mockResolvedValueOnce('{"ok":true}');
    await stopBackend();
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_stop", undefined);

    // 3. backend_restart
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await restartBackend();
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_restart", undefined);

    // 4. backend_status
    mockInvoke.mockResolvedValueOnce({ running: true, connected: true });
    const status = await getBackendStatus();
    expect(status).toEqual({ running: true, connected: true });
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_status", undefined);

    // 5. backend_configure
    const cfg: ApiPresetConfig = {
      type: "openai",
      endpoint: "http://localhost:11434/v1",
      apiKey: "sk-test",
      model: "qwen2.5:3b",
      agentEnabled: true,
      approvalMode: "auto",
    };
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await configureBackend(cfg);
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_configure", { config: cfg });

    // 6. backend_switch_session
    mockInvoke.mockResolvedValueOnce({ ok: true, session: "sess-12345" });
    await switchBackendSession("sess-12345");
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_switch_session", { id: "sess-12345" });

    // 7. backend_delete_session
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await deleteBackendSession("sess-12345");
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_delete_session", { id: "sess-12345" });

    // 8. backend_purge_session
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await purgeBackendSession("sess-12345");
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_purge_session", { id: "sess-12345" });

    // 9. backend_purge_all_sessions
    mockInvoke.mockResolvedValueOnce({ ok: true, removed: 5 });
    await purgeAllBackendSessions();
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_purge_all_sessions", undefined);

    // 10. list_microphones & set_default_microphone
    mockInvoke.mockResolvedValueOnce([{ name: "mic1", description: "Default", isDefault: true }]);
    const mics = await listMicrophones();
    expect(mics).toHaveLength(1);
    expect(mockInvoke).toHaveBeenLastCalledWith("list_microphones", undefined);

    mockInvoke.mockResolvedValueOnce(undefined);
    await setDefaultMicrophone("mic1");
    expect(mockInvoke).toHaveBeenLastCalledWith("set_default_microphone", { name: "mic1" });

    // 11. system_stats
    mockInvoke.mockResolvedValueOnce({
      uptimeSeconds: 100,
      memoryUsedMb: 1000,
      memoryTotalMb: 4000,
      loadAverage: 0.5,
      platform: "linux",
    });
    const stats = await getSystemStats();
    expect(stats.platform).toBe("linux");
    expect(mockInvoke).toHaveBeenLastCalledWith("system_stats", undefined);

    // 12. backend_get_config
    mockInvoke.mockResolvedValueOnce({ ok: true, config: { stt: { engine: "whisper" } } });
    const conf = await getBackendConfig();
    expect(conf.stt?.engine).toBe("whisper");
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_get_config", undefined);

    // 13. backend_timers
    mockInvoke.mockResolvedValueOnce({ ok: true, timers: [{ id: "1", text: "tea", left: "10 s" }] });
    const timers = await getBackendTimers();
    expect(timers).toHaveLength(1);
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_timers", undefined);

    // 14. backend_clear_history
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await clearBackendHistory();
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_clear_history", undefined);

    // 15. backend_export_diagnostics
    mockInvoke.mockResolvedValueOnce({ ok: true, path: "/tmp/jarvis-diagnostics.zip" });
    const bundlePath = await exportDiagnostics();
    expect(bundlePath).toBe("/tmp/jarvis-diagnostics.zip");
    expect(mockInvoke).toHaveBeenLastCalledWith("backend_export_diagnostics", undefined);
  });

  it("sendBackendMessage handles empty session as null", async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, text: "Pong" });
    const reply = await sendBackendMessage("Ping");
    expect(reply).toBe("Pong");
    expect(mockInvoke).toHaveBeenCalledWith("backend_send_message", {
      message: "Ping",
      session: null,
    });
  });

  it("sendBackendMessage surfaces error when backend returns ok=false", async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: false,
      error: "Уже обрабатывается сообщение",
    });
    await expect(sendBackendMessage("Hello")).rejects.toThrow("Уже обрабатывается сообщение");
  });
});

describe("Scenario Management Contracts", () => {
  it("getScenarios returns dictionary of scenarios on success", async () => {
    const mockData: Record<string, ScenarioItem> = {
      work: {
        name: "Work",
        actions: [{ type: "workspace", target: 2 }],
      },
    };
    mockInvoke.mockResolvedValueOnce({ ok: true, scenarios: mockData });
    const res = await getScenarios();
    expect(res).toEqual(mockData);
    expect(mockInvoke).toHaveBeenCalledWith("backend_get_scenarios", undefined);
  });

  it("saveScenario passes id and data correctly", async () => {
    const item: ScenarioItem = {
      name: "Test",
      actions: [{ type: "speak", text: "Hi" }],
    };
    mockInvoke.mockResolvedValueOnce({ ok: true });
    const success = await saveScenario("test-macro", item);
    expect(success).toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith("backend_save_scenario", {
      id: "test-macro",
      data: item,
    });
  });

  it("saveScenario throws error if backend fails", async () => {
    mockInvoke.mockResolvedValueOnce({ ok: false, error: "Disk full" });
    await expect(
      saveScenario("fail", { name: "fail", actions: [] }),
    ).rejects.toThrow("Disk full");
  });

  it("deleteScenario passes id and handles error", async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await expect(deleteScenario("macro-1")).resolves.toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith("backend_delete_scenario", { id: "macro-1" });

    mockInvoke.mockResolvedValueOnce({ ok: false });
    await expect(deleteScenario("macro-2")).rejects.toThrow("Не удалось удалить сценарий");
  });
});

describe("Continuous Mode Contract", () => {
  it("getContinuousMode reads boolean state", async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, continuous: true });
    const res = await getContinuousMode();
    expect(res).toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith("backend_get_continuous", undefined);
  });

  it("setContinuousMode sends enabled and persist flags", async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, continuous: true });
    const res = await setContinuousMode(true, true);
    expect(res).toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith("backend_set_continuous", {
      enabled: true,
      persist: true,
    });
  });
});

describe("Model Listing and Validation Contract", () => {
  it("listApiModels unwraps groups correctly", async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true,
      groups: [
        { provider: "deepseek", models: ["deepseek-chat", "deepseek-coder"] },
      ],
    });
    const groups = await listApiModels({
      type: "openai",
      endpoint: "https://api.deepseek.com/v1",
      apiKey: "sk-...",
      model: "",
    });
    expect(groups).toHaveLength(1);
    expect(groups[0].provider).toBe("deepseek");
    expect(groups[0].models).toContain("deepseek-chat");
  });

  it("listApiModels throws if backend rejects configuration", async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: false,
      error: "Endpoint и API ключ обязательны",
    });
    await expect(
      listApiModels({
        type: "openai",
        endpoint: "https://api.openai.com/v1",
        apiKey: "",
        model: "",
      }),
    ).rejects.toThrow("Endpoint и API ключ обязательны");
  });

  it("listApiModels allows local endpoints without apiKey", async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true,
      groups: [{ provider: "ollama", models: ["qwen2.5:3b"] }],
    });
    const groups = await listApiModels({
      type: "openai",
      endpoint: "http://localhost:11434/v1",
      apiKey: "",
      model: "",
    });
    expect(groups).toHaveLength(1);
    expect(groups[0].models).toContain("qwen2.5:3b");
    expect(mockInvoke).toHaveBeenCalledWith("backend_list_models", {
      config: {
        type: "openai",
        endpoint: "http://localhost:11434/v1",
        apiKey: "",
        model: "",
      },
    });
  });
});

describe("Config Setting Dot-notation Contract", () => {
  it("setBackendConfigValue sends section, key, and value cleanly", async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true,
      note: "Сохранено: stt.whisper.model_size = base",
    });
    const note = await setBackendConfigValue("stt.whisper", "model_size", "base");
    expect(note).toContain("base");
    expect(mockInvoke).toHaveBeenCalledWith("backend_set_config_value", {
      section: "stt.whisper",
      key: "model_size",
      value: "base",
    });
  });

  it("setBackendConfigValue throws backend validation errors", async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: false,
      error: "Секция unapproved не редактируется из GUI",
    });
    await expect(
      setBackendConfigValue("unapproved", "key", "val"),
    ).rejects.toThrow("Секция unapproved не редактируется из GUI");
  });
});

describe("Session Serialization and Event Reactivity Contracts", () => {
  it("validates session serialization format", () => {
    const sessionData = {
      id: "sess-abc12345",
      title: "Тестовая сессия",
      lastMessage: "Ответ получен",
      timestamp: "2026-09-04T12:00:00Z",
      messages: [
        {
          id: "m1",
          role: "user" as const,
          text: "Привет",
          timestamp: "2026-09-04T12:00:00Z",
        },
        {
          id: "m2",
          role: "assistant" as const,
          text: "Здравствуйте, сэр.",
          timestamp: "2026-09-04T12:00:01Z",
          steps: [
            { id: "s1", name: "bash", input: "ls", output: "file.txt" },
          ],
        },
      ],
    };

    store.set("jarvis.ui.chats", JSON.stringify([sessionData]));
    const stored = JSON.parse(store.get("jarvis.ui.chats") ?? "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0].id).toBe("sess-abc12345");
    expect(stored[0].messages[1].steps[0].name).toBe("bash");
  });

  it("reacts to jarvis:history-updated and jarvis:providers-changed events", () => {
    let historyUpdatedCount = 0;
    let providersChangedCount = 0;

    const onHistoryUpdated = () => {
      historyUpdatedCount++;
    };
    const onProvidersChanged = () => {
      providersChangedCount++;
    };

    window.addEventListener("jarvis:history-updated", onHistoryUpdated);
    window.addEventListener("jarvis:providers-changed", onProvidersChanged);

    window.dispatchEvent(new CustomEvent("jarvis:history-updated"));
    expect(historyUpdatedCount).toBe(1);

    window.dispatchEvent(new CustomEvent("jarvis:providers-changed"));
    expect(providersChangedCount).toBe(1);

    window.removeEventListener("jarvis:history-updated", onHistoryUpdated);
    window.removeEventListener("jarvis:providers-changed", onProvidersChanged);

    window.dispatchEvent(new CustomEvent("jarvis:history-updated"));
    expect(historyUpdatedCount).toBe(1);
  });
});
