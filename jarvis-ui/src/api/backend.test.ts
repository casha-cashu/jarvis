import { beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...args: unknown[]) => invoke(...args) }));

import {
  clearBackendHistory,
  getBackendConfig,
  getBackendTimers,
  sendBackendMessage,
} from "./backend";

beforeEach(() => {
  invoke.mockReset();
});

describe("backend wrappers", () => {
  it("getBackendConfig возвращает config при ok", async () => {
    invoke.mockResolvedValue({
      ok: true,
      config: { stt: { engine: "whisper" }, tts: { engine: "piper" }, llm: { provider: "ollama", model: "qwen2.5:3b" } },
    });
    const cfg = await getBackendConfig();
    expect(cfg.stt.engine).toBe("whisper");
    expect(cfg.llm.model).toBe("qwen2.5:3b");
  });

  it("getBackendConfig пробрасывает ошибку бекенда", async () => {
    invoke.mockResolvedValue({ ok: false, error: "Конфиг невалиден" });
    await expect(getBackendConfig()).rejects.toThrow("Конфиг невалиден");
  });

  it("getBackendTimers ошибка → исключение с текстом", async () => {
    invoke.mockResolvedValue({ ok: false, error: "Таймеры недоступны" });
    await expect(getBackendTimers()).rejects.toThrow("Таймеры недоступны");
  });

  it("sendBackendMessage возвращает текст ответа", async () => {
    invoke.mockResolvedValue({ ok: true, text: "Готово, сэр." });
    await expect(sendBackendMessage("привет", "sess-1")).resolves.toBe("Готово, сэр.");
    expect(invoke).toHaveBeenCalledWith("backend_send_message", {
      message: "привет",
      session: "sess-1",
    });
  });

  it("sendBackendMessage без сессии шлёт null", async () => {
    invoke.mockResolvedValue({ ok: true, text: "ок" });
    await sendBackendMessage("тест");
    expect(invoke).toHaveBeenCalledWith("backend_send_message", {
      message: "тест",
      session: null,
    });
  });

  it("clearBackendHistory ошибка → исключение", async () => {
    invoke.mockResolvedValue({ ok: false, error: "нет бриджа" });
    await expect(clearBackendHistory()).rejects.toThrow("нет бриджа");
  });
});
