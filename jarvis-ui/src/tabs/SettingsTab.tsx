import { useEffect, useState } from "react";
import { Check, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import {
  configureBackend,
  listApiModels,
  listMicrophones,
  setDefaultMicrophone,
  type MicrophoneDevice,
  type ModelGroup,
} from "../api/backend";
import {
  addProvider,
  deleteProvider,
  loadProviders,
  saveProviders,
  updateProvider,
  type ProviderEntry,
  type ProviderType,
} from "../api/providers";

type SettingSection = "llm" | "stt" | "tts" | "commands" | "general";

function hostOf(endpoint: string): string {
  try {
    return new URL(endpoint).host;
  } catch {
    return endpoint || "—";
  }
}

const emptyForm = { name: "", type: "openai" as ProviderType, endpoint: "", apiKey: "" };

export default function SettingsTab() {
  const [section, setSection] = useState<SettingSection>("llm");
  const [providers, setProviders] = useState<ProviderEntry[]>(loadProviders);
  const [editingId, setEditingId] = useState<string | null>(null); // null = add form closed
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkOk, setCheckOk] = useState<string | null>(null);
  // Флаги агента персистятся: changeModel в ChatTab читает их при
  // configureBackend — иначе смена модели тихо возвращала agent=true/auto
  // даже если пользователь выключил агента или выбрал strict.
  const [agentEnabled, setAgentEnabled] = useState(
    () => localStorage.getItem("jarvis.ui.agentEnabled") !== "0",
  );
  const [approvalMode, setApprovalMode] = useState<"auto" | "strict" | "yolo">(() => {
    const stored = localStorage.getItem("jarvis.ui.approvalMode");
    return stored === "strict" || stored === "yolo" ? stored : "auto";
  });
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [microphones, setMicrophones] = useState<MicrophoneDevice[]>([]);
  const [selectedMic, setSelectedMic] = useState("");
  const [wakeWord, setWakeWord] = useState("джарвис");

  useEffect(() => {
    listMicrophones().then((devices) => {
      setMicrophones(devices);
      setSelectedMic(devices.find((device) => device.isDefault)?.name ?? devices[0]?.name ?? "");
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    localStorage.setItem("jarvis.ui.agentEnabled", agentEnabled ? "1" : "0");
    localStorage.setItem("jarvis.ui.approvalMode", approvalMode);
  }, [agentEnabled, approvalMode]);

  const openAdd = () => {
    setEditingId("new");
    setForm(emptyForm);
    setFormError(null);
    setCheckOk(null);
  };

  const openEdit = (provider: ProviderEntry) => {
    setEditingId(provider.id);
    setForm({ name: provider.name, type: provider.type, endpoint: provider.endpoint, apiKey: provider.apiKey });
    setFormError(null);
    setCheckOk(null);
  };

  const closeForm = () => {
    setEditingId(null);
    setForm(emptyForm);
    setFormError(null);
    setCheckOk(null);
  };

  const validateForm = (): string | null => {
    if (!/^https?:\/\//i.test(form.endpoint.trim())) return "Endpoint должен начинаться с http:// или https://";
    if (!form.apiKey.trim()) return "Укажите API ключ (для ollama подойдёт любая строка)";
    return null;
  };

  /** Fetch models for the current form values — validates credentials too. */
  const checkForm = async (): Promise<ModelGroup[] | null> => {
    const error = validateForm();
    if (error) {
      setFormError(error);
      return null;
    }
    setChecking(true);
    setFormError(null);
    setCheckOk(null);
    try {
      const groups = await listApiModels({
        type: form.type,
        endpoint: form.endpoint.trim(),
        apiKey: form.apiKey.trim(),
        model: "",
        agentEnabled,
        approvalMode,
      });
      const total = groups.reduce((sum, g) => sum + g.models.length, 0);
      setCheckOk(`OK — доступно моделей: ${total}`);
      return groups;
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Не удалось получить модели");
      return null;
    } finally {
      setChecking(false);
    }
  };

  const saveProvider = async () => {
    const groups = await checkForm();
    if (!groups) return;
    const name = form.name.trim() || hostOf(form.endpoint.trim());
    if (editingId === "new") {
      setProviders(addProvider({ name, type: form.type, endpoint: form.endpoint.trim(), apiKey: form.apiKey.trim() }));
      setSavedNote(`Провайдер «${name}» добавлен`);
    } else if (editingId) {
      setProviders(updateProvider(editingId, { name, type: form.type, endpoint: form.endpoint.trim(), apiKey: form.apiKey.trim() }));
      setSavedNote(`Провайдер «${name}» обновлён`);
    }
    closeForm();
  };

  const handleDelete = (id: string) => {
    const entry = providers.find((p) => p.id === id);
    setProviders(deleteProvider(id));
    setSavedNote(entry ? `Провайдер «${entry.name}» удалён` : null);
  };

  return (
    <div className="flex h-full">
      {/* Section sidebar */}
      <div className="flex w-48 flex-col border-r border-border bg-surface py-2">
        {(
          [
            { id: "llm", label: "LLM" },
            { id: "stt", label: "STT" },
            { id: "tts", label: "TTS" },
            { id: "commands", label: "Команды" },
            { id: "general", label: "Общие" },
          ] as const
        ).map((s) => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`px-4 py-2 text-left text-sm transition-colors ${
              section === s.id
                ? "bg-surface-2 text-accent"
                : "text-text-muted hover:bg-surface-2/50 hover:text-text"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Form area */}
      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-xl">
          {section === "llm" && (
            <div className="flex flex-col gap-6">
              <h2 className="text-lg font-medium text-text">Провайдеры моделей</h2>

              <Field label="Список провайдеров" hint="Модели в чате группируются по этим провайдерам">
                {providers.length === 0 && (
                  <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">
                    Пока нет ни одного провайдера
                  </div>
                )}
                <div className="flex flex-col gap-1.5">
                  {providers.map((provider) => (
                    <div
                      key={provider.id}
                      className="flex items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2"
                    >
                      <div className="flex min-w-0 flex-1 flex-col text-left">
                        <span className="truncate text-sm text-text">{provider.name}</span>
                        <span className="truncate text-[11px] text-text-muted">
                          {provider.type === "openai" ? "OpenAI" : "Anthropic"} · {hostOf(provider.endpoint)}
                        </span>
                      </div>
                      <button
                        onClick={() => openEdit(provider)}
                        className="shrink-0 rounded p-1.5 text-text-muted hover:bg-surface hover:text-text"
                        title="Редактировать"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={() => handleDelete(provider.id)}
                        className="shrink-0 rounded p-1.5 text-text-muted hover:bg-surface hover:text-danger"
                        title={`Удалить «${provider.name}»`}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              </Field>

              {editingId === null && (
                <button
                  onClick={openAdd}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-border py-2.5 text-sm text-text-muted transition-colors hover:border-accent/50 hover:text-accent"
                >
                  <Plus size={14} />
                  Добавить провайдера
                </button>
              )}

              {/* Add/edit form */}
              {editingId !== null && (
                <div className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-medium text-text">
                      {editingId === "new" ? "Новый провайдер" : "Редактирование"}
                    </h3>
                    <button onClick={closeForm} className="rounded p-1 text-text-muted hover:text-text">
                      <X size={15} />
                    </button>
                  </div>
                  <Field label="Название" hint="Например: Ollama, xKiro. Пусто → из адреса">
                    <input
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      placeholder="Ollama"
                      className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text"
                    />
                  </Field>
                  <Field label="Тип API">
                    <select
                      value={form.type}
                      onChange={(e) => setForm({ ...form, type: e.target.value as ProviderType })}
                      className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text"
                    >
                      <option value="openai">OpenAI-compatible</option>
                      <option value="anthropic">Anthropic-compatible</option>
                    </select>
                  </Field>
                  <Field label="Endpoint">
                    <input
                      value={form.endpoint}
                      onChange={(e) => setForm({ ...form, endpoint: e.target.value })}
                      placeholder="http://localhost:11434/v1"
                      className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text"
                    />
                  </Field>
                  <Field label="API ключ" hint="Для локальной ollama подойдёт любая строка">
                    <input
                      type="password"
                      value={form.apiKey}
                      onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
                      placeholder="Ключ API"
                      className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text"
                    />
                  </Field>
                  {formError && <p className="text-xs text-danger">{formError}</p>}
                  {checkOk && <p className="text-xs text-accent">{checkOk}</p>}
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => void checkForm()}
                      disabled={checking}
                      className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs text-text-muted transition-colors hover:text-text disabled:opacity-50"
                    >
                      {checking
                        ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-current/30 border-t-current" />
                        : <RefreshCw size={12} />}
                      Проверить
                    </button>
                    <button
                      onClick={() => void saveProvider()}
                      disabled={checking}
                      className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white hover:brightness-110 disabled:opacity-50"
                    >
                      <Check size={12} />
                      Сохранить
                    </button>
                  </div>
                </div>
              )}

              {savedNote && <p className="text-xs text-accent">{savedNote}</p>}

              <Field label="Bash-агент" hint="Разрешить моделям выполнять команды (tools)">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
                  <input
                    type="checkbox"
                    checked={agentEnabled}
                    onChange={(e) => setAgentEnabled(e.target.checked)}
                    className="h-4 w-4 accent-[var(--color-accent)]"
                  />
                  Включить выполнение команд
                </label>
              </Field>

              <Field
                label="Режим одобрения bash-команд"
                hint="auto — спрашивать опасные | strict — все | yolo — без вопросов"
              >
                <select
                  value={approvalMode}
                  onChange={(e) => setApprovalMode(e.target.value as "auto" | "strict" | "yolo")}
                  className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                >
                  <option value="auto">Auto (рекомендуется)</option>
                  <option value="strict">Strict — подтверждать всё</option>
                  <option value="yolo">YOLO (опасно)</option>
                </select>
              </Field>
            </div>
          )}

          {section === "stt" && (
            <div className="flex flex-col gap-6">
              <h2 className="text-lg font-medium text-text">Настройки STT</h2>
              <Field label="Wake word" hint="Слово активации">
                <input
                  type="text"
                  value={wakeWord}
                  onChange={(e) => setWakeWord(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                />
              </Field>
              <Field label="Движок">
                <select className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none">
                  <option value="vosk">Vosk</option>
                  <option value="whisper">faster-whisper</option>
                </select>
              </Field>
              <Field label="Микрофон" hint="Системный источник PulseAudio/PipeWire">
                <select
                  value={selectedMic}
                  onChange={async (e) => {
                    const previous = selectedMic;
                    const next = e.target.value;
                    setSelectedMic(next);
                    // pactl может упасть — откатываем селект, чтобы он не
                    // показывал неприменённое устройство.
                    try {
                      await setDefaultMicrophone(next);
                    } catch {
                      setSelectedMic(previous);
                    }
                  }}
                  className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text"
                >
                  {microphones.length === 0 && <option value="">Микрофоны не найдены</option>}
                  {microphones.map((device) => (
                    <option key={device.name} value={device.name}>
                      {device.description}
                      {device.isDefault ? " (основной)" : ""}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          )}

          {section === "tts" && (
            <div className="flex flex-col gap-6">
              <h2 className="text-lg font-medium text-text">Настройки TTS</h2>
              <Field label="Движок">
                <select className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none">
                  <option value="piper">Piper (офлайн)</option>
                  <option value="gtts">gTTS (онлайн)</option>
                  <option value="speecht5">SpeechT5</option>
                </select>
              </Field>
            </div>
          )}

          {section === "commands" && (
            <div className="flex flex-col gap-4">
              <h2 className="text-lg font-medium text-text">Команды</h2>
              <p className="text-sm text-text-muted">
                Команды настраиваются в <code className="rounded bg-surface-2 px-1 py-0.5 text-xs">data/commands.json</code> и{" "}
                <code className="rounded bg-surface-2 px-1 py-0.5 text-xs">data/apps.json</code>
              </p>
              <div className="rounded-lg border border-border bg-surface p-4">
                <p className="text-xs text-text-muted">
                  Редактирование команд будет доступно здесь в следующей версии.
                </p>
              </div>
            </div>
          )}

          {section === "general" && (
            <div className="flex flex-col gap-6">
              <h2 className="text-lg font-medium text-text">Общие настройки</h2>
              <Field label="Язык">
                <select className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none">
                  <option value="ru">Русский</option>
                  <option value="en">English</option>
                </select>
              </Field>
              <Field label="Timeout выполнения (сек)">
                <input
                  type="number"
                  defaultValue={30}
                  className="w-24 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                />
              </Field>
            </div>
          )}

          {/* Save button (sticky) */}
          <div className="mt-8 flex justify-end gap-2 border-t border-border pt-4">
            <button className="rounded-lg px-4 py-2 text-sm text-text-muted hover:bg-surface-2">Отмена</button>
            <button
              onClick={() => {
                saveProviders(providers);
                void configureBackendIfPossible(providers, agentEnabled, approvalMode).then((note) => {
                  if (note) setSavedNote(note);
                });
              }}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              Применить
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Applies agent flags to backend if a model is already selected in chat. */
async function configureBackendIfPossible(
  providers: ProviderEntry[],
  agentEnabled: boolean,
  approvalMode: string,
): Promise<string | null> {
  try {
    const raw = localStorage.getItem("jarvis.ui.active-model");
    if (!raw) return null;
    const active = JSON.parse(raw) as { providerId: string; model: string };
    const provider = providers.find((p) => p.id === active.providerId);
    if (!provider || !active.model) return null;
    await configureBackend({
      type: provider.type,
      endpoint: provider.endpoint,
      apiKey: provider.apiKey,
      model: active.model,
      agentEnabled,
      approvalMode,
    });
    return `Применено: ${provider.name}/${active.model}`;
  } catch (err) {
    // Ошибка применения должна быть видна в savedNote, а не глотаться:
    // тихий null выглядел как успех при мёртвом bridge/неверном ключе.
    return err instanceof Error
      ? `Не применено: ${err.message}`
      : "Не применено: неизвестная ошибка";
  }
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-text">{label}</label>
      {children}
      {hint && <span className="text-xs text-text-muted">{hint}</span>}
    </div>
  );
}
