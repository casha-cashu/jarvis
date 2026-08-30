import { invoke } from "@tauri-apps/api/core";

export interface BackendStatus {
  running: boolean;
  connected: boolean;
}

export async function startBackend(): Promise<void> {
  await invoke("backend_start");
}

export async function stopBackend(): Promise<void> {
  await invoke("backend_stop");
}

export async function getBackendStatus(): Promise<BackendStatus> {
  return invoke<BackendStatus>("backend_status");
}

export interface ApiPresetConfig {
  type: "openai" | "anthropic";
  endpoint: string;
  apiKey: string;
  model: string;
  agentEnabled?: boolean;
  approvalMode?: string;
}

export interface MicrophoneDevice { name: string; description: string; isDefault: boolean; }
export interface SystemStats { uptimeSeconds: number; memoryUsedMb: number; memoryTotalMb: number; loadAverage: number; platform: string; }
export interface ModelGroup { provider: string; models: string[]; }
export interface BackendTimer { id: string; text: string; left: string; }

async function unwrap(response: { ok: boolean; error?: string }): Promise<void> {
  if (!response.ok) throw new Error(response.error ?? "Ошибка backend");
}

export async function configureBackend(config: ApiPresetConfig): Promise<void> {
  const response = await invoke<{ ok: boolean; error?: string }>("backend_configure", { config });
  await unwrap(response);
}

export async function listApiModels(config: ApiPresetConfig): Promise<ModelGroup[]> {
  const response = await invoke<{ ok: boolean; groups?: ModelGroup[]; error?: string }>("backend_list_models", { config });
  if (!response.ok) throw new Error(response.error ?? "Не удалось получить модели");
  return response.groups ?? [];
}

export async function getBackendTimers(): Promise<BackendTimer[]> {
  const response = await invoke<{ ok: boolean; timers?: BackendTimer[]; error?: string }>("backend_timers");
  if (!response.ok) throw new Error(response.error ?? "Таймеры недоступны");
  return response.timers ?? [];
}

export async function clearBackendHistory(): Promise<void> {
  const response = await invoke<{ ok: boolean; error?: string }>("backend_clear_history");
  await unwrap(response);
}

/** Aligns backend LLM context with the given UI chat session. */
export async function switchBackendSession(id: string): Promise<void> {
  const response = await invoke<{ ok: boolean; error?: string }>("backend_switch_session", { id });
  await unwrap(response);
}

/** Deletes a chat's archived LLM context (empties live memory if active). */
export async function deleteBackendSession(id: string): Promise<void> {
  const response = await invoke<{ ok: boolean; error?: string }>("backend_delete_session", { id });
  await unwrap(response);
}

/** Deletes a chat's archive AND its live LLM context — «память модели». */
export async function purgeBackendSession(id: string): Promise<void> {
  const response = await invoke<{ ok: boolean; error?: string }>("backend_purge_session", { id });
  await unwrap(response);
}

/** Deletes every archived chat + the live context. */
export async function purgeAllBackendSessions(): Promise<void> {
  const response = await invoke<{ ok: boolean; error?: string }>("backend_purge_all_sessions");
  await unwrap(response);
}

export interface BackendConfigInfo {
  stt: { engine?: string | null; wake_word?: string | null; phrase_time_limit?: number | null };
  tts: { engine?: string | null };
  llm: { provider?: string; model?: string | null };
}

/** Read-only snapshot of config.yaml for the settings screens. */
export async function getBackendConfig(): Promise<BackendConfigInfo> {
  const response = await invoke<{ ok: boolean; config?: BackendConfigInfo; error?: string }>(
    "backend_get_config",
  );
  if (!response.ok) throw new Error(response.error ?? "Конфиг недоступен");
  return response.config ?? { stt: {}, tts: {}, llm: {} };
}

/** Пишет одно значение в config.yaml (белый список ключей на бекенде).
 *  Применяется после перезапуска backend. */
export async function setBackendConfigValue(section: string, key: string, value: string): Promise<string> {
  const response = await invoke<{ ok: boolean; note?: string; error?: string }>(
    "backend_set_config_value",
    { section, key, value },
  );
  if (!response.ok) throw new Error(response.error ?? "Не удалось сохранить");
  return response.note ?? "Сохранено";
}

export async function listMicrophones(): Promise<MicrophoneDevice[]> { return invoke("list_microphones"); }
export async function setDefaultMicrophone(name: string): Promise<void> { await invoke("set_default_microphone", { name }); }
export async function getSystemStats(): Promise<SystemStats> { return invoke("system_stats"); }

export async function sendBackendMessage(message: string, sessionId?: string): Promise<string> {
  const response = await invoke<{ ok: boolean; text?: string; error?: string }>(
    "backend_send_message",
    { message, session: sessionId ?? null },
  );
  if (!response.ok) throw new Error(response.error ?? "Ошибка backend");
  return response.text ?? "";
}
