import { beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...args: unknown[]) => invoke(...args) }));

import {
  clearBackendHistory,
  configureBackend,
  deleteBackendSession,
  deleteScenario,
  getBackendConfig,
  getBackendStatus,
  getBackendTimers,
  getContinuousMode,
  getScenarios,
  getSystemStats,
  listApiModels,
  listMicrophones,
  purgeAllBackendSessions,
  purgeBackendSession,
  restartBackend,
  saveScenario,
  sendBackendMessage,
  setBackendConfigValue,
  setContinuousMode,
  setDefaultMicrophone,
  startBackend,
  stopBackend,
  switchBackendSession,
  getVoiceMode,
  setVoiceMode,
  type ApiPresetConfig,
  type ScenarioItem,
} from "./backend";

beforeEach(() => {
  invoke.mockReset();
});

describe("Backend Lifecycle and Status Wrappers", () => {
  it("startBackend, stopBackend, restartBackend invoke corresponding commands", async () => {
    invoke.mockResolvedValueOnce({ ok: true });
    await startBackend();
    expect(invoke).toHaveBeenCalledWith("backend_start", undefined);

    invoke.mockResolvedValueOnce({ ok: true });
    await stopBackend();
    expect(invoke).toHaveBeenCalledWith("backend_stop", undefined);
  });

  it("startBackend calls unwrap and throws error when ok is false", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "Start failed" });
    await expect(startBackend()).rejects.toThrow("Start failed");
  });

  it("safeInvoke converts rejected string from Tauri IPC into Error instance", async () => {
    invoke.mockRejectedValueOnce("Bridge process crashed");
    await expect(startBackend()).rejects.toThrow("Bridge process crashed");
    invoke.mockRejectedValueOnce("IPC failure");
    await expect(getBackendStatus()).rejects.toBeInstanceOf(Error);
  });

  it("restartBackend calls unwrap, dispatches jarvis:backend-restarted event, and throws on error", async () => {
    const dispatchSpy = vi.fn();
    (globalThis as unknown as { window?: { dispatchEvent: unknown } }).window = {
      dispatchEvent: dispatchSpy,
    };
    class MockCustomEvent {
      type: string;
      detail: unknown;
      constructor(type: string, init?: { detail?: unknown }) {
        this.type = type;
        this.detail = init?.detail;
      }
    }
    (globalThis as unknown as { CustomEvent?: unknown }).CustomEvent = MockCustomEvent;

    invoke.mockResolvedValueOnce({ ok: true });
    await restartBackend();
    expect(invoke).toHaveBeenCalledWith("backend_restart", undefined);
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: "jarvis:backend-restarted" }),
    );

    invoke.mockResolvedValueOnce({ ok: false, error: "Restart failed" });
    await expect(restartBackend()).rejects.toThrow("Restart failed");
  });

  it("getBackendStatus returns status object", async () => {
    invoke.mockResolvedValueOnce({ running: true, connected: true });
    const status = await getBackendStatus();
    expect(status).toEqual({ running: true, connected: true });
  });

  it("configureBackend calls unwrap and throws error when ok is false", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "Invalid provider configuration" });
    const cfg: ApiPresetConfig = {
      type: "openai",
      endpoint: "http://localhost:11434/v1",
      apiKey: "",
      model: "qwen2.5:3b",
    };
    await expect(configureBackend(cfg)).rejects.toThrow("Invalid provider configuration");
  });
});

describe("Session Management Wrappers", () => {
  it("switchBackendSession, deleteBackendSession, purgeBackendSession, purgeAllBackendSessions", async () => {
    invoke.mockResolvedValueOnce({ ok: true });
    await switchBackendSession("s-1");
    expect(invoke).toHaveBeenCalledWith("backend_switch_session", { id: "s-1" });

    invoke.mockResolvedValueOnce({ ok: true });
    await deleteBackendSession("s-1");
    expect(invoke).toHaveBeenCalledWith("backend_delete_session", { id: "s-1" });

    invoke.mockResolvedValueOnce({ ok: true });
    await purgeBackendSession("s-1");
    expect(invoke).toHaveBeenCalledWith("backend_purge_session", { id: "s-1" });

    invoke.mockResolvedValueOnce({ ok: true });
    await purgeAllBackendSessions();
    expect(invoke).toHaveBeenCalledWith("backend_purge_all_sessions", undefined);
  });

  it("purgeBackendSession throws on failure", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "Cannot purge" });
    await expect(purgeBackendSession("s-fail")).rejects.toThrow("Cannot purge");
  });
});

describe("Hardware and System Telemetry Wrappers", () => {
  it("listMicrophones, setDefaultMicrophone, getSystemStats", async () => {
    invoke.mockResolvedValueOnce([{ name: "usb_mic", description: "USB Mic", isDefault: true }]);
    const mics = await listMicrophones();
    expect(mics).toHaveLength(1);
    expect(mics[0].name).toBe("usb_mic");

    invoke.mockResolvedValueOnce(undefined);
    await setDefaultMicrophone("usb_mic");
    expect(invoke).toHaveBeenCalledWith("set_default_microphone", { name: "usb_mic" });

    invoke.mockResolvedValueOnce({
      uptimeSeconds: 3600,
      memoryUsedMb: 500,
      memoryTotalMb: 16000,
      loadAverage: 1.2,
      platform: "linux",
    });
    const stats = await getSystemStats();
    expect(stats.uptimeSeconds).toBe(3600);
  });
});

describe("Scenarios and Continuous Mode Wrappers", () => {
  it("getScenarios, saveScenario, deleteScenario handle success and errors", async () => {
    const scItem: ScenarioItem = { name: "Test", actions: [] };
    invoke.mockResolvedValueOnce({ ok: true, scenarios: { sc1: scItem } });
    const list = await getScenarios();
    expect(list.sc1.name).toBe("Test");

    invoke.mockResolvedValueOnce({ ok: true });
    await expect(saveScenario("sc1", scItem)).resolves.toBe(true);

    invoke.mockResolvedValueOnce({ ok: true });
    await expect(deleteScenario("sc1")).resolves.toBe(true);
  });

  it("getContinuousMode and setContinuousMode return boolean and dispatch event", async () => {
    const dispatchSpy = vi.fn();
    (globalThis as unknown as { window?: { dispatchEvent: unknown } }).window = {
      dispatchEvent: dispatchSpy,
    };
    class MockCustomEvent {
      type: string;
      detail: unknown;
      constructor(type: string, init?: { detail?: unknown }) {
        this.type = type;
        this.detail = init?.detail;
      }
    }
    (globalThis as unknown as { CustomEvent?: unknown }).CustomEvent = MockCustomEvent;

    invoke.mockResolvedValueOnce({ ok: true, continuous: true });
    expect(await getContinuousMode()).toBe(true);

    invoke.mockResolvedValueOnce({ ok: true, continuous: false });
    expect(await setContinuousMode(false, true)).toBe(false);
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: "jarvis:continuous-change", detail: false }),
    );
  });

  it("getContinuousMode and setContinuousMode throw error when ok is false", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "Continuous mode failed" });
    await expect(getContinuousMode()).rejects.toThrow("Continuous mode failed");

    invoke.mockResolvedValueOnce({ ok: false, error: "Set continuous failed" });
    await expect(setContinuousMode(true)).rejects.toThrow("Set continuous failed");
  });
});

describe("Configuration and History Wrappers", () => {
  it("getBackendConfig возвращает config при ok", async () => {
    invoke.mockResolvedValueOnce({
      ok: true,
      config: { stt: { engine: "whisper" }, tts: { engine: "piper" }, llm: { provider: "ollama", model: "qwen2.5:3b" } },
    });
    const cfg = await getBackendConfig();
    expect(cfg.stt?.engine).toBe("whisper");
    expect(cfg.llm?.model).toBe("qwen2.5:3b");
  });

  it("getBackendConfig пробрасывает ошибку бекенда", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "Конфиг невалиден" });
    await expect(getBackendConfig()).rejects.toThrow("Конфиг невалиден");
  });

  it("getBackendTimers ошибка → исключение с текстом", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "Таймеры недоступны" });
    await expect(getBackendTimers()).rejects.toThrow("Таймеры недоступны");
  });

  it("sendBackendMessage возвращает текст ответа", async () => {
    invoke.mockResolvedValueOnce({ ok: true, text: "Готово, сэр." });
    await expect(sendBackendMessage("привет", "sess-1")).resolves.toBe("Готово, сэр.");
    expect(invoke).toHaveBeenCalledWith("backend_send_message", {
      message: "привет",
      session: "sess-1",
    });
  });

  it("sendBackendMessage без сессии шлёт null", async () => {
    invoke.mockResolvedValueOnce({ ok: true, text: "ок" });
    await sendBackendMessage("тест");
    expect(invoke).toHaveBeenCalledWith("backend_send_message", {
      message: "тест",
      session: null,
    });
  });

  it("clearBackendHistory ошибка → исключение", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "нет бриджа" });
    await expect(clearBackendHistory()).rejects.toThrow("нет бриджа");
  });

  it("setBackendConfigValue возвращает note при ok", async () => {
    invoke.mockResolvedValueOnce({ ok: true, note: "Сохранено: stt.engine = whisper" });
    const note = await setBackendConfigValue("stt", "engine", "whisper");
    expect(note).toContain("whisper");
    expect(invoke).toHaveBeenCalledWith("backend_set_config_value", {
      section: "stt",
      key: "engine",
      value: "whisper",
    });
  });

  it("setBackendConfigValue ошибка бекенда → исключение", async () => {
    invoke.mockResolvedValueOnce({ ok: false, error: "не редактируется из GUI" });
    await expect(setBackendConfigValue("llm", "provider", "evil")).rejects.toThrow(
      "не редактируется из GUI",
    );
  });

  it("listApiModels возвращает группы моделей или бросает ошибку", async () => {
    invoke.mockResolvedValueOnce({
      ok: true,
      groups: [{ provider: "openai", models: ["gpt-4o"] }],
    });
    const groups = await listApiModels({
      type: "openai",
      endpoint: "https://api.openai.com/v1",
      apiKey: "sk-...",
      model: "",
    });
    expect(groups[0].provider).toBe("openai");

    invoke.mockResolvedValueOnce({ ok: false, error: "Connection error" });
    await expect(
      listApiModels({
        type: "openai",
        endpoint: "https://bad-endpoint",
        apiKey: "",
        model: "",
      }),
    ).rejects.toThrow("Connection error");
  });

  it("listApiModels валидирует и фильтрует группы, исключая пустые и поврежденные", async () => {
    invoke.mockResolvedValueOnce({
      ok: true,
      groups: [
        { provider: "valid-provider", models: ["m1", "m2"] },
        { provider: "empty-models", models: [] },
        { provider: "null-models", models: null },
        { provider: "undefined-models" },
        null,
        "not-a-group",
      ],
    });
    const groups = await listApiModels({
      type: "openai",
      endpoint: "https://api.openai.com/v1",
      apiKey: "sk-...",
      model: "",
    });
    expect(groups).toHaveLength(1);
    expect(groups[0].provider).toBe("valid-provider");
    expect(groups[0].models).toEqual(["m1", "m2"]);
  });

  it("getVoiceMode and setVoiceMode interact with Tauri IPC and dispatch change event", async () => {
    invoke.mockResolvedValueOnce({ ok: true, voice_enabled: true });
    const enabled = await getVoiceMode();
    expect(invoke).toHaveBeenCalledWith("backend_get_voice_mode", undefined);
    expect(enabled).toBe(true);

    const dispatchSpy = vi.fn();
    (globalThis as unknown as { window?: { dispatchEvent: unknown } }).window = {
      dispatchEvent: dispatchSpy,
    };
    invoke.mockResolvedValueOnce({ ok: true, voice_enabled: false });
    const changed = await setVoiceMode(false);
    expect(invoke).toHaveBeenCalledWith("backend_set_voice_mode", { enabled: false });
    expect(changed).toBe(false);
    expect(dispatchSpy).toHaveBeenCalled();
  });
});