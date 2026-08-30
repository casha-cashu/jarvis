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

import {
  addProvider,
  clearActiveModel,
  deleteProvider,
  getActiveModel,
  loadProviders,
  setActiveModel,
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
});

describe("providers", () => {
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
});
