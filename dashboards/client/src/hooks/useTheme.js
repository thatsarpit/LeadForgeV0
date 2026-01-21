import { useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "engyne_theme_mode";

function resolveAutoTheme(date = new Date()) {
  const hour = date.getHours();
  return hour >= 7 && hour < 19 ? "light" : "dark";
}

export default function useTheme() {
  const [mode, setMode] = useState(() => localStorage.getItem(STORAGE_KEY) || "auto");

  const theme = useMemo(() => {
    if (mode === "auto") {
      return resolveAutoTheme();
    }
    return mode;
  }, [mode]);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, mode);
  }, [mode]);

  useEffect(() => {
    if (mode !== "auto") return undefined;
    const timer = window.setInterval(() => {
      const next = resolveAutoTheme();
      document.documentElement.setAttribute("data-theme", next);
    }, 300000);
    return () => window.clearInterval(timer);
  }, [mode]);

  return { mode, setMode, theme };
}
