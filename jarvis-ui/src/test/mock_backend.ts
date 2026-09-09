/**
 * Mock Backend Harness for UI Integration & User Journey Tests.
 *
 * Intercepts Tauri IPC (`invoke`, `listen`, `emit`) to simulate realistic backend
 * responses, streaming deltas, tool results, and error conditions.
 */
import { vi } from "vitest";

export interface MockMessageReply {
  text: string;
  tools?: Array<{ name: string; args: Record<string, unknown>; output: string }>;
  error?: string;
  delayMs?: number;
}

const listeners = new Map<string, Set<(event: { payload: unknown }) => void>>();
const invokeCalls: Array<{ cmd: string; args?: Record<string, unknown> }> = [];

let nextReply: MockMessageReply | null = null;
let backendRunning = true;
let backendConnected = true;
let failConfigure: string | null = null;

export const mockBackend = {
  get invokeCalls() {
    return invokeCalls;
  },
  get backendRunning() {
    return backendRunning;
  },
  set backendRunning(v: boolean) {
    backendRunning = v;
  },
  get backendConnected() {
    return backendConnected;
  },
  set backendConnected(v: boolean) {
    backendConnected = v;
  },
  get failConfigure() {
    return failConfigure;
  },
  set failConfigure(v: string | null) {
    failConfigure = v;
  },

  reset() {
    invokeCalls.length = 0;
    listeners.clear();
    nextReply = null;
    backendRunning = true;
    backendConnected = true;
    failConfigure = null;
  },

  emit(eventName: string, payload: unknown): void {
    const handlers = listeners.get(eventName);
    if (handlers) {
      for (const fn of handlers) {
        fn({ payload });
      }
    }
  },

  queueReply(reply: MockMessageReply): void {
    nextReply = reply;
  },
};

async function handleInvoke(cmd: string, args?: Record<string, unknown>): Promise<unknown> {
  invokeCalls.push({ cmd, args });

  if (cmd === "backend_status") {
    return { running: backendRunning, connected: backendConnected };
  }

  if (cmd === "backend_configure") {
    if (failConfigure) {
      return { ok: false, error: failConfigure };
    }
    return { ok: true };
  }

  if (cmd === "backend_list_models") {
    return {
      ok: true,
      groups: [
        {
          provider: "ollama",
          models: ["qwen2.5:72b", "llama3.3:70b", "deepseek-r1:70b"],
        },
        {
          provider: "openai",
          models: ["gpt-4o", "gpt-4o-mini"],
        },
      ],
    };
  }

  if (cmd === "backend_timers") {
    return { ok: true, timers: [] };
  }

  if (cmd === "backend_clear_history") {
    return { ok: true };
  }

  if (cmd === "backend_switch_session" || cmd === "backend_delete_session" || cmd === "backend_purge_session") {
    return { ok: true };
  }

  if (cmd === "backend_toggle_continuous") {
    return { ok: true, continuous: Boolean(args?.enabled) };
  }

  if (cmd === "backend_send_message") {
    const reply = nextReply || {
      text: `Ответ Джарвиса на: "${(args?.message as string) || ""}"`,
    };

    if (reply.delayMs) {
      await new Promise((resolve) => setTimeout(resolve, reply.delayMs));
    }

    if (reply.error) {
      return { ok: false, error: reply.error };
    }

    // Simulate streaming deltas if text is present
    if (reply.text) {
      const chunks = reply.text.split(" ");
      for (const chunk of chunks) {
        mockBackend.emit("chat-stream", chunk + " ");
      }
    }

    // Simulate tool results if specified
    if (reply.tools) {
      for (const tool of reply.tools) {
        mockBackend.emit("chat-tool", JSON.stringify({ name: tool.name, args: tool.args }));
        mockBackend.emit("chat-tool-result", JSON.stringify({ name: tool.name, output: tool.output }));
      }
    }

    return { ok: true, text: reply.text };
  }

  return { ok: true };
}

// Top-level Vitest module mocks
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (cmd: string, args?: Record<string, unknown>) => handleInvoke(cmd, args),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: (eventName: string, handler: (event: { payload: unknown }) => void) => {
    if (!listeners.has(eventName)) {
      listeners.set(eventName, new Set());
    }
    listeners.get(eventName)!.add(handler);
    return Promise.resolve(() => {
      listeners.get(eventName)?.delete(handler);
    });
  },
  emit: (eventName: string, payload: unknown) => {
    mockBackend.emit(eventName, payload);
    return Promise.resolve();
  },
}));
