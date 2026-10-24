// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockBackend } from "../test/mock_backend";
import ChatTab, { ThinkingBlock } from "./ChatTab";
import * as backendModule from "../api/backend";

describe("ThinkingBlock Component", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("renders live thinking state with animated badge, timer, and expanded preview", () => {
    render(<ThinkingBlock thinking="Анализирую архитектуру..." isLive={true} duration={3} />);

    // Live thinking badge
    expect(screen.getByText(/думает \(3 сек\)\.\.\./i)).toBeTruthy();
    // Thoughts text container is open
    expect(screen.getByText("Анализирую архитектуру...")).toBeTruthy();
  });

  it("increments timer while isLive is true", () => {
    vi.useFakeTimers();
    render(<ThinkingBlock thinking="Глубокое размышление..." isLive={true} duration={1} />);

    expect(screen.getByText(/думает \(1 сек\)\.\.\./i)).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getByText(/думает \(3 сек\)\.\.\./i)).toBeTruthy();
  });

  it("renders finished reasoning card collapsed by default and expands on click", async () => {
    const user = userEvent.setup();
    render(<ThinkingBlock thinking="План: 1. Проверить API. 2. Написать тесты." isLive={false} duration={5} />);

    // Collapsed header is visible
    expect(screen.getByText("Размышления (5 сек)")).toBeTruthy();
    // Pre container is not shown by default
    expect(screen.queryByText(/План: 1\. Проверить API/)).toBeNull();

    // Click to toggle
    const toggleButton = screen.getByTitle("Показать размышления");
    await user.click(toggleButton);

    // Now thoughts are expanded
    expect(screen.getByText(/План: 1\. Проверить API/)).toBeTruthy();

    // Click again to collapse
    await user.click(screen.getByTitle("Скрыть размышления"));
    expect(screen.queryByText(/План: 1\. Проверить API/)).toBeNull();
  });
});

describe("ChatTab Reasoning and Thinking Stream", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("accumulates chat-thinking stream and renders ThinkingBlock during streaming", async () => {
    render(<ChatTab />);

    // Simulate in-flight backend send with delay
    mockBackend.queueReply({
      text: "Конечный ответ помощника.",
      delayMs: 200,
    });

    const input = screen.getByPlaceholderText("Написать сообщение...");
    const sendBtn = screen.getByTitle("Отправить");

    fireEvent.change(input, { target: { value: "Вопрос с рассуждениями" } });
    fireEvent.click(sendBtn);

    // Emit live thinking delta
    act(() => {
      mockBackend.emit("chat-thinking", "Сначала вычисляем X... ");
    });

    // Verify thinking block appears
    await waitFor(() => {
      expect(screen.getByText(/думает/i)).toBeTruthy();
      expect(screen.getByText(/Сначала вычисляем X\.\.\./i)).toBeTruthy();
    });

    // Emit second thinking delta
    act(() => {
      mockBackend.emit("chat-thinking", "Затем вычисляем Y.");
    });

    await waitFor(() => {
      expect(screen.getByText(/Сначала вычисляем X\.\.\. Затем вычисляем Y\./i)).toBeTruthy();
    });

    // Wait for reply completion
    await waitFor(
      () => {
        expect(screen.getAllByText("Конечный ответ помощника.").length).toBeGreaterThanOrEqual(1);
      },
      { timeout: 1500 },
    );

    // After finish, reasoning should be displayed as collapsed card in assistant message
    expect(screen.getByText(/размышления/i)).toBeTruthy();
  });
});

describe("ChatTab Attachments and Drag & Drop", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("has a paperclip attachment button with accept filter", () => {
    render(<ChatTab />);

    const paperclipBtn = screen.getByRole("button", { name: /прикрепить файл/i });
    expect(paperclipBtn).toBeTruthy();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    expect(fileInput.accept).toBe("image/*,.txt,.py,.rs,.json,.md,.log,.pdf");
  });

  it("renders visual dropzone overlay during drag enter and hides on drag leave", () => {
    render(<ChatTab />);

    const chatContainer = screen.getByText("Новый чат").closest(".overflow-hidden") as HTMLElement;
    expect(chatContainer).toBeTruthy();

    // Drag enter with files
    fireEvent.dragEnter(chatContainer, {
      dataTransfer: { items: [{ kind: "file", type: "image/png" }] },
    });

    expect(screen.getByTestId("dropzone-overlay")).toBeTruthy();
    expect(screen.getByText(/перетащите файлы сюда/i)).toBeTruthy();

    // Drag leave
    fireEvent.dragLeave(chatContainer);
    expect(screen.queryByTestId("dropzone-overlay")).toBeNull();
  });

  it("allows attaching files via file picker, displays preview badges, and removes them", async () => {
    render(<ChatTab />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;

    const dummyFile = new File(["fn main() { println!(\"hello\"); }"], "main.rs", {
      type: "text/x-rust",
    });

    // Add file via input change
    act(() => {
      fireEvent.change(fileInput, {
        target: { files: [dummyFile] },
      });
    });

    // Preview badge should appear with filename
    await waitFor(() => {
      expect(screen.getByText("main.rs")).toBeTruthy();
    });

    // Remove file
    const removeBtn = screen.getByLabelText("Удалить main.rs");
    act(() => {
      fireEvent.click(removeBtn);
    });

    expect(screen.queryByTestId("attachments-preview")).toBeNull();
  });

  it("encodes images to base64 and formats text files as markdown code blocks on send", async () => {
    const sendSpy = vi.spyOn(backendModule, "sendBackendMessage").mockResolvedValue("Файлы приняты.");

    render(<ChatTab />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;

    // Create a text file and an image file
    const codeFile = new File(["print('hello world')"], "script.py", {
      type: "text/x-python",
    });
    const imageFile = new File(["fake-image-bytes"], "photo.png", {
      type: "image/png",
    });

    act(() => {
      fireEvent.change(fileInput, {
        target: { files: [codeFile, imageFile] },
      });
    });

    // Previews should appear
    await waitFor(() => {
      expect(screen.getByText("script.py")).toBeTruthy();
      expect(screen.getByAltText("photo.png")).toBeTruthy();
    });

    // Send without typing text (sending allowed when attachments exist)
    const sendBtn = screen.getByTitle("Отправить");
    expect((sendBtn as HTMLButtonElement).disabled).toBe(false);

    await act(async () => {
      fireEvent.click(sendBtn);
    });

    await waitFor(() => {
      expect(sendSpy).toHaveBeenCalled();
    });

    const [calledText, , calledImages] = sendSpy.mock.calls[0];

    // Verify markdown formatted code block was appended
    expect(calledText).toContain("### Файл: script.py");
    expect(calledText).toContain("```python");
    expect(calledText).toContain("print('hello world')");

    // Verify image was base64 encoded
    expect(calledImages).toBeDefined();
    expect(calledImages!.length).toBe(1);
    expect(calledImages![0]).toContain("data:image/png;base64,");

    // Preview bar should be cleared after send
    expect(screen.queryByTestId("attachments-preview")).toBeNull();
    expect(screen.queryByAltText("photo.png")).toBeNull();

    sendSpy.mockRestore();
  });
});

describe("ChatTab Reasoning Effort Controls & Model Capabilities", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders reasoning effort selector with default value and persists selection to localStorage", () => {
    render(<ChatTab />);

    const select = screen.getByTestId("reasoning-effort-select") as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect(select.value).toBe("medium");

    // Change to high
    fireEvent.change(select, { target: { value: "high" } });
    expect(select.value).toBe("high");
    expect(localStorage.getItem("jarvis.ui.reasoningEffort")).toBe("high");

    // Change to off
    fireEvent.change(select, { target: { value: "off" } });
    expect(select.value).toBe("off");
    expect(localStorage.getItem("jarvis.ui.reasoningEffort")).toBe("off");
  });

  it("does not render quick-toggle Brain button in bottom input bar and updates reasoning via header select", () => {
    render(<ChatTab />);

    // Quick-toggle Brain button has been removed from bottom input bar per user request
    expect(screen.queryByTestId("toggle-reasoning-btn")).toBeNull();

    const select = screen.getByTestId("reasoning-effort-select") as HTMLSelectElement;
    expect(select.value).toBe("medium");

    // Changing select switches medium -> off
    fireEvent.change(select, { target: { value: "off" } });
    expect(select.value).toBe("off");
    expect(localStorage.getItem("jarvis.ui.reasoningEffort")).toBe("off");

    // Changing select switches off -> high
    fireEvent.change(select, { target: { value: "high" } });
    expect(select.value).toBe("high");
    expect(localStorage.getItem("jarvis.ui.reasoningEffort")).toBe("high");
  });

  it("displays temperature input in header and saves changes", () => {
    render(<ChatTab />);

    const tempInput = screen.getByTestId("chat-temperature-input") as HTMLInputElement;
    expect(tempInput).toBeTruthy();
    expect(tempInput.value).toBe("0.7");

    fireEvent.change(tempInput, { target: { value: "0.2" } });
    fireEvent.blur(tempInput);

    expect(tempInput.value).toBe("0.2");
    expect(localStorage.getItem("jarvis.ui.temperature")).toBe("0.2");
  });

  it("forwards reasoningEffort to sendBackendMessage on user send", async () => {
    const sendSpy = vi.spyOn(backendModule, "sendBackendMessage").mockResolvedValue("Ответ получен.");

    render(<ChatTab />);

    const select = screen.getByTestId("reasoning-effort-select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "high" } });

    const input = screen.getByPlaceholderText("Написать сообщение...");
    const sendBtn = screen.getByTitle("Отправить");

    fireEvent.change(input, { target: { value: "Сложная математическая задача" } });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(sendSpy).toHaveBeenCalled();
    });

    const [calledText, , , calledEffort] = sendSpy.mock.calls[0];
    expect(calledText).toBe("Сложная математическая задача");
    expect(calledEffort).toBe("high");

    sendSpy.mockRestore();
  });

  it("renders model-specific reasoning options from activeCapability and disables controls when unsupported", async () => {
    // 1. Setup localStorage with a model that has custom reasoning efforts
    localStorage.setItem(
      "jarvis.ui.providers",
      JSON.stringify([
        {
          id: "p1",
          name: "Test Provider",
          type: "openai",
          endpoint: "https://api.test/v1",
          apiKey: "key",
        },
      ]),
    );
    localStorage.setItem(
      "jarvis.ui.models-cache",
      JSON.stringify({
        p1: [
          {
            provider: "Test",
            models: ["custom-toggle-model", "non-reasoning-model"],
            details: {
              "custom-toggle-model": {
                id: "custom-toggle-model",
                name: "Custom Toggle",
                reasoning: true,
                reasoningEfforts: ["off", "on"],
              },
              "non-reasoning-model": {
                id: "non-reasoning-model",
                name: "Non Reasoning",
                reasoning: false,
                reasoningEfforts: [],
              },
            },
          },
        ],
      }),
    );
    localStorage.setItem(
      "jarvis.ui.active-model",
      JSON.stringify({ providerId: "p1", model: "custom-toggle-model" }),
    );

    const { unmount } = render(<ChatTab />);

    const select = screen.getByTestId("reasoning-effort-select") as HTMLSelectElement;
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["off", "on"]);
    expect(select.disabled).toBe(false);

    unmount();

    // 2. Switch to non-reasoning model
    localStorage.setItem(
      "jarvis.ui.active-model",
      JSON.stringify({ providerId: "p1", model: "non-reasoning-model" }),
    );

    render(<ChatTab />);

    const selectDisabled = screen.getByTestId("reasoning-effort-select") as HTMLSelectElement;
    expect(selectDisabled.disabled).toBe(true);
    const disabledOptions = Array.from(selectDisabled.querySelectorAll("option")).map((o) => o.textContent);
    expect(disabledOptions).toContain("Мысли: Выкл");

    expect(screen.queryByTestId("toggle-reasoning-btn")).toBeNull();
  });
});

