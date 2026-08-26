import { useState, useCallback } from "react";

export type Tab = "chat" | "settings" | "status" | "history";

export function useTab(initial: Tab = "chat") {
  const [tab, setTab] = useState<Tab>(initial);
  const change = useCallback((t: Tab) => setTab(t), []);
  return { tab, setTab: change };
}
