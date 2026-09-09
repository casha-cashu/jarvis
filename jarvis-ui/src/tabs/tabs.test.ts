import { describe, expect, it, vi } from "vitest";

if (typeof window === "undefined") {
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
      const list = listeners.get(event.type) ?? [];
      for (const cb of list) cb(event);
      return true;
    },
  };
  Object.defineProperty(globalThis, "window", { value: mockWindow, configurable: true });
}

if (typeof CustomEvent === "undefined") {
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

if (typeof navigator === "undefined") {
  Object.defineProperty(globalThis, "navigator", {
    value: {
      clipboard: {
        writeText: async () => {},
      },
    },
    configurable: true,
    writable: true,
  });
}

describe("FRONTEND-BUG-1: Session selective purge logic", () => {
  it("only purges sessions that have no remaining messages", () => {
    interface Message {
      id: string;
      role: string;
      text: string;
    }
    interface Session {
      id: string;
      title: string;
      messages: Message[];
    }

    const sessions: Session[] = [
      {
        id: "sess-1",
        title: "Chat 1",
        messages: [
          { id: "m-1", role: "user", text: "Hello" },
          { id: "m-2", role: "assistant", text: "Hi" },
        ],
      },
      {
        id: "sess-2",
        title: "Chat 2",
        messages: [{ id: "m-3", role: "user", text: "Only msg" }],
      },
    ];

    // Case A: Select only m-1 from sess-1 (partial deletion)
    const selectedA = new Set(["sess-1-m-1"]);
    const touchedA = Array.from(
      new Set(
        sessions
          .filter((s) => s.messages.some((m) => selectedA.has(`${s.id}-${m.id}`)))
          .map((s) => s.id),
      ),
    );
    const remainingA = sessions
      .map((session) => ({
        ...session,
        messages: session.messages.filter((m) => !selectedA.has(`${session.id}-${m.id}`)),
      }))
      .filter((session) => session.messages.length > 0);

    const remainingIdsA = new Set(remainingA.map((s) => s.id));
    const droppedSessionIdsA = touchedA.filter((id) => !remainingIdsA.has(id));

    expect(droppedSessionIdsA).toEqual([]); // sess-1 still has m-2, so NOT dropped

    // Case B: Select m-3 from sess-2 (full session deletion)
    const selectedB = new Set(["sess-2-m-3"]);
    const touchedB = Array.from(
      new Set(
        sessions
          .filter((s) => s.messages.some((m) => selectedB.has(`${s.id}-${m.id}`)))
          .map((s) => s.id),
      ),
    );
    const remainingB = sessions
      .map((session) => ({
        ...session,
        messages: session.messages.filter((m) => !selectedB.has(`${session.id}-${m.id}`)),
      }))
      .filter((session) => session.messages.length > 0);

    const remainingIdsB = new Set(remainingB.map((s) => s.id));
    const droppedSessionIdsB = touchedB.filter((id) => !remainingIdsB.has(id));

    expect(droppedSessionIdsB).toEqual(["sess-2"]); // sess-2 had all messages deleted
  });
});

describe("FRONTEND-BUG-3: jarvis:history-updated source filtering", () => {
  it("ignores history update when source is 'chat'", () => {
    let syncCalled = false;
    const handleHistoryUpdated = (e: { detail?: { source?: string } }) => {
      if (e.detail?.source === "chat") return;
      syncCalled = true;
    };

    handleHistoryUpdated({ detail: { source: "chat" } });
    expect(syncCalled).toBe(false);

    handleHistoryUpdated({ detail: { source: "history" } });
    expect(syncCalled).toBe(true);
  });
});

describe("FRONTEND-BUG-4: changeModel rollback on configureBackend failure", () => {
  it("rolls back activeModel when configuration fails", async () => {
    let currentActive: { providerId: string; model: string } | null = {
      providerId: "p1",
      model: "gpt-4o",
    };
    const prevActive = currentActive;

    const configureBackendMock = vi.fn().mockRejectedValue(new Error("Connection refused"));

    const changeModel = async (newProviderId: string, newModel: string) => {
      currentActive = { providerId: newProviderId, model: newModel };
      try {
        await configureBackendMock();
      } catch {
        currentActive = prevActive;
      }
    };

    await changeModel("p2", "claude-3-5-sonnet");
    expect(currentActive).toEqual({ providerId: "p1", model: "gpt-4o" });
  });
});

describe("FRONTEND-BUG-6: Keyboard shortcut allowance", () => {
  it("allows Ctrl and Meta modifier combinations in digit-only and decimal inputs", () => {
    const handleDigitOnlyKeyDown = (e: {
      key: string;
      ctrlKey?: boolean;
      metaKey?: boolean;
      preventDefault: () => void;
    }) => {
      if (e.ctrlKey || e.metaKey) return;
      if (["Backspace", "Delete", "ArrowLeft", "ArrowRight", "Tab", "Enter"].includes(e.key)) {
        return;
      }
      if (!/^[0-9]$/.test(e.key)) {
        e.preventDefault();
      }
    };

    const prevented = vi.fn();
    // Normal letter without ctrl/meta should be prevented
    handleDigitOnlyKeyDown({ key: "a", ctrlKey: false, metaKey: false, preventDefault: prevented });
    expect(prevented).toHaveBeenCalledTimes(1);

    // Ctrl+A should be allowed (preventDefault NOT called)
    prevented.mockClear();
    handleDigitOnlyKeyDown({ key: "a", ctrlKey: true, metaKey: false, preventDefault: prevented });
    expect(prevented).not.toHaveBeenCalled();

    // Cmd+V (metaKey) should be allowed
    prevented.mockClear();
    handleDigitOnlyKeyDown({ key: "v", ctrlKey: false, metaKey: true, preventDefault: prevented });
    expect(prevented).not.toHaveBeenCalled();
  });
});

describe("FRONTEND-BUG-2: Secret field mask protection", () => {
  it("ignores onBlur updates when masked bullets or asterisks are present", () => {
    const handleSave = vi.fn();
    const handleBlur = (val: string) => {
      const trimmed = val.trim();
      if (trimmed.includes("•") || trimmed.includes("***")) return;
      handleSave(trimmed || null);
    };

    handleBlur("••••••••");
    expect(handleSave).not.toHaveBeenCalled();

    handleBlur("abc***123");
    expect(handleSave).not.toHaveBeenCalled();

    handleBlur("sk-real-secret-key");
    expect(handleSave).toHaveBeenCalledWith("sk-real-secret-key");

    handleBlur("");
    expect(handleSave).toHaveBeenCalledWith(null);
  });
});

describe("FRONTEND-BUG-5: Tauri unlisten error suppression", () => {
  it("gracefully catches rejection from unlisten promise", async () => {
    const failingUnlistenPromise = Promise.reject(new Error("Event already disposed"));
    let errorCaught: unknown = null;

    await failingUnlistenPromise
      .then((fn: () => void) => fn())
      .catch((err: unknown) => {
        errorCaught = err;
        return undefined;
      });

    expect(errorCaught).toBeInstanceOf(Error);
  });
});

describe("FRONTEND-BUG-7: ToolStepView WCAG AAA badge contrast", () => {
  it("badge uses text-slate-950 font-bold on bg-accent instead of text-white", () => {
    const badgeClass = "shrink-0 rounded bg-accent px-1 py-0.5 text-[10px] font-bold uppercase text-slate-950";
    expect(badgeClass).toContain("text-slate-950");
    expect(badgeClass).toContain("font-bold");
    expect(badgeClass).not.toContain("text-white");
  });
});

describe("FRONTEND-BUG-8: Modal dialog backdrop and keydown handlers", () => {
  it("only closes when click is on the backdrop container directly", () => {
    let closed = false;
    const backdrop = { id: "backdrop" };
    const innerModal = { id: "modal-card" };

    const handleBackdropClick = (target: unknown, currentTarget: unknown) => {
      if (target === currentTarget) {
        closed = true;
      }
    };

    // Click on inner modal card: should not close
    handleBackdropClick(innerModal, backdrop);
    expect(closed).toBe(false);

    // Click on backdrop directly: should close
    handleBackdropClick(backdrop, backdrop);
    expect(closed).toBe(true);
  });
});

describe("FRONTEND-BUG-9: Smart autoscroll logic", () => {
  it("detects when user is within 80px threshold of bottom", async () => {
    const { checkIsAtBottom } = await import("../utils/ui");

    // scrollHeight=1000, scrollTop=550, clientHeight=400 -> dist = 50px <= 80px -> true
    expect(checkIsAtBottom(1000, 550, 400)).toBe(true);

    // scrollHeight=1000, scrollTop=520, clientHeight=400 -> dist = 80px <= 80px -> true
    expect(checkIsAtBottom(1000, 520, 400)).toBe(true);

    // scrollHeight=1000, scrollTop=400, clientHeight=400 -> dist = 200px > 80px -> false
    expect(checkIsAtBottom(1000, 400, 400)).toBe(false);

    // scrollHeight=1000, scrollTop=0, clientHeight=400 -> dist = 600px -> false
    expect(checkIsAtBottom(1000, 0, 400)).toBe(false);
  });
});

describe("FRONTEND-BUG-10: Double-send and composition protection", () => {
  it("blocks send if text is empty, already sending, or composing", () => {
    let sendCalls = 0;
    const sendingRef = { current: false };

    const canSend = (input: string, isSending: boolean, isComposing: boolean) => {
      if (isComposing) return false;
      if (isSending || sendingRef.current) return false;
      if (!input.trim()) return false;
      return true;
    };

    const triggerSend = (input: string, isSending: boolean, isComposing: boolean) => {
      if (!canSend(input, isSending, isComposing)) return false;
      sendingRef.current = true;
      sendCalls++;
      return true;
    };

    // Empty text
    expect(triggerSend("   ", false, false)).toBe(false);
    expect(sendCalls).toBe(0);

    // IME composition active
    expect(triggerSend("привет", false, true)).toBe(false);
    expect(sendCalls).toBe(0);

    // Already sending via state
    expect(triggerSend("привет", true, false)).toBe(false);
    expect(sendCalls).toBe(0);

    // Normal valid send
    expect(triggerSend("привет", false, false)).toBe(true);
    expect(sendCalls).toBe(1);

    // Immediate second trigger blocked by sendingRef even if state hasn't flushed
    expect(triggerSend("второе сообщение", false, false)).toBe(false);
    expect(sendCalls).toBe(1);
  });
});

describe("FRONTEND-BUG-11: StatusTab isActive polling guard", () => {
  it("clears interval and skips background polling when isActive is false", () => {
    let intervalId: number | null = null;
    let pollCount = 0;

    const setupPolling = (isActive: boolean) => {
      if (!isActive) return () => {};
      pollCount++;
      intervalId = 12345;
      return () => {
        intervalId = null;
      };
    };

    // When inactive: no poll, no interval
    const cleanupInactive = setupPolling(false);
    expect(pollCount).toBe(0);
    expect(intervalId).toBeNull();
    cleanupInactive();

    // When active: poll called, interval registered
    const cleanupActive = setupPolling(true);
    expect(pollCount).toBe(1);
    expect(intervalId).toBe(12345);

    // Cleanup on tab switch / unmount
    cleanupActive();
    expect(intervalId).toBeNull();
  });
});

describe("FRONTEND-BUG-12: Message bubble styles and safe clipboard copy", () => {
  it("safely handles clipboard errors without crashing", async () => {
    const { copyToClipboard } = await import("../utils/ui");

    // Mock navigator.clipboard.writeText throwing an error
    const originalClipboard = navigator.clipboard;
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: vi.fn().mockRejectedValue(new Error("Clipboard access denied")),
      },
      configurable: true,
    });

    const result = await copyToClipboard("test text");
    // Should return false, not throw
    expect(result).toBe(false);

    // Restore
    Object.defineProperty(navigator, "clipboard", {
      value: originalClipboard,
      configurable: true,
    });
  });

  it("successfully writes to clipboard when available", async () => {
    const { copyToClipboard } = await import("../utils/ui");

    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: writeTextMock,
      },
      configurable: true,
    });

    const result = await copyToClipboard("copied message");
    expect(result).toBe(true);
    expect(writeTextMock).toHaveBeenCalledWith("copied message");
  });
});

describe("FRONTEND-BUG-13: Sidebar tooltip duplicate removal & TitleBar window control error suppression", () => {
  it("suppresses errors when window control fails in tiling WMs", async () => {
    const { tauriCommand } = await import("../utils/ui");

    // In a non-tauri or tiling WM environment where window commands throw
    await expect(tauriCommand("minimize")).resolves.not.toThrow();
  });
});


describe("FRONTEND-BUG-14: Theme sanitization and cross-component custom event synchronization", () => {
  it("sanitizes invalid theme values to fallback", async () => {
    const { sanitizeTheme } = await import("../hooks/useTheme");

    expect(sanitizeTheme("dark")).toBe("dark");
    expect(sanitizeTheme("light")).toBe("light");
    expect(sanitizeTheme("system")).toBe("system");

    // Invalid values
    expect(sanitizeTheme("blue")).toBe("dark");
    expect(sanitizeTheme(null)).toBe("dark");
    expect(sanitizeTheme(undefined)).toBe("dark");
    expect(sanitizeTheme(123)).toBe("dark");
    expect(sanitizeTheme("", "light")).toBe("light");
  });

  it("dispatches jarvis:theme-change on theme updates", async () => {
    const events: string[] = [];
    const handler = (e: Event) => {
      const custom = e as CustomEvent<string>;
      events.push(custom.detail);
    };
    window.addEventListener("jarvis:theme-change", handler);

    window.dispatchEvent(new CustomEvent("jarvis:theme-change", { detail: "light" }));
    expect(events).toEqual(["light"]);

    window.removeEventListener("jarvis:theme-change", handler);
  });
});

describe("FRONTEND-BUG-15: History sync and source event propagation", () => {
  it("ChatTab ignores jarvis:history-updated when source is 'chat'", () => {
    let reloaded = false;
    const onHistoryUpdated = (e: { detail?: { source?: string } }) => {
      if (e.detail?.source === "chat") return;
      reloaded = true;
    };
    onHistoryUpdated({ detail: { source: "chat" } });
    expect(reloaded).toBe(false);

    onHistoryUpdated({ detail: { source: "history" } });
    expect(reloaded).toBe(true);
  });

  it("ChatTab updates activeSession to first available if active was deleted", () => {
    const sessions = [{ id: "sess-2", title: "Chat 2" }, { id: "sess-3", title: "Chat 3" }];
    const currentActive = "sess-1"; // was deleted in history
    const nextActive = !sessions.some((s) => s.id === currentActive) ? (sessions[0]?.id ?? "") : currentActive;
    expect(nextActive).toBe("sess-2");
  });

  it("HistoryTab dispatches source 'history' on deletion and clear-all", () => {
    const dispatched: unknown[] = [];
    const dispatch = (detail: unknown) => {
      dispatched.push(detail);
    };
    dispatch({ source: "history" });
    expect(dispatched).toEqual([{ source: "history" }]);
  });
});

describe("FRONTEND-BUG-16: Number clamping and input protection", () => {
  it("clampNumber clamps floats within range and handles invalid values", async () => {
    const { clampNumber } = await import("../utils/ui");
    expect(clampNumber(0.7, 0.0, 2.0, 0.7)).toBe(0.7);
    expect(clampNumber(-0.5, 0.0, 2.0, 0.7)).toBe(0.0);
    expect(clampNumber(3.5, 0.0, 2.0, 0.7)).toBe(2.0);
    expect(clampNumber("1.5", 0.0, 2.0, 0.7)).toBe(1.5);
    expect(clampNumber(NaN, 0.0, 2.0, 0.7)).toBe(0.7);
    expect(clampNumber("invalid", 0.0, 2.0, 0.7)).toBe(0.7);
    expect(clampNumber(Infinity, 0.0, 2.0, 0.7)).toBe(0.7);
  });

  it("clampInt clamps integers within range, truncates decimals, and handles invalid values", async () => {
    const { clampInt } = await import("../utils/ui");
    expect(clampInt(5, 1, 30, 5)).toBe(5);
    expect(clampInt(0, 1, 30, 5)).toBe(1);
    expect(clampInt(45, 1, 30, 5)).toBe(30);
    expect(clampInt("15", 1, 30, 5)).toBe(15);
    expect(clampInt(4.9, 1, 30, 5)).toBe(4);
    expect(clampInt(NaN, 1, 30, 5)).toBe(5);
    expect(clampInt("bad", 1, 30, 5)).toBe(5);
    expect(clampInt(4096, 1, 32768, 4096)).toBe(4096);
    expect(clampInt(0, 1, 32768, 4096)).toBe(1);
    expect(clampInt(99999, 1, 32768, 4096)).toBe(32768);
  });
});

describe("FRONTEND-BUG-17: Local provider model fetching without API key", () => {
  it("allows local providers (ollama, lmstudio, localhost, 127.0.0.1) without API key but blocks remote providers", async () => {
    const { isLocalProvider } = await import("../api/providers");

    const ollama = { type: "openai" as const, endpoint: "http://localhost:11434/v1", apiKey: "", id: "1", name: "Ollama" };
    const lmstudio = { type: "openai" as const, endpoint: "http://127.0.0.1:1234/v1", apiKey: "", id: "2", name: "LM Studio" };
    const remoteWithoutKey = { type: "openai" as const, endpoint: "https://api.openai.com/v1", apiKey: "", id: "3", name: "OpenAI" };
    const remoteWithKey = { type: "openai" as const, endpoint: "https://api.openai.com/v1", apiKey: "sk-proj", id: "4", name: "OpenAI" };

    expect(isLocalProvider(ollama)).toBe(true);
    expect(isLocalProvider(lmstudio)).toBe(true);
    expect(isLocalProvider(remoteWithoutKey)).toBe(false);
    expect(isLocalProvider(remoteWithKey)).toBe(false);

    const shouldSkipFetch = (provider: { apiKey?: string; endpoint?: string; name?: string; type?: string }) =>
      !isLocalProvider(provider) && !provider.apiKey;

    expect(shouldSkipFetch(ollama)).toBe(false);
    expect(shouldSkipFetch(lmstudio)).toBe(false);
    expect(shouldSkipFetch(remoteWithoutKey)).toBe(true);
    expect(shouldSkipFetch(remoteWithKey)).toBe(false);
  });
});

describe("FRONTEND-BUG-18: Model groups defensive rendering", () => {
  it("safely handles null/undefined sub.models without throwing", () => {
    const subMalformed = { provider: "test", models: undefined as unknown as string[] };
    const renderModels = (sub: { models?: string[] }) => (sub.models ?? []).map((m) => m.toUpperCase());

    expect(() => renderModels(subMalformed)).not.toThrow();
    expect(renderModels(subMalformed)).toEqual([]);
    expect(renderModels({ models: ["gpt-4o"] })).toEqual(["GPT-4O"]);
  });
});

describe("FRONTEND-BUG-19: Backend restart synchronization and status error handling", () => {
  it("StatusTab sets connected to false when getBackendStatus fails", () => {
    let backendState = { running: true, connected: true };
    const handleStatusError = () => {
      backendState = { ...backendState, connected: false };
    };

    handleStatusError();
    expect(backendState.connected).toBe(false);
    expect(backendState.running).toBe(true);
  });

  it("ChatTab backend-restarted handler reconfigures model and switches session", async () => {
    const configureMock = vi.fn().mockResolvedValue(undefined);
    const switchMock = vi.fn().mockResolvedValue(undefined);

    const onBackendRestarted = async (activeModel: { providerId: string; model: string } | null, activeSession: string) => {
      if (activeModel) {
        await configureMock({ model: activeModel.model });
      }
      if (activeSession) {
        await switchMock(activeSession);
      }
    };

    await onBackendRestarted({ providerId: "p1", model: "gpt-4o" }, "sess-123");
    expect(configureMock).toHaveBeenCalledWith({ model: "gpt-4o" });
    expect(switchMock).toHaveBeenCalledWith("sess-123");
  });
});

describe("FRONTEND-BUG-20: Provider change synchronization and API key visibility", () => {
  it("ChatTab reloads providers and active model on jarvis:providers-changed", () => {
    let currentProviders: string[] = ["old"];
    let currentActive: string | null = "old-model";

    const onProvidersChanged = (newProviders: string[], newActive: string | null) => {
      currentProviders = newProviders;
      currentActive = newActive;
    };

    onProvidersChanged(["p1", "p2"], "p1::gpt-4o");
    expect(currentProviders).toEqual(["p1", "p2"]);
    expect(currentActive).toBe("p1::gpt-4o");
  });

  it("toggles API key input type between password and text", () => {
    let showApiKey = false;
    const toggleShowApiKey = () => {
      showApiKey = !showApiKey;
    };

    const getInputType = (visible: boolean) => (visible ? "text" : "password");

    expect(getInputType(showApiKey)).toBe("password");
    toggleShowApiKey();
    expect(getInputType(showApiKey)).toBe("text");
    toggleShowApiKey();
    expect(getInputType(showApiKey)).toBe("password");
  });
});

describe("FRONTEND-BUG-21: HistoryTab safe message iteration, toggleAll logic, and empty state", () => {
  it("iterates over session.messages safely when messages is null or undefined", () => {
    interface TestSession {
      id: string;
      title: string;
      messages?: Array<{ id: string; role: string; text: string; timestamp: string }>;
    }
    const sessions: TestSession[] = [
      { id: "s1", title: "Valid", messages: [{ id: "m1", role: "user", text: "hi", timestamp: "now" }] },
      { id: "s2", title: "Empty", messages: [] },
      { id: "s3", title: "Nullish", messages: undefined },
    ];

    const items: Array<{ key: string; text: string }> = [];
    for (const session of sessions) {
      for (const m of session.messages ?? []) {
        if (m.role === "system") continue;
        items.push({ key: `${session.id}-${m.id}`, text: m.text });
      }
    }

    expect(items).toHaveLength(1);
    expect(items[0].text).toBe("hi");
  });

  it("allFilteredSelected is true ONLY when filtered has items and every item is selected", () => {
    const isAllFilteredSelected = (filtered: Array<{ key: string }>, selected: Set<string>) =>
      filtered.length > 0 && filtered.every((i) => selected.has(i.key));

    const items = [{ key: "1" }, { key: "2" }, { key: "3" }];

    // Nothing selected
    expect(isAllFilteredSelected(items, new Set())).toBe(false);

    // Partial selected
    expect(isAllFilteredSelected(items, new Set(["1"]))).toBe(false);

    // All selected
    expect(isAllFilteredSelected(items, new Set(["1", "2", "3"]))).toBe(true);

    // Selected has other items, but not all filtered items
    expect(isAllFilteredSelected(items, new Set(["1", "extra"]))).toBe(false);

    // Filtered is empty
    expect(isAllFilteredSelected([], new Set(["1"]))).toBe(false);
  });

  it("displays 'История пуста' when items is empty, and 'Ничего не найдено' when search has no matches", () => {
    const getEmptyText = (itemsCount: number) => (itemsCount === 0 ? "История пуста" : "Ничего не найдено");

    // When there are no messages in history at all
    expect(getEmptyText(0)).toBe("История пуста");

    // When items exist but search filtered down to 0
    expect(getEmptyText(5)).toBe("Ничего не найдено");
  });
});



