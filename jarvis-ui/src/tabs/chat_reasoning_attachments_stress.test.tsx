// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockBackend } from "../test/mock_backend";
import ChatTab, { ThinkingBlock } from "./ChatTab";
import * as backendModule from "../api/backend";

describe("Frontend ThinkingBlock Adversarial Stress Tests", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("handles empty thinking strings cleanly both during live and finished states", () => {
    // 1. Live state with empty thinking
    render(<ThinkingBlock thinking="" isLive={true} duration={0} />);
    expect(screen.getByText("формирование мыслей...")).toBeTruthy();
    expect(screen.getByText(/думает \([0-9]+ сек\)\.\.\./i)).toBeTruthy();

    // 2. Newly mounted finished state with empty thinking (as in MessageBubble for past messages)
    cleanup();
    render(<ThinkingBlock thinking="" isLive={false} duration={0} />);
    expect(screen.getByText(/Размышления \([0-9]+ сек\)/)).toBeTruthy();
    expect(screen.queryByText("(нет записей)")).toBeNull();

    // Click to expand finished empty card
    const toggleBtn = screen.getByTitle("Показать размышления");
    fireEvent.click(toggleBtn);
    expect(screen.getByText("(нет записей)")).toBeTruthy();
    expect(screen.getByTitle("Скрыть размышления")).toBeTruthy();
  });

  it("preserves user manual collapse state during live streaming without re-opening on next delta", () => {
    const { rerender } = render(
      <ThinkingBlock thinking="Часть 1: анализ вопроса" isLive={true} duration={0} />,
    );

    // Live is open by default
    expect(screen.getByText("Часть 1: анализ вопроса")).toBeTruthy();

    // User manually clicks to collapse the live thinking block
    const collapseBtn = screen.getByTitle("Скрыть размышления");
    fireEvent.click(collapseBtn);

    // Now text container is hidden
    expect(screen.queryByText("Часть 1: анализ вопроса")).toBeNull();

    // Next chunk arrives while still isLive (duration stays 0 as in real ChatTab streaming)
    rerender(
      <ThinkingBlock thinking="Часть 1: анализ вопроса... Часть 2: проверка" isLive={true} duration={0} />,
    );

    // It should REMAIN collapsed (user preference honored)
    expect(screen.queryByText(/Часть 2: проверка/)).toBeNull();
    expect(screen.getByTitle("Показать размышления")).toBeTruthy();

    // User can re-open manually
    fireEvent.click(screen.getByTitle("Показать размышления"));
    expect(screen.getByText("Часть 1: анализ вопроса... Часть 2: проверка")).toBeTruthy();
  });

  it("auto-scrolls pre container when new thinking deltas arrive while open and live", () => {
    const { rerender } = render(
      <ThinkingBlock thinking="Начало рассуждения" isLive={true} duration={1} />,
    );

    const pre = screen.getByText("Начало рассуждения") as HTMLPreElement;
    expect(pre).toBeTruthy();

    // Mock scrollHeight and scrollTop
    Object.defineProperty(pre, "scrollHeight", { value: 1200, configurable: true, writable: true });
    pre.scrollTop = 0;

    // Receive new thinking chunk
    rerender(
      <ThinkingBlock thinking="Начало рассуждения\nПродолжение рассуждения" isLive={true} duration={2} />,
    );

    // Verify scrollTop was updated to scrollHeight
    expect(pre.scrollTop).toBe(1200);
  });

  it("repeatedly toggles open and close with correct chevron orientation and labels", async () => {
    const user = userEvent.setup();
    render(<ThinkingBlock thinking="Многошаговый план решения задачи" isLive={false} duration={12} />);

    expect(screen.getByText("Размышления (12 сек)")).toBeTruthy();
    expect(screen.queryByText("Многошаговый план решения задачи")).toBeNull();

    for (let i = 0; i < 3; i++) {
      // Open
      await user.click(screen.getByTitle("Показать размышления"));
      expect(screen.getByText("Многошаговый план решения задачи")).toBeTruthy();

      // Close
      await user.click(screen.getByTitle("Скрыть размышления"));
      expect(screen.queryByText("Многошаговый план решения задачи")).toBeNull();
    }
  });
});

describe("Thinking Duration & Message Interface Lifecycle", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("calculates minimum 1 second duration for sub-second rapid thinking phase", async () => {
    render(<ChatTab />);

    mockBackend.queueReply({
      text: "Быстрый ответ.",
      delayMs: 50,
    });

    const input = screen.getByPlaceholderText("Написать сообщение...");
    const sendBtn = screen.getByTitle("Отправить");

    fireEvent.change(input, { target: { value: "Быстрый вопрос" } });
    fireEvent.click(sendBtn);

    // Emit thinking event immediately
    act(() => {
      mockBackend.emit("chat-thinking", "Мгновенная мысль.");
    });

    await waitFor(() => {
      expect(screen.getByText(/Мгновенная мысль\./)).toBeTruthy();
    });

    // Emit stream response immediately
    act(() => {
      mockBackend.emit("chat-stream", "Быстрый ответ.");
    });

    // Wait for message completion
    await waitFor(() => {
      expect(screen.getByText(/Размышления \(1 сек\)/)).toBeTruthy();
    });
  });

  it("persists thinking and thinkingDuration with the completed assistant message", async () => {
    render(<ChatTab />);

    mockBackend.queueReply({
      text: "Итоговый результат расчета.",
      delayMs: 100,
    });

    const input = screen.getByPlaceholderText("Написать сообщение...");
    const sendBtn = screen.getByTitle("Отправить");

    fireEvent.change(input, { target: { value: "Посчитай факториал" } });
    fireEvent.click(sendBtn);

    act(() => {
      mockBackend.emit("chat-thinking", "Шаг 1: N=5. Шаг 2: 5*4*3*2*1=120.");
    });

    await waitFor(() => {
      expect(screen.getByText(/Шаг 1: N=5/)).toBeTruthy();
    });

    // Wait for reply completion
    await waitFor(() => {
      expect(screen.getAllByText("Итоговый результат расчета.").length).toBeGreaterThanOrEqual(1);
    });

    // Check localStorage persistence (wait for the sessions effect to flush)
    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem("jarvis.ui.chats") || "[]");
      const lastMsg = saved[0]?.messages?.find((m: { role: string }) => m.role === "assistant");
      expect(lastMsg).toBeDefined();
    });

    const saved = JSON.parse(localStorage.getItem("jarvis.ui.chats") || "[]");
    const lastMsg = saved[0].messages.find((m: { role: string }) => m.role === "assistant");
    expect(lastMsg.thinking).toContain("5*4*3*2*1=120");
    expect(lastMsg.thinkingDuration).toBeGreaterThanOrEqual(1);
  });
});

describe("File & Image Attachments Protocol Stress Tests", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("robustly handles nested drag enter and drag leave without prematurely dismissing overlay", () => {
    render(<ChatTab />);

    const chatContainer = screen.getByText("Новый чат").closest(".overflow-hidden") as HTMLElement;
    expect(chatContainer).toBeTruthy();

    // 1. Drag enter on root container
    fireEvent.dragEnter(chatContainer, {
      dataTransfer: { items: [{ kind: "file", type: "text/plain" }] },
    });
    expect(screen.getByTestId("dropzone-overlay")).toBeTruthy();

    // 2. Drag enter on child element (counter = 2)
    fireEvent.dragEnter(screen.getByTestId("dropzone-overlay"), {
      dataTransfer: { items: [{ kind: "file", type: "text/plain" }] },
    });
    expect(screen.getByTestId("dropzone-overlay")).toBeTruthy();

    // 3. Drag leave from child element (counter = 1) -> overlay MUST remain visible
    fireEvent.dragLeave(screen.getByTestId("dropzone-overlay"));
    expect(screen.getByTestId("dropzone-overlay")).toBeTruthy();

    // 4. Drag leave from root container (counter = 0) -> overlay closes
    fireEvent.dragLeave(chatContainer);
    expect(screen.queryByTestId("dropzone-overlay")).toBeNull();
  });

  it("handles dropping multiple mixed files (images + code + text), renders previews, and removes specific items", async () => {
    render(<ChatTab />);

    const chatContainer = screen.getByText("Новый чат").closest(".overflow-hidden") as HTMLElement;

    const img1 = new File(["fake-png-1"], "diagram.png", { type: "image/png" });
    const img2 = new File(["fake-jpg-2"], "photo.jpg", { type: "image/jpeg" });
    const pyFile = new File(["def add(a, b): return a + b"], "calc.py", { type: "text/x-python" });
    const rsFile = new File(["fn main() {}"], "lib.rs", { type: "text/x-rust" });
    const jsonFile = new File(['{"ok": true}'], "config.json", { type: "application/json" });

    // Drop all 5 files at once
    fireEvent.drop(chatContainer, {
      dataTransfer: {
        files: [img1, img2, pyFile, rsFile, jsonFile],
      },
    });

    // Previews should appear for all files
    await waitFor(() => {
      expect(screen.getByTestId("attachments-preview")).toBeTruthy();
      expect(screen.getByAltText("diagram.png")).toBeTruthy();
      expect(screen.getByAltText("photo.jpg")).toBeTruthy();
      expect(screen.getByText("calc.py")).toBeTruthy();
      expect(screen.getByText("lib.rs")).toBeTruthy();
      expect(screen.getByText("config.json")).toBeTruthy();
    });

    // Remove one image (diagram.png)
    const removeImgBtn = screen.getByLabelText("Удалить diagram.png");
    fireEvent.click(removeImgBtn);

    expect(screen.queryByAltText("diagram.png")).toBeNull();
    // photo.jpg and code files should remain
    expect(screen.getByAltText("photo.jpg")).toBeTruthy();
    expect(screen.getByText("calc.py")).toBeTruthy();

    // Remove one code file (lib.rs)
    const removeRsBtn = screen.getByLabelText("Удалить lib.rs");
    fireEvent.click(removeRsBtn);

    expect(screen.queryByText("lib.rs")).toBeNull();
    expect(screen.getByText("calc.py")).toBeTruthy();
    expect(screen.getByText("config.json")).toBeTruthy();
  });

  it("formats various file extensions correctly into markdown code blocks (.py, .rs, .json, .md, .log, .txt, .sh, .toml, .yaml)", async () => {
    const sendSpy = vi.spyOn(backendModule, "sendBackendMessage").mockResolvedValue("Все файлы получены.");

    render(<ChatTab />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;

    const files = [
      new File(["import os\nprint(os.name)"], "script.py", { type: "text/x-python" }),
      new File(["pub fn hello() -> &'static str { \"hi\" }"], "mod.rs", { type: "text/x-rust" }),
      new File(['{\n  "version": "1.0"\n}'], "manifest.json", { type: "application/json" }),
      new File(["# Documentation\nThis is a test doc."], "README.md", { type: "text/markdown" }),
      new File(["[2026-09-20] INFO: Server started"], "access.log", { type: "text/plain" }),
      new File(["Hello world plain text"], "notes.txt", { type: "text/plain" }),
      new File(["#!/bin/bash\necho test"], "run.sh", { type: "application/x-sh" }),
      new File(['[package]\nname = "test"'], "Cargo.toml", { type: "text/plain" }),
      new File(["version: '3'\nservices:\n  app: {}"], "docker-compose.yaml", { type: "text/yaml" }),
      new File(["SELECT * FROM users;"], "query.sql", { type: "text/sql" }),
      new File(["unknown syntax"], "custom.xyz", { type: "text/plain" }),
    ];

    fireEvent.change(fileInput, { target: { files } });

    await waitFor(() => {
      expect(screen.getByText("script.py")).toBeTruthy();
      expect(screen.getByText("docker-compose.yaml")).toBeTruthy();
    });

    const sendBtn = screen.getByTitle("Отправить");
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(sendSpy).toHaveBeenCalled();
    });

    const [messagePayload] = sendSpy.mock.calls[0];

    // Verify language mappings in markdown blocks
    expect(messagePayload).toContain("### Файл: script.py\n```python\nimport os\nprint(os.name)\n```");
    expect(messagePayload).toContain("### Файл: mod.rs\n```rust\npub fn hello()");
    expect(messagePayload).toContain("### Файл: manifest.json\n```json\n{\n  \"version\": \"1.0\"\n}\n```");
    expect(messagePayload).toContain("### Файл: README.md\n```markdown\n# Documentation");
    expect(messagePayload).toContain("### Файл: access.log\n```text\n[2026-09-20] INFO: Server started\n```");
    expect(messagePayload).toContain("### Файл: notes.txt\n```text\nHello world plain text\n```");
    expect(messagePayload).toContain("### Файл: run.sh\n```bash\n#!/bin/bash");
    expect(messagePayload).toContain("### Файл: Cargo.toml\n```toml\n[package]");
    expect(messagePayload).toContain("### Файл: docker-compose.yaml\n```yaml\nversion: '3'");
    expect(messagePayload).toContain("### Файл: query.sql\n```sql\nSELECT * FROM users;\n```");
    expect(messagePayload).toContain("### Файл: custom.xyz\n```xyz\nunknown syntax\n```");

    sendSpy.mockRestore();
  });

  it("handles image-only message: encodes to base64, passes to backend, and displays thumbnail in chat", async () => {
    const sendSpy = vi.spyOn(backendModule, "sendBackendMessage").mockResolvedValue("Изображение проанализировано.");

    render(<ChatTab />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const imgFile = new File(["raw-png-data"], "screenshot.png", { type: "image/png" });

    fireEvent.change(fileInput, { target: { files: [imgFile] } });

    await waitFor(() => {
      expect(screen.getByAltText("screenshot.png")).toBeTruthy();
    });

    // Text input is empty, but send button is enabled because attachment exists
    const input = screen.getByPlaceholderText("Написать сообщение...") as HTMLInputElement;
    expect(input.value).toBe("");
    const sendBtn = screen.getByTitle("Отправить") as HTMLButtonElement;
    expect(sendBtn.disabled).toBe(false);

    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(sendSpy).toHaveBeenCalled();
    });

    const [sentText, , sentImages] = sendSpy.mock.calls[0];
    // Sent text is empty string (no user text entered)
    expect(sentText).toBe("");
    // Images array contains base64 string
    expect(sentImages).toBeDefined();
    expect(sentImages!.length).toBe(1);
    expect(sentImages![0]).toContain("data:image/png;base64,");

    // Chat history should render user message with image thumbnail and "Изображение" label
    await waitFor(() => {
      expect(screen.getByAltText("Прикреплённое изображение 1")).toBeTruthy();
      expect(screen.getByText("Изображение")).toBeTruthy();
    });

    sendSpy.mockRestore();
  });
});
