import { useEffect, useMemo, useState } from "react";
import { Search, Trash2, X, CheckSquare, Square } from "lucide-react";
import { purgeBackendSession, purgeAllBackendSessions } from "../api/backend";

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  timestamp: string;
}

interface Session {
  id: string;
  title: string;
  messages: Message[];
}

const CHAT_STORAGE_KEY = "jarvis.ui.chats";
const SKIP_CONFIRM_KEY = "jarvis.ui.skip-delete-confirm";

function loadSessions(): Session[] {
  try {
    const stored = localStorage.getItem(CHAT_STORAGE_KEY);
    return stored ? (JSON.parse(stored) as Session[]) : [];
  } catch {
    return [];
  }
}

function saveSessions(sessions: Session[]): void {
  localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(sessions));
}

interface FlatItem {
  key: string;
  sessionId: string;
  role: "user" | "assistant";
  text: string;
  timestamp: string;
  session: string;
}

export default function HistoryTab() {
  const [search, setSearch] = useState("");
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [skipConfirm, setSkipConfirm] = useState(
    () => localStorage.getItem(SKIP_CONFIRM_KEY) === "1",
  );
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    const onSync = () => setSessions(loadSessions());
    window.addEventListener("focus", onSync);
    window.addEventListener("jarvis:history-updated", onSync);
    return () => {
      window.removeEventListener("focus", onSync);
      window.removeEventListener("jarvis:history-updated", onSync);
    };
  }, []);

  useEffect(() => {
    if (!confirmOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setConfirmOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [confirmOpen]);

  const items: FlatItem[] = useMemo(() => {
    const flat: FlatItem[] = [];
    for (const session of sessions) {
      for (const m of session.messages ?? []) {
        if (m.role === "system") continue;
        flat.push({
          key: `${session.id}-${m.id}`,
          sessionId: session.id,
          role: m.role === "user" ? "user" : "assistant",
          text: m.text,
          timestamp: m.timestamp,
          session: session.title,
        });
      }
    }
    return flat;
  }, [sessions]);

  const filtered = items.filter((h) =>
    h.text.toLowerCase().includes(search.toLowerCase()),
  );

  const toggleItem = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const allFilteredSelected = filtered.length > 0 && filtered.every((i) => selected.has(i.key));

  const toggleAll = () => {
    if (allFilteredSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        for (const i of filtered) next.delete(i.key);
        return next;
      });
    } else {
      setSelected((prev) => {
        const next = new Set(prev);
        for (const i of filtered) next.add(i.key);
        return next;
      });
    }
  };

  /** Removes selected messages; drops sessions left with no messages. */
  const deleteSelected = async () => {
    const touched = Array.from(
      new Set(
        sessions
          .filter((s) => s.messages.some((m) => selected.has(`${s.id}-${m.id}`)))
          .map((s) => s.id),
      ),
    );

    const remaining = sessions
      .map((session) => ({
        ...session,
        messages: session.messages.filter(
          (m) => !selected.has(`${session.id}-${m.id}`),
        ),
      }))
      .filter((session) => session.messages.length > 0);
    saveSessions(remaining);
    setSessions(remaining);
    setSelected(new Set());
    window.dispatchEvent(new CustomEvent("jarvis:history-updated", { detail: { source: "history" } }));

    const remainingIds = new Set(remaining.map((s) => s.id));
    const droppedSessionIds = touched.filter((id) => !remainingIds.has(id));

    for (const id of droppedSessionIds) {
      await purgeBackendSession(id).catch(() => undefined);
    }
  };

  const requestDelete = () => {
    if (selected.size === 0) return;
    if (skipConfirm) void deleteSelected();
    else setConfirmOpen(true);
  };

  const confirmDelete = () => {
    if (skipConfirm) localStorage.setItem(SKIP_CONFIRM_KEY, "1");
    setConfirmOpen(false);
    void deleteSelected();
  };

  const handleClearAll = async () => {
    setClearing(true);
    try {
      // purge_all_sessions, а не clear_history: обещание «удалить память
      // модели» должно включать архивы прошлых чатов.
      await purgeAllBackendSessions().catch(() => undefined);
      localStorage.removeItem(CHAT_STORAGE_KEY);
      setSessions([]);
      setSelected(new Set());
      window.dispatchEvent(new CustomEvent("jarvis:history-updated", { detail: { source: "history" } }));
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="relative flex h-full flex-col">
      {/* Search bar */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Search size={16} className="text-text-muted" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Поиск по истории..."
          className="flex-1 bg-transparent text-sm text-text placeholder:text-text-muted focus:outline-none"
        />
        {filtered.length > 0 && (
          <button
            onClick={toggleAll}
            className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-text"
            title={allFilteredSelected ? "Снять выделение" : "Выбрать все"}
          >
            {allFilteredSelected
              ? <CheckSquare size={14} />
              : <Square size={14} />}
          </button>
        )}
        <button
          onClick={() => void handleClearAll()}
          disabled={clearing || sessions.length === 0}
          className="rounded p-1.5 text-text-muted hover:bg-surface-2 hover:text-danger disabled:opacity-30"
          title="Удалить всю историю (локальные чаты + память модели)"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* Bulk delete bar */}
      {selected.size > 0 && (
        <div className="flex items-center justify-between border-b border-border bg-accent-bg/40 px-4 py-2 text-sm">
          <span className="text-text">Выбрано: {selected.size}</span>
          <button
            onClick={requestDelete}
            className="flex items-center gap-1.5 rounded-lg bg-danger px-3 py-1 text-xs font-medium text-white hover:brightness-110"
          >
            <Trash2 size={12} />
            Удалить выбранное
          </button>
        </div>
      )}

      {/* History list */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div className="mx-auto flex max-w-3xl flex-col gap-2">
          {filtered.map((item) => {
            const checked = selected.has(item.key);
            return (
              <div
                key={item.key}
                className={`flex gap-2 rounded-lg border px-3 py-2.5 transition-colors ${
                  checked
                    ? "border-danger/50 bg-danger/10"
                    : "border-border bg-surface hover:bg-surface-2/50"
                }`}
              >
                <button
                  onClick={() => toggleItem(item.key)}
                  className="mt-0.5 shrink-0 text-text-muted hover:text-accent"
                  title={checked ? "Снять выделение" : "Выбрать"}
                >
                  {checked ? <CheckSquare size={15} /> : <Square size={15} />}
                </button>
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        item.role === "user"
                          ? "bg-accent-bg text-accent"
                          : "bg-surface-2 text-text-muted"
                      }`}
                    >
                      {item.role === "user" ? "ВЫ" : "JARVIS"}
                    </span>
                    <span className="text-[10px] text-text-muted">{item.timestamp}</span>
                    <span className="ml-auto truncate text-[10px] text-text-muted">
                      {item.session}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-sm text-text">
                    {item.text}
                  </p>
                </div>
              </div>
            );
          })}

          {filtered.length === 0 && (
            <div className="py-12 text-center text-sm text-text-muted">
              {items.length === 0 ? "История пуста" : "Ничего не найдено"}
            </div>
          )}
        </div>
      </div>

      {/* Confirm dialog */}
      {confirmOpen && (
        <div
          role="dialog"
          aria-modal="true"
          tabIndex={-1}
          onClick={(e) => e.target === e.currentTarget && setConfirmOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && setConfirmOpen(false)}
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
        >
          <div className="flex w-full max-w-sm flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-base font-medium text-text">Удалить сообщения?</h3>
              <button
                onClick={() => setConfirmOpen(false)}
                className="rounded p-0.5 text-text-muted hover:text-text"
              >
                <X size={16} />
              </button>
            </div>
            <p className="text-sm text-text-muted">
              Будет удалено {selected.size} сообщ. из истории. Действие необратимо.
            </p>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-text-muted">
              <input
                type="checkbox"
                checked={skipConfirm}
                onChange={(e) => setSkipConfirm(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--color-accent)]"
              />
              Больше не спрашивать
            </label>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmOpen(false)}
                className="rounded-lg px-4 py-2 text-sm text-text-muted hover:bg-surface-2"
              >
                Отмена
              </button>
              <button
                onClick={() => void confirmDelete()}
                className="rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white hover:brightness-110"
              >
                Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
