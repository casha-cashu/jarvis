// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockBackend } from "../test/mock_backend";

// Import components after mocks
import SettingsTab from "./SettingsTab";
import ChatTab from "./ChatTab";
import { saveProviders } from "../api/providers";

describe("User Journey E2E Suite: Real User Scenarios & Error Modes", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    saveProviders([]);
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  // ── 1. Settings Journey ──────────────────────────────────────────────────
  describe("Journey 1: Settings → Adding and Validating an LLM Provider", () => {
    it("guides user through adding a provider, enforces validation, and saves", async () => {
      const user = userEvent.setup();
      render(<SettingsTab />);

      // User sees the settings page and clicks "Добавить"
      const addBtn = screen.getByRole("button", { name: /добавить/i });
      await user.click(addBtn);

      // Modal / inline form opens
      expect(screen.getByText("Новый провайдер")).toBeTruthy();

      // User tries to save without entering required fields
      const saveBtn = screen.getByRole("button", { name: /сохранить/i });
      await user.click(saveBtn);

      // Validation error should be displayed
      expect(screen.getByText(/укажите название провайдера/i)).toBeTruthy();

      // User enters provider name
      const nameInput = screen.getByPlaceholderText(/мой сервер llm/i);
      await user.type(nameInput, "Ollama Cloud");

      // User tries to save without endpoint
      await user.click(saveBtn);
      expect(screen.getByText(/укажите url эндпоинта/i)).toBeTruthy();

      // User enters endpoint URL
      const endpointInput = screen.getByPlaceholderText(/localhost:11434/i);
      await user.type(endpointInput, "http://localhost:11434/v1");

      // User clicks save
      await user.click(saveBtn);

      // Form should close and new provider should appear in the providers list
      await waitFor(() => {
        expect(screen.queryByText("Новый провайдер")).toBeNull();
      });

      expect(screen.getByText("Ollama Cloud")).toBeTruthy();
    });
  });

  // ── 2. Chat Journey: Message & Streaming ─────────────────────────────────
  describe("Journey 2: Chat → Sending messages and receiving streaming responses", () => {
    it("allows user to type a question and renders assistant reply", async () => {
      const user = userEvent.setup();
      render(<ChatTab />);

      const input = screen.getByPlaceholderText("Написать сообщение...");
      const sendBtn = screen.getByTitle("Отправить");

      // Initially input is empty and send button is disabled
      expect((sendBtn as HTMLButtonElement).disabled).toBe(true);

      // User types question
      await user.type(input, "Привет, Jarvis!");
      expect((sendBtn as HTMLButtonElement).disabled).toBe(false);

      // Setup assistant response
      mockBackend.queueReply({
        text: "Здравствуйте, сэр! Чем могу помочь?",
      });

      // User clicks send
      await user.click(sendBtn);

      // Input is immediately cleared
      expect((input as HTMLInputElement).value).toBe("");

      // User message should appear in chat
      await waitFor(() => {
        expect(screen.getAllByText("Привет, Jarvis!").length).toBeGreaterThanOrEqual(1);
      });

      // Assistant response should appear
      await waitFor(() => {
        expect(screen.getAllByText(/чем могу помочь/i).length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // ── 3. Chat Journey: Tool Execution Results ──────────────────────────────
  describe("Journey 3: Chat → Execution of System Commands & Tool Results", () => {
    it("renders tool call notification and tool execution result cards in the transcript", async () => {
      const user = userEvent.setup();
      render(<ChatTab />);

      const input = screen.getByPlaceholderText("Написать сообщение...");

      // User asks for system info which triggers tool execution
      mockBackend.queueReply({
        text: "Текущее время: 14:15:00.",
        tools: [
          {
            name: "get_current_time",
            args: {},
            output: "2026-09-09 14:15:00",
          },
        ],
      });

      await user.type(input, "Который час?{enter}");

      // Assistant text and tool output should both be rendered
      await waitFor(() => {
        expect(screen.getByText("get_current_time")).toBeTruthy();
        expect(screen.getAllByText(/текущее время: 14:15:00/i).length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // ── 4. Error Modes & Network Resilience ──────────────────────────────────
  describe("Journey 4: Resilience → Handling LLM Network and API Failures", () => {
    it("displays a clear error message when backend LLM fails and allows retrying", async () => {
      const user = userEvent.setup();
      render(<ChatTab />);

      const input = screen.getByPlaceholderText("Написать сообщение...");

      // Simulate an API rate limit or network failure
      mockBackend.queueReply({
        text: "",
        error: "Превышен лимит запросов (Rate limit exceeded)",
      });

      await user.type(input, "Сделай сложную задачу{enter}");

      // Error banner should be displayed to the user
      await waitFor(() => {
        expect(screen.getAllByText(/превышен лимит запросов/i).length).toBeGreaterThanOrEqual(1);
      });

      // User can clear input and type a new message without UI breaking
      mockBackend.queueReply({
        text: "Теперь всё в порядке.",
      });

      await user.clear(input);
      await user.type(input, "Попробуй снова{enter}");

      await waitFor(() => {
        expect(screen.getAllByText("Теперь всё в порядке.").length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  // ── 5. Stress Testing: Rapid Clicking & In-Flight Lock ───────────────────
  describe("Journey 5: Stress Testing → Double-click and Rapid Typing Protection", () => {
    it("locks the send button during in-flight requests and ignores spam clicks", async () => {
      render(<ChatTab />);

      const input = screen.getByPlaceholderText("Написать сообщение...");
      const sendBtn = screen.getByTitle("Отправить");

      // Set reply delay so request remains in-flight for 150ms
      mockBackend.queueReply({
        text: "Обработка завершена.",
        delayMs: 150,
      });

      fireEvent.change(input, { target: { value: "Тестовое сообщение" } });
      expect((input as HTMLInputElement).value).toBe("Тестовое сообщение");

      // First click sends message
      act(() => {
        fireEvent.click(sendBtn);
      });

      // Spam click immediately while request is in-flight
      act(() => {
        fireEvent.click(sendBtn);
        fireEvent.keyDown(input, { key: "Enter" });
      });

      // Exactly 1 message invocation should be registered
      const sendCalls = mockBackend.invokeCalls.filter(
        (c) => c.cmd === "backend_send_message"
      );
      expect(sendCalls.length).toBe(1);

      // Wait for completion
      await waitFor(
        () => {
          expect(screen.getAllByText("Обработка завершена.").length).toBeGreaterThanOrEqual(1);
        },
        { timeout: 1000 }
      );
    });
  });

  // ── 6. Session Management Journey ────────────────────────────────────────
  describe("Journey 6: Session Management → New Chat and Switching", () => {
    it("clears the active view when user starts a new chat", async () => {
      const user = userEvent.setup();
      render(<ChatTab />);

      const input = screen.getByPlaceholderText("Написать сообщение...");

      mockBackend.queueReply({
        text: "Первый разговор.",
      });

      await user.type(input, "Первое сообщение{enter}");

      await waitFor(() => {
        expect(screen.getAllByText("Первый разговор.").length).toBeGreaterThanOrEqual(1);
      });

      // Click "Новая сессия"
      const newSessionBtn = screen.getByTitle("Новая сессия");
      await user.click(newSessionBtn);

      // In the new session, the chat area shows the empty state placeholder
      await waitFor(() => {
        expect(screen.getByText(/напишите что-нибудь/i)).toBeTruthy();
      });
    });
  });
});
