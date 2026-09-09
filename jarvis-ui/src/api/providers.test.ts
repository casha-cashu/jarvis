import { beforeEach, describe, expect, it } from "vitest";

// Минимальный localStorage: в node-окружении vitest его нет
const store = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  value: {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  },
  configurable: true,
});

// Mock window.dispatchEvent
const dispatchedEvents: Event[] = [];
Object.defineProperty(globalThis, "window", {
  value: {
    dispatchEvent: (e: Event) => {
      dispatchedEvents.push(e);
      return true;
    },
  },
  configurable: true,
});

import {
  addProvider,
  clearActiveModel,
  deleteProvider,
  getActiveModel,
  getProvider,
  isLocalProvider,
  loadProviders,
  setActiveModel,
  setProviders,
  updateProvider,
  type ProviderEntry,
} from "./providers";

const entry: Omit<ProviderEntry, "id"> = {
  name: "Ollama",
  type: "openai",
  endpoint: "http://localhost:11434/v1",
  apiKey: "key",
};

beforeEach(() => {
  store.clear();
  dispatchedEvents.length = 0;
});

describe("providers store and CRUD", () => {
  it("addProvider добавляет и сохраняет", () => {
    const next = addProvider(entry);
    expect(next).toHaveLength(1);
    expect(next[0].name).toBe("Ollama");
    expect(loadProviders()).toHaveLength(1);
  });

  it("updateProvider патчит по id", () => {
    const [p] = addProvider(entry);
    updateProvider(p.id, { name: "Мой Ollama" });
    expect(loadProviders()[0].name).toBe("Мой Ollama");
  });

  it("getProvider возвращает провайдера по id или null", () => {
    const [p] = addProvider(entry);
    expect(getProvider(p.id)).toEqual(p);
    expect(getProvider("nonexistent-id")).toBeNull();
  });

  it("deleteProvider удаляет и сбрасывает активную модель", () => {
    const [p] = addProvider(entry);
    setActiveModel(p.id, "qwen2.5:3b");
    expect(getActiveModel()).toEqual({ providerId: p.id, model: "qwen2.5:3b" });
    deleteProvider(p.id);
    expect(loadProviders()).toHaveLength(0);
    expect(getActiveModel()).toBeNull();
  });

  it("getActiveModel null для битого JSON", () => {
    store.set("jarvis.ui.active-model", "{broken");
    expect(getActiveModel()).toBeNull();
  });

  it("getActiveModel null для удалённого провайдера", () => {
    store.set("jarvis.ui.active-model", JSON.stringify({ providerId: "ghost", model: "m" }));
    expect(getActiveModel()).toBeNull();
  });

  it("clearActiveModel очищает выбор", () => {
    const [p] = addProvider(entry);
    setActiveModel(p.id, "m1");
    clearActiveModel();
    expect(getActiveModel()).toBeNull();
  });

  it("диспатчит jarvis:providers-changed при add, update, delete, setProviders", () => {
    dispatchedEvents.length = 0;
    const [p] = addProvider(entry);
    expect(dispatchedEvents.some((e) => e.type === "jarvis:providers-changed")).toBe(true);

    dispatchedEvents.length = 0;
    updateProvider(p.id, { name: "Ollama 2" });
    expect(dispatchedEvents.some((e) => e.type === "jarvis:providers-changed")).toBe(true);

    dispatchedEvents.length = 0;
    setProviders([p]);
    expect(dispatchedEvents.some((e) => e.type === "jarvis:providers-changed")).toBe(true);

    dispatchedEvents.length = 0;
    deleteProvider(p.id);
    expect(dispatchedEvents.some((e) => e.type === "jarvis:providers-changed")).toBe(true);
  });

  it("мигрирует старые пресеты из jarvis.ui.api-presets", () => {
    const legacy = [
      {
        id: "legacy-1",
        name: "Old Ollama",
        type: "openai" as const,
        endpoint: "http://127.0.0.1:11434/v1",
        apiKey: "",
      },
    ];
    store.set("jarvis.ui.api-presets", JSON.stringify(legacy));

    const loaded = loadProviders();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].id).toBe("legacy-1");
    expect(store.get("jarvis.ui.providers")).toBeDefined();
  });
});

describe("isLocalProvider", () => {
  it("определяет локальные провайдеры по URL и имени", () => {
    expect(isLocalProvider({ endpoint: "http://localhost:11434/v1" })).toBe(true);
    expect(isLocalProvider({ endpoint: "http://127.0.0.1:1234/v1" })).toBe(true);
    expect(isLocalProvider({ endpoint: "http://0.0.0.0:8000/v1" })).toBe(true);
    expect(isLocalProvider({ endpoint: "http://[::1]:11434/v1" })).toBe(true);
    expect(isLocalProvider({ name: "Ollama local", endpoint: "http://my-server:8000/v1" })).toBe(true);
    expect(isLocalProvider({ name: "LM Studio", endpoint: "http://remote:1234/v1" })).toBe(true);
    expect(isLocalProvider({ type: "ollama" })).toBe(true);
    expect(isLocalProvider({ type: "lmstudio" })).toBe(true);
    expect(isLocalProvider({ name: "OpenAI", endpoint: "https://api.openai.com/v1" })).toBe(false);
    expect(isLocalProvider({ name: "Anthropic", endpoint: "https://api.anthropic.com/v1" })).toBe(false);
  });
});
