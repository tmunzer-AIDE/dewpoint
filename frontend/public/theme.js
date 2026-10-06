// SPDX-License-Identifier: Apache-2.0
// The remembered theme (components/ThemeSelect.tsx, key "dewpoint.theme"), applied before the first paint: a classic
// script in <head> blocks rendering; the app's bundle is a deferred module, so the OS's theme would paint first.
// Served from 'self' (script-src 'self'); no inline script.
try {
  const theme = localStorage.getItem("dewpoint.theme");
  if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
} catch {
  // No storage (a private window, blocked site data): the OS's theme stands.
}
