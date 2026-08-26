import { useState, useCallback, useEffect } from "react";

export type Theme = "dark" | "light" | "system";

const THEME_KEY = "jarvis.ui.theme";

function resolveSystem(): "dark" | "light" {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyTheme(t: Theme) {
  const resolved = t === "system" ? resolveSystem() : t;
  document.documentElement.dataset.theme = resolved;
  if (resolved === "light") {
    document.documentElement.style.setProperty("--color-bg", "#f7f6f3");
    document.documentElement.style.setProperty("--color-surface", "#ffffff");
    document.documentElement.style.setProperty("--color-surface-2", "#f0efeb");
    document.documentElement.style.setProperty("--color-border", "#e5e5e3");
    document.documentElement.style.setProperty("--color-text", "#1a1a1c");
    document.documentElement.style.setProperty("--color-text-muted", "#6b6b70");
    document.documentElement.style.setProperty("--color-accent", "#2563eb");
    document.documentElement.style.setProperty("--color-accent-bg", "#dbeafe");
    document.documentElement.style.setProperty("--color-warn", "#d97706");
    document.documentElement.style.setProperty("--color-danger", "#dc2626");
  } else {
    document.documentElement.style.setProperty("--color-bg", "#0a0a0b");
    document.documentElement.style.setProperty("--color-surface", "#141417");
    document.documentElement.style.setProperty("--color-surface-2", "#1d1d20");
    document.documentElement.style.setProperty("--color-border", "#2a2a2e");
    document.documentElement.style.setProperty("--color-text", "#ededee");
    document.documentElement.style.setProperty("--color-text-muted", "#8a8a90");
    document.documentElement.style.setProperty("--color-accent-bg", "#1e3a5f");
    document.documentElement.style.setProperty("--color-warn", "#f59e0b");
    document.documentElement.style.setProperty("--color-danger", "#ef4444");
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    return (localStorage.getItem(THEME_KEY) as Theme) || "dark";
  });

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem(THEME_KEY, t);
    setThemeState(t);
    applyTheme(t);
  }, []);

  useEffect(() => {
    applyTheme(theme);
    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const handler = () => applyTheme("system");
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
  }, [theme]);

  return { theme, setTheme };
}
