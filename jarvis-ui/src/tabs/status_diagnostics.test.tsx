// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockBackend } from "../test/mock_backend";

// Import component after mocks
import StatusTab from "./StatusTab";

describe("StatusTab diagnostics report (PR-UI-OBS-1)", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("exports diagnostics and shows the bundle path", async () => {
    render(<StatusTab />);

    const button = await screen.findByRole("button", { name: /сформировать отчёт/i });
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));

    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText(/\/tmp\/jarvis-diagnostics-test\.zip/)).toBeTruthy();
    });
    const calls = mockBackend.invokeCalls.filter((c) => c.cmd === "backend_export_diagnostics");
    expect(calls).toHaveLength(1);
  });

  it("shows an error when diagnostics generation fails", async () => {
    mockBackend.failDiagnostics = "zip failed";
    render(<StatusTab />);

    const button = await screen.findByRole("button", { name: /сформировать отчёт/i });
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));

    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText("zip failed")).toBeTruthy();
    });
  });

  it("disables the button while backend is disconnected", async () => {
    mockBackend.backendConnected = false;
    render(<StatusTab />);

    const button = await screen.findByRole("button", { name: /сформировать отчёт/i });
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(true));
  });
});
