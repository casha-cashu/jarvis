export type ProviderType = "openai" | "anthropic";

/** A user-defined LLM provider endpoint (e.g. Ollama, xKiro, OpenRouter). */
export interface ProviderEntry {
  id: string;
  name: string; // display name, e.g. "Ollama"
  type: ProviderType;
  endpoint: string;
  apiKey: string;
}

/** Currently selected model = provider + model id pair. */
export interface ActiveModel {
  providerId: string;
  model: string;
}

const PROVIDERS_KEY = "jarvis.ui.providers";
const LEGACY_PRESETS_KEY = "jarvis.ui.api-presets";
const ACTIVE_KEY = "jarvis.ui.active-model";

export function loadProviders(): ProviderEntry[] {
  try {
    const raw = localStorage.getItem(PROVIDERS_KEY);
    if (raw !== null) {
      const parsed = JSON.parse(raw) as ProviderEntry[];
      if (Array.isArray(parsed)) return parsed;
    }
  } catch {
    /* fall through to migration */
  }
  // One-time migration: old presets become providers.
  try {
    const legacyRaw = localStorage.getItem(LEGACY_PRESETS_KEY);
    if (legacyRaw) {
      const legacy = JSON.parse(legacyRaw) as Array<{
        id: string;
        name: string;
        type: ProviderType;
        endpoint: string;
        apiKey: string;
      }>;
      const migrated: ProviderEntry[] = legacy.map((p) => ({
        id: p.id,
        name: p.name,
        type: p.type,
        endpoint: p.endpoint,
        apiKey: p.apiKey,
      }));
      if (migrated.length > 0) {
        localStorage.setItem(PROVIDERS_KEY, JSON.stringify(migrated));
        return migrated;
      }
    }
  } catch {
    /* ignore */
  }
  return [];
}

function notifyProvidersChanged(): void {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent("jarvis:providers-changed"));
  }
}

export function saveProviders(providers: ProviderEntry[]): void {
  localStorage.setItem(PROVIDERS_KEY, JSON.stringify(providers));
}

export function setProviders(providers: ProviderEntry[]): void {
  saveProviders(providers);
  notifyProvidersChanged();
}

export function addProvider(entry: Omit<ProviderEntry, "id">): ProviderEntry[] {
  const next = [...loadProviders(), { ...entry, id: crypto.randomUUID() }];
  saveProviders(next);
  notifyProvidersChanged();
  return next;
}

export function updateProvider(id: string, patch: Partial<ProviderEntry>): ProviderEntry[] {
  const next = loadProviders().map((p) => (p.id === id ? { ...p, ...patch } : p));
  saveProviders(next);
  notifyProvidersChanged();
  return next;
}

export function deleteProvider(id: string): ProviderEntry[] {
  const next = loadProviders().filter((p) => p.id !== id);
  saveProviders(next);
  const active = getActiveModel();
  if (active && active.providerId === id) clearActiveModel();
  notifyProvidersChanged();
  return next;
}

/** Checks whether a provider is a local service (Ollama, LM Studio, etc.) where API key is optional. */
export function isLocalProvider(provider: { endpoint?: string; name?: string; type?: string }): boolean {
  const ep = (provider.endpoint || "").toLowerCase();
  const name = (provider.name || "").toLowerCase();
  const type = (provider.type || "").toLowerCase();
  if (type === "ollama" || type === "lmstudio") return true;
  return (
    ep.includes("localhost") ||
    ep.includes("127.0.0.1") ||
    ep.includes("0.0.0.0") ||
    ep.includes("::1") ||
    ep.includes("ollama") ||
    ep.includes("lmstudio") ||
    ep.includes("lm-studio") ||
    name.includes("ollama") ||
    name.includes("lm studio") ||
    name.includes("lmstudio")
  );
}

export function getProvider(id: string): ProviderEntry | null {
  return loadProviders().find((p) => p.id === id) ?? null;
}

export function getActiveModel(): ActiveModel | null {
  try {
    const raw = localStorage.getItem(ACTIVE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ActiveModel;
    if (!parsed.providerId || !parsed.model) return null;
    return getProvider(parsed.providerId) ? parsed : null;
  } catch {
    return null;
  }
}

export function setActiveModel(providerId: string, model: string): void {
  localStorage.setItem(ACTIVE_KEY, JSON.stringify({ providerId, model } satisfies ActiveModel));
}

export function clearActiveModel(): void {
  localStorage.removeItem(ACTIVE_KEY);
}
