import { useEffect, useState } from "react";
import {
  Brain,
  Check,
  Globe,
  Mic,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Terminal,
  Trash2,
  Volume2,
  X,
  Save,
  Eye,
  EyeOff,
} from "lucide-react";
import {
  listApiModels,
  listMicrophones,
  setDefaultMicrophone,
  getBackendConfig,
  setBackendConfigValue,
  getScenarios,
  saveScenario,
  deleteScenario,
  getContinuousMode,
  setContinuousMode,
  restartBackend,
  getBackendStatus,
  DEFAULT_SYSTEM_PROMPT,
  type BackendConfigTree,
  type MicrophoneDevice,
  type ModelGroup,
  type ScenarioItem,
  type ScenarioAction,
} from "../api/backend";
import {
  addProvider,
  deleteProvider,
  loadProviders,
  updateProvider,
  type ProviderEntry,
  type ProviderType,
} from "../api/providers";

function clampNumber(val: unknown, min: number, max: number, fallback: number): number {
  const n = typeof val === "number" ? val : parseFloat(String(val));
  if (isNaN(n) || !isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function clampInt(val: unknown, min: number, max: number, fallback: number): number {
  const n = typeof val === "number" ? val : parseInt(String(val), 10);
  if (isNaN(n) || !isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(n)));
}

type SettingSection = "llm" | "stt" | "tts" | "commands" | "system";

function hostOf(endpoint: string): string {
  try {
    return new URL(endpoint).host;
  } catch {
    return endpoint || "—";
  }
}

const emptyForm = { name: "", type: "openai" as ProviderType, endpoint: "", apiKey: "" };

export default function SettingsTab() {
  const [section, setSection] = useState<SettingSection>(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const sec = params.get("section") as SettingSection;
      if (["llm", "stt", "tts", "commands", "system"].includes(sec)) return sec;
    }
    return "llm";
  });

  const [providers, setProviders] = useState<ProviderEntry[]>(loadProviders);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkOk, setCheckOk] = useState<string | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);

  // Agent state
  const [agentEnabled, setAgentEnabled] = useState(
    () => localStorage.getItem("jarvis.ui.agentEnabled") !== "0",
  );
  const [approvalMode, setApprovalMode] = useState<"auto" | "strict" | "yolo">(() => {
    const stored = localStorage.getItem("jarvis.ui.approvalMode");
    return stored === "strict" || stored === "yolo" ? stored : "auto";
  });
  const [agentMaxIterations, setAgentMaxIterations] = useState(5);

  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [microphones, setMicrophones] = useState<MicrophoneDevice[]>([]);
  const [selectedMic, setSelectedMic] = useState("");

  // Full config state
  const [cfg, setCfg] = useState<BackendConfigTree>({});

  // Controlled UI states for tricky inputs
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT);
  const [vadThreshold, setVadThreshold] = useState(0.5);
  const [fuzzyThreshold, setFuzzyThreshold] = useState(0.8);
  const [useTemperature, setUseTemperature] = useState(true);
  const [temperatureVal, setTemperatureVal] = useState(0.7);
  const [useMaxTokens, setUseMaxTokens] = useState(false);
  const [maxTokensVal, setMaxTokensVal] = useState(4096);

  // Status & action loading
  const [restarting, setRestarting] = useState(false);

  // Scenarios state
  const [scenarios, setScenarios] = useState<Record<string, ScenarioItem>>({});
  const [editingScenarioId, setEditingScenarioId] = useState<string | null>(null);
  const [scenarioForm, setScenarioForm] = useState<ScenarioItem>({
    name: "",
    description: "",
    phrases: [],
    actions: [],
  });
  const [scenarioPhrasesInput, setScenarioPhrasesInput] = useState("");

  // Continuous listening
  const [continuous, setContinuous] = useState(false);

  const reloadConfig = () => {
    getBackendConfig()
      .then((data) => {
        setCfg(data);
        if (data.llm?.system_prompt !== undefined) {
          setSystemPrompt(data.llm.system_prompt ?? DEFAULT_SYSTEM_PROMPT);
        }
        if (data.llm?.agent_max_iterations !== undefined) {
          setAgentMaxIterations(data.llm.agent_max_iterations);
        }
        if (data.llm?.temperature !== undefined) {
          setUseTemperature(data.llm.temperature !== null);
          if (data.llm.temperature !== null) setTemperatureVal(data.llm.temperature);
        }
        if (data.llm?.max_tokens !== undefined) {
          setUseMaxTokens(data.llm.max_tokens !== null);
          if (data.llm.max_tokens !== null) setMaxTokensVal(data.llm.max_tokens);
        }
        if (data.vad?.silero?.threshold !== undefined) {
          setVadThreshold(data.vad.silero.threshold);
        }
        if (data.commands?.fuzzy_threshold !== undefined) {
          setFuzzyThreshold(data.commands.fuzzy_threshold);
        }
        if (data.stt?.continuous !== undefined) {
          setContinuous(Boolean(data.stt.continuous));
        }
      })
      .catch(() => undefined);
  };

  const reloadScenarios = () => {
    getScenarios().then(setScenarios).catch(() => undefined);
  };

  useEffect(() => {
    listMicrophones()
      .then((devices) => {
        setMicrophones(devices);
        setSelectedMic(devices.find((device) => device.isDefault)?.name ?? devices[0]?.name ?? "");
      })
      .catch(() => undefined);

    reloadConfig();
    reloadScenarios();

    getContinuousMode().then(setContinuous).catch(() => undefined);

    const onContinuousChange = (e: Event) => {
      const custom = e as CustomEvent<boolean>;
      if (typeof custom.detail === "boolean") {
        setContinuous(custom.detail);
      }
    };
    window.addEventListener("jarvis:continuous-change", onContinuousChange);
    return () => window.removeEventListener("jarvis:continuous-change", onContinuousChange);
  }, []);

  const showNote = (text: string) => {
    setSavedNote(text);
    setTimeout(() => setSavedNote(null), 3500);
  };

  const handleSaveConfigKey = async (sec: string, key: string, val: unknown) => {
    try {
      const note = await setBackendConfigValue(sec, key, val);
      showNote(note);
      reloadConfig();
    } catch (err) {
      showNote(err instanceof Error ? err.message : "Ошибка сохранения");
    }
  };

  const handleToggleContinuous = async (next: boolean) => {
    setContinuous(next);
    try {
      await setContinuousMode(next, true);
      showNote(next ? "Режим непрерывного диалога включён" : "Режим диалога выключен (по фразе)");
    } catch {
      setContinuous(!next);
    }
  };

  const handleRestartBackend = async () => {
    setRestarting(true);
    try {
      await restartBackend();
      showNote("Сервис JARVIS успешно перезапущен");
      await getBackendStatus();
    } catch (err) {
      showNote(err instanceof Error ? err.message : "Не удалось перезапустить сервис");
    } finally {
      setRestarting(false);
    }
  };

  // Provider CRUD
  const handleOpenAdd = () => {
    setEditingId("__new__");
    setForm(emptyForm);
    setFormError(null);
    setCheckOk(null);
    setShowApiKey(false);
  };

  const handleOpenEdit = (p: ProviderEntry) => {
    setEditingId(p.id);
    setForm({ name: p.name, type: p.type, endpoint: p.endpoint, apiKey: p.apiKey });
    setFormError(null);
    setCheckOk(null);
    setShowApiKey(false);
  };

  const handleCloseForm = () => {
    setEditingId(null);
    setForm(emptyForm);
    setFormError(null);
    setCheckOk(null);
    setShowApiKey(false);
  };

  const handleCheckConnection = async () => {
    setChecking(true);
    setFormError(null);
    setCheckOk(null);

    const ep = form.endpoint.trim();
    if (!ep) {
      setFormError("Укажите URL эндпоинта");
      setChecking(false);
      return;
    }

    try {
      const u = new URL(ep);
      if (!u.protocol.startsWith("http")) {
        throw new Error();
      }
    } catch {
      setFormError("Некорректный URL эндпоинта (должен начинаться с http:// или https://)");
      setChecking(false);
      return;
    }

    try {
      const groups: ModelGroup[] = await listApiModels({
        type: form.type,
        endpoint: ep,
        apiKey: form.apiKey.trim(),
        model: "",
      });
      const total = groups.reduce((acc, g) => acc + g.models.length, 0);
      setCheckOk(`Связь установлена (${total} моделей найдено)`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Ошибка подключения");
    } finally {
      setChecking(false);
    }
  };

  const handleSaveProvider = () => {
    if (!form.name.trim()) {
      setFormError("Укажите название провайдера");
      return;
    }
    if (!form.endpoint.trim()) {
      setFormError("Укажите URL эндпоинта");
      return;
    }
    try {
      const u = new URL(form.endpoint.trim());
      if (!u.protocol.startsWith("http")) throw new Error();
    } catch {
      setFormError("Некорректный URL эндпоинта (должен начинаться с http:// или https://)");
      return;
    }

    if (editingId === "__new__") {
      addProvider({
        name: form.name.trim(),
        type: form.type,
        endpoint: form.endpoint.trim(),
        apiKey: form.apiKey.trim(),
      });
      setProviders(loadProviders());
      handleCloseForm();
      showNote(`Провайдер «${form.name.trim()}» добавлен`);
    } else if (editingId) {
      updateProvider(editingId, {
        name: form.name.trim(),
        type: form.type,
        endpoint: form.endpoint.trim(),
        apiKey: form.apiKey.trim(),
      });
      setProviders(loadProviders());
      handleCloseForm();
      showNote("Провайдер обновлён");
    }
  };

  const handleDeleteProvider = (id: string, name: string) => {
    deleteProvider(id);
    setProviders(loadProviders());
    if (editingId === id) handleCloseForm();
    showNote(`Провайдер «${name}» удалён`);
  };

  // Scenario CRUD
  const handleOpenNewScenario = () => {
    setEditingScenarioId("__new__");
    setScenarioForm({
      name: "",
      description: "",
      phrases: [],
      actions: [{ type: "speak", text: "Слушаю вас" }],
    });
    setScenarioPhrasesInput("");
  };

  const handleOpenEditScenario = (id: string, item: ScenarioItem) => {
    setEditingScenarioId(id);
    setScenarioForm({ ...item, actions: [...item.actions] });
    setScenarioPhrasesInput((item.phrases ?? []).join(", "));
  };

  const handleSaveScenarioSubmit = async () => {
    if (!scenarioForm.name.trim()) {
      showNote("Укажите название сценария");
      return;
    }
    const id = (editingScenarioId === "__new__" ? scenarioForm.name : editingScenarioId)
      ?.toLowerCase()
      .trim();
    if (!id) return;

    const phrases = scenarioPhrasesInput
      .split(",")
      .map((p) => p.trim().toLowerCase())
      .filter(Boolean);

    const payload: ScenarioItem = {
      ...scenarioForm,
      phrases: phrases.length > 0 ? phrases : [id],
    };

    try {
      await saveScenario(id, payload);
      showNote(`Сценарий «${payload.name}» сохранён`);
      setEditingScenarioId(null);
      reloadScenarios();
    } catch (err) {
      showNote(err instanceof Error ? err.message : "Ошибка сохранения сценария");
    }
  };

  const handleDeleteScenarioSubmit = async (id: string) => {
    try {
      await deleteScenario(id);
      showNote(`Сценарий «${id}» удалён`);
      if (editingScenarioId === id) setEditingScenarioId(null);
      reloadScenarios();
    } catch (err) {
      showNote(err instanceof Error ? err.message : "Ошибка удаления");
    }
  };

  const handleAddAction = () => {
    setScenarioForm((prev) => ({
      ...prev,
      actions: [...prev.actions, { type: "speak", text: "" }],
    }));
  };

  const handleRemoveAction = (idx: number) => {
    setScenarioForm((prev) => ({
      ...prev,
      actions: prev.actions.filter((_, i) => i !== idx),
    }));
  };

  const handleActionChange = (idx: number, patch: Partial<ScenarioAction>) => {
    setScenarioForm((prev) => ({
      ...prev,
      actions: prev.actions.map((act, i) => (i === idx ? { ...act, ...patch } : act)),
    }));
  };

  // Helper for numeric input restriction
  const handleDigitOnlyKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.ctrlKey || e.metaKey) return;
    if (["Backspace", "Delete", "ArrowLeft", "ArrowRight", "Tab", "Enter"].includes(e.key)) {
      return;
    }
    if (!/^[0-9]$/.test(e.key)) {
      e.preventDefault();
    }
  };

  const handleDecimalKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.ctrlKey || e.metaKey) return;
    if (["Backspace", "Delete", "ArrowLeft", "ArrowRight", "Tab", "Enter"].includes(e.key)) {
      return;
    }
    if ((e.key === "." || e.key === ",") && !e.currentTarget.value.includes(".") && !e.currentTarget.value.includes(",")) {
      return;
    }
    if (!/^[0-9]$/.test(e.key)) {
      e.preventDefault();
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Toast notification */}
      {savedNote && (
        <div className="fixed bottom-4 right-4 z-50 rounded-lg border border-accent/40 bg-surface px-4 py-2.5 text-xs text-text shadow-xl animate-fade-in flex items-center gap-2">
          <Check size={14} className="text-accent" />
          <span>{savedNote}</span>
        </div>
      )}

      {/* Settings Tab Navigation */}
      <div className="flex border-b border-border bg-surface px-6 pt-3 gap-6 overflow-x-auto select-none">
        <button
          onClick={() => setSection("llm")}
          className={`flex items-center gap-2 pb-3 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
            section === "llm" ? "border-accent text-accent" : "border-transparent text-text-muted hover:text-text"
          }`}
        >
          <Brain size={15} />
          LLM & Агент
        </button>
        <button
          onClick={() => setSection("stt")}
          className={`flex items-center gap-2 pb-3 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
            section === "stt" ? "border-accent text-accent" : "border-transparent text-text-muted hover:text-text"
          }`}
        >
          <Mic size={15} />
          Аудио & STT
        </button>
        <button
          onClick={() => setSection("tts")}
          className={`flex items-center gap-2 pb-3 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
            section === "tts" ? "border-accent text-accent" : "border-transparent text-text-muted hover:text-text"
          }`}
        >
          <Volume2 size={15} />
          Озвучка & VAD
        </button>
        <button
          onClick={() => setSection("commands")}
          className={`flex items-center gap-2 pb-3 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
            section === "commands" ? "border-accent text-accent" : "border-transparent text-text-muted hover:text-text"
          }`}
        >
          <Terminal size={15} />
          Команды & Сценарии
        </button>
        <button
          onClick={() => setSection("system")}
          className={`flex items-center gap-2 pb-3 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
            section === "system" ? "border-accent text-accent" : "border-transparent text-text-muted hover:text-text"
          }`}
        >
          <Globe size={15} />
          Система, Поиск & Telegram
        </button>
      </div>

      {/* Main Content Area */}
      <div
        key={Object.keys(cfg).length > 0 ? "cfg-loaded" : "cfg-loading"}
        className="flex-1 overflow-y-auto px-6 py-6"
      >
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">

          {/* ── 1. LLM & АГЕНТ ─────────────────────────────────────────────── */}
          {section === "llm" && (
            <div className="flex flex-col gap-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-medium text-text">Провайдеры языковых моделей</h2>
                  <p className="text-xs text-text-muted">
                    Поддерживаются два протокола API: OpenAI-совместимый и Anthropic
                  </p>
                </div>
                <button
                  onClick={handleOpenAdd}
                  className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:brightness-110"
                >
                  <Plus size={13} />
                  Добавить
                </button>
              </div>

              {/* Provider Add/Edit Form */}
              {editingId && (
                <div className="rounded-xl border border-border bg-surface p-4 flex flex-col gap-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-text">
                      {editingId === "__new__" ? "Новый провайдер" : "Редактировать провайдера"}
                    </span>
                    <button onClick={handleCloseForm} className="text-text-muted hover:text-text">
                      <X size={15} />
                    </button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <Field label="Название">
                      <input
                        type="text"
                        value={form.name}
                        onChange={(e) => setForm({ ...form, name: e.target.value })}
                        placeholder="Например: Мой сервер LLM"
                        className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                      />
                    </Field>
                    <Field label="Тип эндпоинта">
                      <select
                        value={form.type}
                        onChange={(e) => setForm({ ...form, type: e.target.value as ProviderType })}
                        className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                      >
                        <option value="openai">OpenAI-совместимый API (/v1/chat/completions)</option>
                        <option value="anthropic">Anthropic API (/v1/messages)</option>
                      </select>
                    </Field>
                    <Field label="URL эндпоинта">
                      <input
                        type="text"
                        value={form.endpoint}
                        onChange={(e) => setForm({ ...form, endpoint: e.target.value })}
                        placeholder="http://localhost:11434/v1 или https://api.openai.com/v1"
                        className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                      />
                    </Field>
                    <Field label="API Key">
                      <div className="relative flex items-center">
                        <input
                          type={showApiKey ? "text" : "password"}
                          value={form.apiKey}
                          onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
                          placeholder="Оставьте пустым при отсутствии авторизации"
                          className="w-full rounded-lg border border-border bg-surface-2 pl-3 pr-9 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                        />
                        <button
                          type="button"
                          onClick={() => setShowApiKey((v) => !v)}
                          className="absolute right-2.5 text-text-muted hover:text-text"
                          title={showApiKey ? "Скрыть ключ" : "Показать ключ"}
                        >
                          {showApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
                        </button>
                      </div>
                    </Field>
                  </div>
                  {formError && <p className="text-xs text-danger">{formError}</p>}
                  {checkOk && <p className="text-xs text-emerald-500">{checkOk}</p>}
                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={handleCheckConnection}
                      disabled={checking}
                      className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs text-text-muted hover:text-text disabled:opacity-50"
                    >
                      <RefreshCw size={12} className={checking ? "animate-spin" : ""} />
                      Проверить связь
                    </button>
                    <button
                      type="button"
                      onClick={handleSaveProvider}
                      className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-white hover:brightness-110"
                    >
                      Сохранить
                    </button>
                  </div>
                </div>
              )}

              {/* Provider List */}
              <div className="flex flex-col gap-2">
                {providers.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3"
                  >
                    <div>
                      <p className="text-sm font-semibold text-text">{p.name}</p>
                      <p className="text-xs text-text-muted">
                        {p.type === "anthropic" ? "Anthropic API" : "OpenAI-совместимый"} · {hostOf(p.endpoint)}
                      </p>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleOpenEdit(p)}
                        className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
                        title="Редактировать"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => handleDeleteProvider(p.id, p.name)}
                        className="rounded p-1.5 text-text-muted hover:bg-danger/10 hover:text-danger"
                        title="Удалить"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* System Prompt & Reset Button */}
              <div className="flex flex-col gap-4 border-t border-border pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-text">Системный промпт ассистента</h3>
                    <p className="text-xs text-text-muted">Задаёт роль, правила общения и безопасность</p>
                  </div>
                  <button
                    onClick={() => {
                      setSystemPrompt(DEFAULT_SYSTEM_PROMPT);
                      handleSaveConfigKey("llm", "system_prompt", DEFAULT_SYSTEM_PROMPT);
                      showNote("Системный промпт сброшен к заводскому шаблону");
                    }}
                    className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2.5 py-1 text-xs text-text-muted hover:text-text transition-colors"
                    title="Сбросить промпт к проверенному шаблону по умолчанию"
                  >
                    <RotateCcw size={12} />
                    Сбросить по умолчанию
                  </button>
                </div>

                <textarea
                  rows={6}
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  onBlur={() => handleSaveConfigKey("llm", "system_prompt", systemPrompt)}
                  className="rounded-lg border border-border bg-surface px-3 py-2 text-xs font-mono leading-relaxed text-text focus:outline-none focus:border-accent"
                />
              </div>

              {/* API Request Hyperparameters (with disabling toggles) */}
              <div className="flex flex-col gap-4 border-t border-border pt-6">
                <h3 className="text-sm font-semibold text-text">Параметры API-запросов (Гиперпараметры)</h3>
                <p className="text-xs text-text-muted">
                  Вы можете отключать параметры, если выбранная модель или эндпоинт их не поддерживает (например, reasoning-модели)
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Temperature block with toggle */}
                  <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-text">Передавать температуру (temperature)</span>
                      <input
                        type="checkbox"
                        checked={useTemperature}
                        onChange={(e) => {
                          const next = e.target.checked;
                          setUseTemperature(next);
                          handleSaveConfigKey("llm", "temperature", next ? temperatureVal : null);
                        }}
                        className="h-4 w-4 rounded text-accent focus:ring-accent"
                      />
                    </div>
                    {useTemperature ? (
                      <div className="flex flex-col gap-1.5 pt-1">
                        <div className="flex items-center justify-between text-xs text-text-muted">
                          <span>Значение: {temperatureVal.toFixed(2)}</span>
                          <span>(0.0 — точность, 1.0+ — креативность)</span>
                        </div>
                        <input
                          type="range"
                          min="0"
                          max="2"
                          step="0.05"
                          value={temperatureVal}
                          onChange={(e) => setTemperatureVal(parseFloat(e.target.value))}
                          onMouseUp={() => {
                            const clamped = clampNumber(temperatureVal, 0.0, 2.0, 0.7);
                            setTemperatureVal(clamped);
                            handleSaveConfigKey("llm", "temperature", clamped);
                          }}
                          onTouchEnd={() => {
                            const clamped = clampNumber(temperatureVal, 0.0, 2.0, 0.7);
                            setTemperatureVal(clamped);
                            handleSaveConfigKey("llm", "temperature", clamped);
                          }}
                          onBlur={() => {
                            const clamped = clampNumber(temperatureVal, 0.0, 2.0, 0.7);
                            setTemperatureVal(clamped);
                            handleSaveConfigKey("llm", "temperature", clamped);
                          }}
                          className="w-full accent-accent"
                        />
                      </div>
                    ) : (
                      <p className="text-[11px] text-text-muted">Параметр отключён и не передаётся в API</p>
                    )}
                  </div>

                  {/* Max tokens block with toggle */}
                  <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-text">Ограничивать макс. токенов (max_tokens)</span>
                      <input
                        type="checkbox"
                        checked={useMaxTokens}
                        onChange={(e) => {
                          const next = e.target.checked;
                          setUseMaxTokens(next);
                          handleSaveConfigKey("llm", "max_tokens", next ? maxTokensVal : null);
                        }}
                        className="h-4 w-4 rounded text-accent focus:ring-accent"
                      />
                    </div>
                    {useMaxTokens ? (
                      <div className="flex flex-col gap-1.5 pt-1">
                        <input
                          type="number"
                          min="1"
                          max="32768"
                          value={maxTokensVal}
                          onKeyDown={handleDigitOnlyKeyDown}
                          onChange={(e) => {
                            const v = parseInt(e.target.value, 10);
                            setMaxTokensVal(isNaN(v) ? 0 : v);
                          }}
                          onBlur={() => {
                            const clamped = clampInt(maxTokensVal, 1, 32768, 4096);
                            setMaxTokensVal(clamped);
                            handleSaveConfigKey("llm", "max_tokens", clamped);
                          }}
                          className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs text-text focus:outline-none focus:border-accent"
                        />
                      </div>
                    ) : (
                      <p className="text-[11px] text-text-muted">Без принудительного лимита (по умолчанию провайдера)</p>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label="Глубина истории (реплик)" hint="Количество сообщений, сохраняемых в контексте">
                    <input
                      type="number"
                      min={2}
                      max={100}
                      defaultValue={cfg.llm?.max_history ?? 20}
                      onKeyDown={handleDigitOnlyKeyDown}
                      onBlur={(e) => {
                        const clamped = clampInt(e.target.value, 2, 100, 20);
                        e.target.value = String(clamped);
                        handleSaveConfigKey("llm", "max_history", clamped);
                      }}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                </div>
              </div>

              {/* Automation Agent Parameters */}
              <div className="flex flex-col gap-4 border-t border-border pt-6">
                <h3 className="text-sm font-semibold text-text">Автоматизация и Bash-агент</h3>
                <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
                  <div>
                    <p className="text-sm font-medium text-text">Разрешить выполнение действий агентом</p>
                    <p className="text-xs text-text-muted">
                      Позволяет Джарвису выполнять bash-команды, скрипты, читать файлы и искать в сети
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={agentEnabled}
                    onChange={(e) => {
                      setAgentEnabled(e.target.checked);
                      localStorage.setItem("jarvis.ui.agentEnabled", e.target.checked ? "1" : "0");
                      handleSaveConfigKey("llm", "agent_enabled", e.target.checked);
                    }}
                    className="h-4 w-4 rounded text-accent focus:ring-accent"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label="Уровень безопасности (Approval Mode)">
                    <select
                      value={approvalMode}
                      onChange={(e) => {
                        const m = e.target.value as "auto" | "strict" | "yolo";
                        setApprovalMode(m);
                        localStorage.setItem("jarvis.ui.approvalMode", m);
                        handleSaveConfigKey("llm", "agent_approval_mode", m);
                      }}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    >
                      <option value="auto">Auto (блокирует опасные, разрешает безопасные действия)</option>
                      <option value="strict">Strict (запрашивает подтверждение на каждое действие)</option>
                      <option value="yolo">YOLO (максимальная автономия в рамках белого списка)</option>
                    </select>
                  </Field>
                  <Field label="Максимум шагов агента за запрос">
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={agentMaxIterations}
                      onKeyDown={handleDigitOnlyKeyDown}
                      onChange={(e) => {
                        const v = parseInt(e.target.value, 10);
                        setAgentMaxIterations(isNaN(v) ? 0 : v);
                      }}
                      onBlur={() => {
                        const clamped = clampInt(agentMaxIterations, 1, 30, 5);
                        setAgentMaxIterations(clamped);
                        handleSaveConfigKey("llm", "agent_max_iterations", clamped);
                      }}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                </div>
              </div>
            </div>
          )}

          {/* ── 2. АУДИО & STT ─────────────────────────────────────────────── */}
          {section === "stt" && (
            <div className="flex flex-col gap-6">
              <div>
                <h2 className="text-lg font-medium text-text">Распознавание речи и микрофон</h2>
                <p className="text-xs text-text-muted">
                  Настройка аудиоустройств ввода, движка STT и параметров распознавания
                </p>
              </div>

              <div className="flex flex-col gap-4">
                <Field label="Входной микрофон">
                  <select
                    value={selectedMic}
                    onChange={async (e) => {
                      const name = e.target.value;
                      setSelectedMic(name);
                      try {
                        await setDefaultMicrophone(name);
                        await handleSaveConfigKey("audio.microphone", "device_name", name);
                      } catch {
                        /* ignore */
                      }
                    }}
                    className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:border-accent"
                  >
                    {microphones.map((d, index) => (
                      <option key={`${d.name}-${index}`} value={d.name}>
                        {d.description} {d.isDefault ? "(по умолчанию)" : ""}
                      </option>
                    ))}
                  </select>
                </Field>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label="Движок распознавания речи (STT)">
                    <select
                      value={cfg.stt?.engine ?? "whisper"}
                      onChange={(e) => handleSaveConfigKey("stt", "engine", e.target.value)}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    >
                      <option value="whisper">faster-whisper (высокая точность)</option>
                      <option value="vosk">Vosk (быстрый оффлайн-движок)</option>
                    </select>
                  </Field>

                  {/* Model size selector: depends on whether whisper or vosk is chosen */}
                  {(cfg.stt?.engine ?? "whisper") === "whisper" ? (
                    <Field label="Размер модели Whisper">
                      <select
                        value={cfg.stt?.whisper?.model_size ?? "tiny"}
                        onChange={(e) => handleSaveConfigKey("stt.whisper", "model_size", e.target.value)}
                        className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                      >
                        <option value="tiny">tiny (~75 МБ, сверхбыстрая)</option>
                        <option value="base">base (~140 МБ, базовая)</option>
                        <option value="small">small (~460 МБ, сбалансированная)</option>
                        <option value="medium">medium (~1.5 ГБ, профессиональная)</option>
                        <option value="turbo">turbo (~1.6 ГБ, ускоренная v3)</option>
                        <option value="large-v3">large-v3 (~3.1 ГБ, максимальное качество)</option>
                      </select>
                    </Field>
                  ) : (
                    <Field label="Размер модели Vosk">
                      <select
                        value={cfg.stt?.vosk?.model_size ?? "small-ru"}
                        onChange={(e) => handleSaveConfigKey("stt.vosk", "model_size", e.target.value)}
                        className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                      >
                        <option value="small-ru">small-ru (~45 МБ, легковесная оффлайн)</option>
                        <option value="ru">ru (~1.5 ГБ, стандартная русская)</option>
                        <option value="large-ru">large-ru (~2.5 ГБ, максимальный словарь)</option>
                      </select>
                    </Field>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label="Слово активации (Wake Word)">
                    <input
                      type="text"
                      defaultValue={cfg.stt?.wake_word ?? "джарвис"}
                      onBlur={(e) => handleSaveConfigKey("stt", "wake_word", e.target.value.toLowerCase().trim())}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>

                  <Field label="Частота дискретизации">
                    <select
                      value={cfg.audio?.microphone?.sample_rate ?? 16000}
                      onChange={(e) => handleSaveConfigKey("audio.microphone", "sample_rate", parseInt(e.target.value, 10))}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    >
                      <option value={16000}>16 000 Гц (рекомендуется для STT)</option>
                      <option value={44100}>44 100 Гц (CD качество)</option>
                      <option value={48000}>48 000 Гц (студийное)</option>
                    </select>
                  </Field>
                </div>

                {/* Continuous Listening Toggle */}
                <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
                  <div>
                    <p className="text-sm font-medium text-text">Режим постоянной прослушки (Continuous listening)</p>
                    <p className="text-xs text-text-muted">
                      Активирует режим непрерывного диалога (не нужно произносить «Джарвис» перед каждым вопросом)
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={continuous}
                    onChange={(e) => handleToggleContinuous(e.target.checked)}
                    className="h-4 w-4 rounded text-accent focus:ring-accent"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label="Макс. длительность фразы (сек)">
                    <input
                      type="number"
                      min={3}
                      max={30}
                      onKeyDown={handleDigitOnlyKeyDown}
                      defaultValue={cfg.stt?.phrase_time_limit ?? 10}
                      onBlur={(e) => {
                        const clamped = clampInt(e.target.value, 3, 30, 10);
                        e.target.value = String(clamped);
                        handleSaveConfigKey("stt", "phrase_time_limit", clamped);
                      }}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                  <Field label="Порог тишины для завершения (сек)">
                    <input
                      type="number"
                      step="0.1"
                      min="0.3"
                      max="3.0"
                      onKeyDown={handleDecimalKeyDown}
                      defaultValue={cfg.stt?.silence_threshold ?? 1.0}
                      onBlur={(e) => {
                        const clamped = clampNumber(e.target.value, 0.3, 3.0, 1.0);
                        e.target.value = String(clamped);
                        handleSaveConfigKey("stt", "silence_threshold", clamped);
                      }}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                </div>
              </div>
            </div>
          )}

          {/* ── 3. ОЗВУЧКА & VAD ───────────────────────────────────────────── */}
          {section === "tts" && (
            <div className="flex flex-col gap-6">
              <div>
                <h2 className="text-lg font-medium text-text">Синтез речи (TTS) и детектор активности (VAD)</h2>
                <p className="text-xs text-text-muted">
                  Настройка голоса ответов, скорости синтеза и чувствительности микрофона
                </p>
              </div>

              <div className="flex flex-col gap-4">
                <Field label="Движок синтеза речи (TTS)">
                  <select
                    value={cfg.tts?.engine ?? "piper"}
                    onChange={(e) => handleSaveConfigKey("tts", "engine", e.target.value)}
                    className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:border-accent"
                  >
                    <option value="piper">Piper — быстрый локальный нейросетевой синтез (оффлайн)</option>
                    <option value="gtts">Google TTS — облачный синтез речи (требует интернет)</option>
                    <option value="speecht5">SpeechT5 — локальная нейросетевая модель (Hugging Face)</option>
                  </select>
                </Field>

                {/* Engine-specific TTS settings */}
                {(cfg.tts?.engine ?? "piper") === "piper" && (
                  <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
                    <p className="text-xs text-text-muted">
                      Piper — быстрый локальный нейросетевой синтез речи. Работает оффлайн, обеспечивает естественное русское произношение.
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                      <Field label="Скорость речи Piper (length_scale)" hint="1.0 — нормальная, 0.8 — быстрее, 1.2 — медленнее">
                        <input
                          type="number"
                          step="0.05"
                          min="0.5"
                          max="2.0"
                          onKeyDown={handleDecimalKeyDown}
                          defaultValue={cfg.tts?.piper?.length_scale ?? 1.0}
                          onBlur={(e) => {
                            const val = Math.max(0.5, Math.min(2.0, parseFloat(e.target.value) || 1.0));
                            handleSaveConfigKey("tts.piper", "length_scale", val);
                          }}
                          className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                        />
                      </Field>

                      <Field label="Голос / Диктор Piper" hint="Выбор голоса диктора">
                        <select
                          value={cfg.tts?.piper?.speaker_id ?? 0}
                          onChange={(e) => handleSaveConfigKey("tts.piper", "speaker_id", parseInt(e.target.value, 10) || 0)}
                          className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                        >
                          <option value={0}>0 — Основной голос (по умолчанию)</option>
                          <option value={1}>1 — Альтернативный голос 1</option>
                          <option value={2}>2 — Альтернативный голос 2</option>
                          <option value={3}>3 — Альтернативный голос 3</option>
                        </select>
                      </Field>
                    </div>
                  </div>
                )}

                {(cfg.tts?.engine ?? "piper") === "gtts" && (
                  <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
                    <p className="text-xs text-text-muted">
                      Google TTS — облачный сервис синтеза речи Google. Требует активного интернет-соединения.
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                      <Field label="Язык озвучки Google (lang)">
                        <select
                          value={cfg.tts?.gtts?.lang ?? "ru"}
                          onChange={(e) => handleSaveConfigKey("tts.gtts", "lang", e.target.value)}
                          className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                        >
                          <option value="ru">Русский (ru)</option>
                          <option value="en">English (en)</option>
                        </select>
                      </Field>
                      <Field label="Замедленный темп (slow)">
                        <div className="flex items-center h-9">
                          <input
                            type="checkbox"
                            checked={cfg.tts?.gtts?.slow ?? false}
                            onChange={(e) => handleSaveConfigKey("tts.gtts", "slow", e.target.checked)}
                            className="h-4 w-4 rounded text-accent focus:ring-accent"
                          />
                          <span className="ml-2 text-xs text-text-muted">Читать замедленно</span>
                        </div>
                      </Field>
                    </div>
                  </div>
                )}

                {(cfg.tts?.engine ?? "piper") === "speecht5" && (
                  <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
                    <p className="text-xs text-text-muted">
                      SpeechT5 — локальная нейросетевая модель синтеза речи (Hugging Face).
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                      <Field label="Устройство выполнения (device)">
                        <select
                          value={cfg.tts?.speecht5?.device ?? "cpu"}
                          onChange={(e) => handleSaveConfigKey("tts.speecht5", "device", e.target.value)}
                          className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                        >
                          <option value="cpu">Процессор (CPU)</option>
                          <option value="cuda">Видеокарта (CUDA / GPU)</option>
                        </select>
                      </Field>
                      <Field label="ID диктора SpeechT5 (speaker_id)">
                        <input
                          type="number"
                          min={0}
                          max={7}
                          onKeyDown={handleDigitOnlyKeyDown}
                          defaultValue={cfg.tts?.speecht5?.speaker_id ?? 0}
                          onBlur={(e) => {
                            const clamped = clampInt(e.target.value, 0, 7, 0);
                            e.target.value = String(clamped);
                            handleSaveConfigKey("tts.speecht5", "speaker_id", clamped);
                          }}
                          className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                        />
                      </Field>
                    </div>
                  </div>
                )}

                <div className="flex flex-col gap-4 border-t border-border pt-6">
                  <h3 className="text-sm font-semibold text-text">Голосовой детектор (Silero VAD)</h3>
                  <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
                    <div>
                      <p className="text-sm font-medium text-text">Включить Silero VAD</p>
                      <p className="text-xs text-text-muted">
                        Нейросетевое определение начала и окончания речи для мгновенного отклика
                      </p>
                    </div>
                    <input
                      type="checkbox"
                      checked={cfg.vad?.enabled ?? true}
                      onChange={(e) => handleSaveConfigKey("vad", "enabled", e.target.checked)}
                      className="h-4 w-4 rounded text-accent focus:ring-accent"
                    />
                  </div>

                  <Field
                    label={`Порог чувствительности VAD: ${vadThreshold.toFixed(2)}`}
                    hint="0.3 — срабатывает на тихий шепот, 0.8 — только громкая уверенная речь"
                  >
                    <input
                      type="range"
                      min="0.1"
                      max="0.9"
                      step="0.05"
                      value={vadThreshold}
                      onChange={(e) => setVadThreshold(parseFloat(e.target.value))}
                      onMouseUp={() => handleSaveConfigKey("vad.silero", "threshold", vadThreshold)}
                      onTouchEnd={() => handleSaveConfigKey("vad.silero", "threshold", vadThreshold)}
                      className="w-full accent-accent"
                    />
                  </Field>
                </div>
              </div>
            </div>
          )}

          {/* ── 4. КОМАНДЫ & СЦЕНАРИИ ───────────────────────────────────────── */}
          {section === "commands" && (
            <div className="flex flex-col gap-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-medium text-text">Команды и автономные сценарии</h2>
                  <p className="text-xs text-text-muted">
                    Создание макросов, связок действий и настройка NLU-маршрутизатора
                  </p>
                </div>
                <button
                  onClick={handleOpenNewScenario}
                  className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:brightness-110"
                >
                  <Plus size={13} />
                  Новый сценарий
                </button>
              </div>

              {/* Scenario Editor Modal / Panel */}
              {editingScenarioId && (
                <div className="rounded-xl border border-accent/40 bg-surface p-4 flex flex-col gap-4 shadow-lg">
                  <div className="flex items-center justify-between border-b border-border pb-2">
                    <span className="text-sm font-semibold text-text">
                      {editingScenarioId === "__new__" ? "Создание сценария" : `Редактирование: ${scenarioForm.name}`}
                    </span>
                    <button onClick={() => setEditingScenarioId(null)} className="text-text-muted hover:text-text">
                      <X size={15} />
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <Field label="Название сценария">
                      <input
                        type="text"
                        value={scenarioForm.name}
                        onChange={(e) => setScenarioForm({ ...scenarioForm, name: e.target.value })}
                        placeholder="Например: Режим кодинга"
                        className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                      />
                    </Field>
                    <Field label="Описание (для LLM и пользователя)">
                      <input
                        type="text"
                        value={scenarioForm.description ?? ""}
                        onChange={(e) => setScenarioForm({ ...scenarioForm, description: e.target.value })}
                        placeholder="Переключает на воркспейс 2 и запускает IDE"
                        className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                      />
                    </Field>
                  </div>

                  <Field label="Фразы активации (через запятую)" hint="Слова, по которым сценарий запускается голосом">
                    <input
                      type="text"
                      value={scenarioPhrasesInput}
                      onChange={(e) => setScenarioPhrasesInput(e.target.value)}
                      placeholder="режим кодинга, начинаем программировать, сесть за код"
                      className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>

                  {/* Actions builder */}
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold tracking-wider text-text-muted">
                        ДЕЙСТВИЯ СЦЕНАРИЯ
                      </span>
                      <button
                        onClick={handleAddAction}
                        className="flex items-center gap-1 text-xs text-accent hover:underline"
                      >
                        <Plus size={12} />
                        Добавить шаг
                      </button>
                    </div>

                    {scenarioForm.actions.map((act, idx) => (
                      <div
                        key={idx}
                        className="flex items-center gap-2 rounded-lg border border-border bg-surface-2 p-2.5"
                      >
                        <span className="text-xs font-mono text-text-muted w-5 text-center">{idx + 1}.</span>
                        <select
                          value={act.type}
                          onChange={(e) => handleActionChange(idx, { type: e.target.value as ScenarioAction["type"] })}
                          className="rounded border border-border bg-surface px-2 py-1 text-xs text-text focus:outline-none"
                        >
                          <option value="workspace">Воркспейс</option>
                          <option value="launch">Запуск приложения</option>
                          <option value="command">Команда системы</option>
                          <option value="volume">Громкость</option>
                          <option value="speak">Сказать фразу</option>
                          <option value="delay">Пауза (сек)</option>
                        </select>

                        {act.type === "workspace" && (
                          <input
                            type="number"
                            min={1}
                            max={10}
                            onKeyDown={handleDigitOnlyKeyDown}
                            value={act.target ?? 1}
                            onChange={(e) => handleActionChange(idx, { target: parseInt(e.target.value, 10) || 1 })}
                            placeholder="Номер воркспейса (1-10)"
                            className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text"
                          />
                        )}

                        {act.type === "launch" && (
                          <input
                            type="text"
                            value={act.target ?? ""}
                            onChange={(e) => handleActionChange(idx, { target: e.target.value })}
                            placeholder="Имя программы (code, firefox, telegram...)"
                            className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text"
                          />
                        )}

                        {act.type === "command" && (
                          <input
                            type="text"
                            value={act.target ?? ""}
                            onChange={(e) => handleActionChange(idx, { target: e.target.value })}
                            placeholder="Системная команда (mute, pause, screenshot...)"
                            className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text"
                          />
                        )}

                        {act.type === "volume" && (
                          <input
                            type="number"
                            min={0}
                            max={100}
                            onKeyDown={handleDigitOnlyKeyDown}
                            value={act.amount ?? 50}
                            onChange={(e) => handleActionChange(idx, { amount: parseInt(e.target.value, 10) || 0 })}
                            placeholder="Процент громкости (0-100)"
                            className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text"
                          />
                        )}

                        {act.type === "speak" && (
                          <input
                            type="text"
                            value={act.text ?? ""}
                            onChange={(e) => handleActionChange(idx, { text: e.target.value })}
                            placeholder="Текст для озвучки ассистентом"
                            className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text"
                          />
                        )}

                        {act.type === "delay" && (
                          <input
                            type="number"
                            step="0.5"
                            min="0.5"
                            max="60"
                            value={act.seconds ?? 1}
                            onChange={(e) => handleActionChange(idx, { seconds: parseFloat(e.target.value) || 1 })}
                            placeholder="Секунды"
                            className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text"
                          />
                        )}

                        <button
                          onClick={() => handleRemoveAction(idx)}
                          className="rounded p-1 text-text-muted hover:text-danger"
                          title="Удалить действие"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    ))}
                  </div>

                  <div className="flex justify-end gap-2 pt-2">
                    <button
                      onClick={() => setEditingScenarioId(null)}
                      className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs text-text-muted hover:text-text"
                    >
                      Отмена
                    </button>
                    <button
                      onClick={handleSaveScenarioSubmit}
                      className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-white hover:brightness-110"
                    >
                      <Save size={13} />
                      Сохранить сценарий
                    </button>
                  </div>
                </div>
              )}

              {/* Scenarios List */}
              <div className="flex flex-col gap-3">
                {Object.keys(scenarios).length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-text-muted">
                    Нет сохранённых сценариев. Нажмите «Новый сценарий», чтобы создать автоматизацию.
                  </div>
                ) : (
                  Object.entries(scenarios).map(([id, sc]) => (
                    <div
                      key={id}
                      className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4"
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-sm font-semibold text-text">{sc.name}</p>
                          <p className="text-xs text-text-muted">{sc.description ?? "Без описания"}</p>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleOpenEditScenario(id, sc)}
                            className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
                            title="Редактировать"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            onClick={() => handleDeleteScenarioSubmit(id)}
                            className="rounded p-1.5 text-text-muted hover:bg-danger/10 hover:text-danger"
                            title="Удалить"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {(sc.phrases ?? [id]).map((phrase, pi) => (
                          <span
                            key={pi}
                            className="rounded bg-surface-2 px-2 py-0.5 text-[11px] text-text-muted"
                          >
                            «{phrase}»
                          </span>
                        ))}
                      </div>

                      <div className="flex items-center gap-2 pt-1 text-[11px] text-accent">
                        <span>Шагов: {sc.actions?.length ?? 0}</span>
                        <span>·</span>
                        <span>Действия: {sc.actions?.map((a) => a.type).join(" → ")}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Thresholds & NLU Config */}
              <div className="flex flex-col gap-4 border-t border-border pt-6">
                <h3 className="text-sm font-semibold text-text">Параметры маршрутизации команд и NLU</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field
                    label={`Порог нечеткого поиска: ${fuzzyThreshold.toFixed(2)}`}
                    hint="0.80 — оптимальный баланс точности и распознавания опечаток"
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="range"
                        min="0.5"
                        max="1.0"
                        step="0.05"
                        value={fuzzyThreshold}
                        onChange={(e) => setFuzzyThreshold(parseFloat(e.target.value))}
                        onMouseUp={() => handleSaveConfigKey("commands", "fuzzy_threshold", fuzzyThreshold)}
                        onTouchEnd={() => handleSaveConfigKey("commands", "fuzzy_threshold", fuzzyThreshold)}
                        className="flex-1 accent-accent"
                      />
                      <input
                        type="number"
                        step="0.05"
                        min="0.5"
                        max="1.0"
                        value={fuzzyThreshold}
                        onKeyDown={handleDecimalKeyDown}
                        onChange={(e) => {
                          const v = parseFloat(e.target.value);
                          if (!isNaN(v)) setFuzzyThreshold(v);
                        }}
                        onBlur={() => {
                          const clamped = Math.max(0.5, Math.min(1.0, fuzzyThreshold));
                          setFuzzyThreshold(clamped);
                          handleSaveConfigKey("commands", "fuzzy_threshold", clamped);
                        }}
                        className="w-20 rounded-lg border border-border bg-surface px-2.5 py-1 text-sm text-text focus:outline-none focus:border-accent text-center"
                      />
                    </div>
                  </Field>

                  <Field label="Таймаут выполнения команды (сек)">
                    <input
                      type="number"
                      min={5}
                      max={120}
                      onKeyDown={handleDigitOnlyKeyDown}
                      defaultValue={cfg.commands?.execution_timeout ?? 30}
                      onBlur={(e) => {
                        const clamped = clampInt(e.target.value, 5, 120, 30);
                        e.target.value = String(clamped);
                        handleSaveConfigKey("commands", "execution_timeout", clamped);
                      }}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                </div>
              </div>
            </div>
          )}

          {/* ── 5. СИСТЕМА, ПОИСК & TELEGRAM ───────────────────────────────── */}
          {section === "system" && (
            <div className="flex flex-col gap-6">
              <div>
                <h2 className="text-lg font-medium text-text">Веб-поиск, логирование и Telegram</h2>
                <p className="text-xs text-text-muted">
                  Автономный веб-поиск (DuckDuckGo / Brave / Tavily), бот и системные настройки
                </p>
              </div>

              {/* Web Search Config */}
              <div className="flex flex-col gap-4">
                <h3 className="text-sm font-semibold text-text">Автономный Web Search & Browsing</h3>
                <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
                  <div>
                    <p className="text-sm font-medium text-text">Включить поиск в интернете</p>
                    <p className="text-xs text-text-muted">
                      Позволяет Джарвису находить свежую информацию, новости и читать страницы
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={cfg.web_search?.enabled ?? true}
                    onChange={(e) => handleSaveConfigKey("web_search", "enabled", e.target.checked)}
                    className="h-4 w-4 rounded text-accent focus:ring-accent"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label="Провайдер веб-поиска">
                    <select
                      value={cfg.web_search?.provider ?? "duckduckgo"}
                      onChange={(e) => handleSaveConfigKey("web_search", "provider", e.target.value)}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    >
                      <option value="duckduckgo">DuckDuckGo (бесплатно, без API-ключей)</option>
                      <option value="brave">Brave Search API (по ключу)</option>
                      <option value="tavily">Tavily AI Search (по ключу)</option>
                    </select>
                  </Field>

                  <Field label="Максимум результатов поиска">
                    <input
                      type="number"
                      min={1}
                      max={10}
                      onKeyDown={handleDigitOnlyKeyDown}
                      defaultValue={cfg.web_search?.max_results ?? 5}
                      onBlur={(e) => {
                        const clamped = clampInt(e.target.value, 1, 10, 5);
                        e.target.value = String(clamped);
                        handleSaveConfigKey("web_search", "max_results", clamped);
                      }}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                </div>

                {/* API Key inputs shown ONLY when Brave or Tavily is selected */}
                {(cfg.web_search?.provider ?? "duckduckgo") === "duckduckgo" ? (
                  <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs text-emerald-500 flex items-center gap-2">
                    <Check size={14} className="shrink-0" />
                    <span>DuckDuckGo работает бесплатно и не требует ввода API-ключей.</span>
                  </div>
                ) : (cfg.web_search?.provider ?? "duckduckgo") === "brave" ? (
                  <Field label="Brave Search API Key" hint="Ключ для доступа к Brave Search API">
                    <input
                      type="password"
                      defaultValue={cfg.web_search?.brave_api_key ? "••••••••" : ""}
                      onBlur={(e) => {
                        const val = e.target.value.trim();
                        if (val.includes("•") || val.includes("***")) return;
                        handleSaveConfigKey("web_search", "brave_api_key", val || null);
                      }}
                      placeholder={cfg.web_search?.brave_api_key ? "••••••••" : "BSA..."}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                ) : (
                  <Field label="Tavily AI Search API Key" hint="Ключ для доступа к Tavily API">
                    <input
                      type="password"
                      defaultValue={cfg.web_search?.tavily_api_key ? "••••••••" : ""}
                      onBlur={(e) => {
                        const val = e.target.value.trim();
                        if (val.includes("•") || val.includes("***")) return;
                        handleSaveConfigKey("web_search", "tavily_api_key", val || null);
                      }}
                      placeholder={cfg.web_search?.tavily_api_key ? "••••••••" : "tvly-..."}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                    />
                  </Field>
                )}
              </div>

              {/* Logging & Service Lifecycle Controls */}
              <div className="flex flex-col gap-4 border-t border-border pt-6">
                <h3 className="text-sm font-semibold text-text">Логирование и применение настроек</h3>
                <Field label="Уровень логирования" hint="Степень детализации журналов в logs/jarvis.log">
                  <select
                    value={cfg.logging?.level ?? "INFO"}
                    onChange={(e) => handleSaveConfigKey("logging", "level", e.target.value)}
                    className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                  >
                    <option value="DEBUG">DEBUG (подробный журнал для отладки)</option>
                    <option value="INFO">INFO (стандартный рабочий журнал)</option>
                    <option value="WARNING">WARNING (только предупреждения и ошибки)</option>
                    <option value="ERROR">ERROR (только критические сбои)</option>
                  </select>
                </Field>

                <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
                  <div>
                    <p className="text-sm font-medium text-text">Применить настройки и перезапустить сервис</p>
                    <p className="text-xs text-text-muted">
                      Перезапуск процесса JARVIS требуется для применения изменённых аудиоустройств и параметров ядра
                    </p>
                  </div>
                  <button
                    onClick={handleRestartBackend}
                    disabled={restarting}
                    className="flex items-center gap-2 rounded-lg border border-accent bg-accent/10 px-4 py-2 text-xs font-medium text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
                  >
                    <RefreshCw size={13} className={restarting ? "animate-spin" : ""} />
                    <span>{restarting ? "Перезапуск..." : "Перезапустить сервис"}</span>
                  </button>
                </div>
              </div>

              {/* Telegram Bot */}
              <div className="flex flex-col gap-4 border-t border-border pt-6">
                <h3 className="text-sm font-semibold text-text">Telegram-интеграция</h3>
                <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
                  <div>
                    <p className="text-sm font-medium text-text">Включить Telegram-бота</p>
                    <p className="text-xs text-text-muted">
                      Позволяет отдавать голосовые и текстовые команды ассистенту через Telegram
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={cfg.telegram?.enabled ?? false}
                    onChange={(e) => handleSaveConfigKey("telegram", "enabled", e.target.checked)}
                    className="h-4 w-4 rounded text-accent focus:ring-accent"
                  />
                </div>

                <Field label="Токен бота Telegram (Bot Father)">
                  <input
                    type="password"
                    defaultValue={cfg.telegram?.bot_token ? "••••••••" : ""}
                    onBlur={(e) => {
                      const val = e.target.value.trim();
                      if (val.includes("•") || val.includes("***")) return;
                      handleSaveConfigKey("telegram", "bot_token", val || null);
                    }}
                    placeholder={cfg.telegram?.bot_token ? "••••••••" : "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"}
                    className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-accent"
                  />
                </Field>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
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
      <label className="text-xs font-medium text-text">{label}</label>
      {children}
      {hint && <span className="text-[11px] text-text-muted">{hint}</span>}
    </div>
  );
}
