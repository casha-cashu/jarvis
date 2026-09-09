import { afterEach, beforeEach, describe, expect, it } from "vitest";

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

const customEventsList: Array<{ type: string; detail?: unknown }> = [];
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
      customEventsList.push(event);
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

import {
  clearBackendHistory,
  configureBackend,
  deleteScenario,
  getBackendConfig,
  getBackendStatus,
  getBackendTimers,
  getContinuousMode,
  getScenarios,
  getSystemStats,
  listApiModels,
  listMicrophones,
  restartBackend,
  saveScenario,
  sendBackendMessage,
  setBackendConfigValue,
  setContinuousMode,
  setDefaultMicrophone,
  startBackend,
  stopBackend,
} from "./backend";

const globalProc = (
  globalThis as unknown as {
    process?: { env?: Record<string, string | undefined> };
  }
).process;
const originalVitestEnv = globalProc?.env?.VITEST;

beforeEach(() => {
  store.clear();
  customEventsList.length = 0;
  // Unset VITEST to trigger isTauri() -> false (browser mock mode)
  if (globalProc?.env) {
    delete globalProc.env.VITEST;
  }
});

afterEach(() => {
  if (globalProc?.env) {
    globalProc.env.VITEST = originalVitestEnv;
  }
});

describe("Browser Mock Implementation (when not running in Tauri)", () => {
  it("getBackendStatus reflects start/stop/restart state changes", async () => {
    let status = await getBackendStatus();
    expect(status.running).toBe(true);

    await stopBackend();
    status = await getBackendStatus();
    expect(status.running).toBe(false);
    expect(status.connected).toBe(false);

    await startBackend();
    status = await getBackendStatus();
    expect(status.running).toBe(true);
    expect(status.connected).toBe(true);

    await restartBackend();
    status = await getBackendStatus();
    expect(status.running).toBe(true);
  });

  it("getBackendConfig returns full mock config tree and saves nested updates", async () => {
    const initial = await getBackendConfig();
    expect(initial.stt?.engine).toBe("whisper");
    expect(initial.vad?.enabled).toBe(true);

    const note = await setBackendConfigValue("stt", "engine", "vosk");
    expect(note).toContain("stt.engine");

    const updated = await getBackendConfig();
    expect(updated.stt?.engine).toBe("vosk");
  });

  it("browser mock supports dot-notation in setBackendConfigValue", async () => {
    await setBackendConfigValue("stt.whisper", "model_size", "base");
    const cfg = await getBackendConfig();
    expect(cfg.stt?.whisper?.model_size).toBe("base");
  });

  it("getContinuousMode and setContinuousMode manage state and localStorage", async () => {
    expect(await getContinuousMode()).toBe(false);

    const res = await setContinuousMode(true);
    expect(res).toBe(true);
    expect(await getContinuousMode()).toBe(true);

    expect(
      customEventsList.some((e) => e.type === "jarvis:continuous-change" && e.detail === true),
    ).toBe(true);
  });

  it("scenario CRUD works seamlessly in browser mock", async () => {
    const initial = await getScenarios();
    expect(Object.keys(initial)).toContain("начинаем работу");

    await saveScenario("custom-macro", {
      name: "Custom Macro",
      actions: [{ type: "speak", text: "Ready" }],
    });

    const afterAdd = await getScenarios();
    expect(afterAdd["custom-macro"]).toBeDefined();
    expect(afterAdd["custom-macro"].name).toBe("Custom Macro");

    await deleteScenario("custom-macro");
    const afterDelete = await getScenarios();
    expect(afterDelete["custom-macro"]).toBeUndefined();
  });

  it("mock microphones and default device setting", async () => {
    const mics = await listMicrophones();
    expect(mics.length).toBeGreaterThanOrEqual(1);

    await setDefaultMicrophone("fifine");
    const cfg = await getBackendConfig();
    expect(cfg.audio?.microphone?.device_name).toBe("fifine");
  });

  it("system stats returns plausible mock telemetry", async () => {
    const stats = await getSystemStats();
    expect(stats.platform).toBe("linux");
    expect(stats.memoryTotalMb).toBeGreaterThan(0);
    expect(stats.uptimeSeconds).toBeGreaterThan(0);
  });

  it("sendBackendMessage returns mock reply", async () => {
    const reply = await sendBackendMessage("Привет");
    expect(reply).toContain("Джарвис");
  });

  it("backend_timers returns empty array in browser mock", async () => {
    const timers = await getBackendTimers();
    expect(Array.isArray(timers)).toBe(true);
  });

  it("configureBackend and clearBackendHistory work in mock mode", async () => {
    await expect(
      configureBackend({
        type: "openai",
        endpoint: "http://localhost:11434/v1",
        apiKey: "",
        model: "qwen2.5:3b",
      }),
    ).resolves.not.toThrow();

    await expect(clearBackendHistory()).resolves.not.toThrow();
  });

  it("listApiModels returns mock groups for openai and anthropic, rejects bad url", async () => {
    // Bad URL
    await expect(
      listApiModels({
        type: "openai",
        endpoint: "not-a-url",
        apiKey: "",
        model: "",
      }),
    ).rejects.toThrow("Некорректный URL");

    // OpenAI models
    const openaiGroups = await listApiModels({
      type: "openai",
      endpoint: "http://localhost:11434/v1",
      apiKey: "",
      model: "",
    });
    expect(openaiGroups[0].provider).toBe("openai");
    expect(openaiGroups[0].models).toContain("gpt-4o");

    // Anthropic models
    const anthropicGroups = await listApiModels({
      type: "anthropic",
      endpoint: "https://api.anthropic.com/v1",
      apiKey: "sk-ant",
      model: "",
    });
    expect(anthropicGroups[0].provider).toBe("anthropic");
    expect(anthropicGroups[0].models).toContain("claude-3-5-sonnet-20241022");
  });
});
