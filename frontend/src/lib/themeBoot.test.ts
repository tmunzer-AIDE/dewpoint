// SPDX-License-Identifier: Apache-2.0
// The remembered theme is applied by a classic script in <head>, which blocks the first paint, not by the bundle,
// which is a deferred module: otherwise the OS's theme paints first and then flips.
import indexHtml from "../../index.html?raw";
import boot from "../../public/theme.js?raw";
import { afterEach, expect, it } from "vitest";

/** Runs `source` as a page script: jsdom runs it, as vitest configures jsdom. */
function page(source: string): void {
  const script = document.createElement("script");
  script.textContent = source;
  document.head.append(script);
  script.remove();
}
const run = () => page(boot);
// A page script sees the page's own storage, which the tests' global doesn't share under Node 26 (test/setup.ts): the
// tests remember a theme the way the app does, from the page.
const remember = (theme: string) => page(`localStorage.setItem("dewpoint.theme", ${JSON.stringify(theme)})`);

afterEach(() => {
  page("localStorage.clear()");
  document.documentElement.removeAttribute("data-theme");
});

it("applies a remembered light or dark theme", () => {
  remember("dark");
  run();
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
});

it("leaves the OS's theme alone when nothing, or nothing it knows, is remembered", () => {
  run();
  expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  remember("sepia");
  run();
  expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
});

it("runs before the bundle, as a render-blocking script in <head>", () => {
  const head = indexHtml.slice(0, indexHtml.indexOf("</head>"));
  expect(head).toMatch(/<script src="\/theme\.js"><\/script>/);
  expect(head).not.toMatch(/<script[^>]*src="\/theme\.js"[^>]*\b(?:defer|async|type="module")/);
});
