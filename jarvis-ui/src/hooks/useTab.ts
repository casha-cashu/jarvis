import { useState, useCallback } from "react";

export type Tab = "chat" | "settings" | "status" | "history";

export function useTab(initial: Tab = "chat") {
  const getInitialTab = (): Tab => {
    if (typeof window !== "undefined") {
      const hash = window.location.hash.replace("#", "") as Tab;
      if (["chat", "settings", "status", "history"].includes(hash)) return hash;
      const params = new URLSearchParams(window.location.search);
      const tabParam = params.get("tab") as Tab;
      if (["chat", "settings", "status", "history"].includes(tabParam)) return tabParam;
    }
    return initial;
  };

  const [tab, setTabState] = useState<Tab>(getInitialTab);
  const change = useCallback((t: Tab) => {
    setTabState(t);
    if (typeof window !== "undefined") {
      window.location.hash = t;
    }
  }, []);
  return { tab, setTab: change };
}
