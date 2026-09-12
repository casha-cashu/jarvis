// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mockBackend } from "../test/mock_backend";

// Import component after mocks
import StatusTab from "./StatusTab";

describe("StatusTab VU-meter (PR-UI-VU-1)", () => {
  beforeEach(() => {
    mockBackend.reset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("does not render VU-meter when voice mode is off", async () => {
    render(<StatusTab />);

    await screen.findByRole("button", { name: /включить микрофон/i });
    expect(screen.queryByTestId("vu-meter-container")).toBeNull();
  });

  it("renders VU-meter and updates level when voice events arrive", async () => {
    render(<StatusTab />);

    const enableBtn = await screen.findByRole("button", { name: /включить микрофон/i });
    await waitFor(() => expect(enableBtn.hasAttribute("disabled")).toBe(false));

    // Enable voice mode by clicking button
    fireEvent.click(enableBtn);

    // Simulate backend listening event
    act(() => {
      mockBackend.emit("voice-event", JSON.stringify({ status: "listening", text: "Слушаю..." }));
    });

    await waitFor(() => {
      expect(screen.getByTestId("vu-meter-container")).toBeTruthy();
    });

    // Default level is 0%
    expect(screen.getByTestId("vu-meter-value").textContent).toBe("0%");

    // Emit audio_level event with level 0.45
    act(() => {
      mockBackend.emit("voice-event", JSON.stringify({ status: "audio_level", level: 0.45 }));
    });

    await waitFor(() => {
      expect(screen.getByTestId("vu-meter-value").textContent).toBe("45%");
      const bar = screen.getByTestId("vu-meter-bar");
      expect(bar.style.width).toBe("45%");
      expect(["#10b981", "rgb(16, 185, 129)"]).toContain(bar.style.backgroundColor);
    });

    // Emit clipping level 0.92
    act(() => {
      mockBackend.emit("voice-event", JSON.stringify({ status: "audio_level", level: 0.92 }));
    });

    await waitFor(() => {
      expect(screen.getByTestId("vu-meter-value").textContent).toBe("92%");
      const bar = screen.getByTestId("vu-meter-bar");
      expect(bar.style.width).toBe("92%");
      expect(["#ef4444", "rgb(239, 68, 68)"]).toContain(bar.style.backgroundColor);
    });

    // Simulate voice stopped event
    act(() => {
      mockBackend.emit("voice-event", JSON.stringify({ status: "stopped" }));
    });

    await waitFor(() => {
      expect(screen.queryByTestId("vu-meter-container")).toBeNull();
    });
  });
});
