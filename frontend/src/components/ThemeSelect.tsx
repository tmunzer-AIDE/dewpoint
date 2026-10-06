// SPDX-License-Identifier: Apache-2.0
// The theme (D6): the OS's by default, or light or dark, remembered in this browser only. A per-viewer convenience:
// storage may be unavailable, and the page then simply follows the OS.
import { useEffect, useState } from "react";

const KEY = "dewpoint.theme";
type Theme = "system" | "light" | "dark";

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

export function ThemeSelect() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    applyTheme(theme);
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      // storage refused: the choice lasts this page only
    }
  }, [theme]);
  return (
    <select
      aria-label="Theme"
      value={theme}
      onChange={(e) => setTheme(e.target.value as Theme)}
      className="min-h-9 rounded-lg border border-line-control bg-surface px-2 text-small text-ink"
    >
      <option value="system">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}
