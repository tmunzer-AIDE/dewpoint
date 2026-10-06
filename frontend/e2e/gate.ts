// SPDX-License-Identifier: Apache-2.0
/* The browser gate (sub-project 4, slice 4a): every e2e test runs against the real app behind nginx, under its real
   CSP, and fails on a CSP violation, a console error, an uncaught page error or a request to another origin. Screens
   are checked against WCAG 2.2 AA with axe. Import `test` and `expect` from here, never from @playwright/test. */
import AxeBuilder from "@axe-core/playwright";
import { test as base, expect, type Page } from "@playwright/test";

declare global {
  interface Window {
    __dewpointCsp?: (violation: string) => void;
  }
}

/** The browser logs an API's 4xx answer as a console error; those answers are the app's contract (a wrong password,
 * a missing session), not a fault. 5xx answers, and everything else, stay problems. */
const EXPECTED_HTTP = /^Failed to load resource: the server responded with a status of 4\d\d\b/;

export interface Gate {
  /** What the gate has seen so far: each a short line naming its kind. */
  problems: string[];
  /** Forget what was seen: for the gate's own tests, which provoke problems on purpose. */
  clear(): void;
}

export const test = base.extend<{ gate: Gate }>({
  gate: [
    async ({ page, baseURL }, use) => {
      const problems: string[] = [];
      const origin = new URL(baseURL ?? "http://localhost").origin;
      await page.exposeFunction("__dewpointCsp", (v: string) => problems.push(`csp: ${v}`));
      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (e) =>
          window.__dewpointCsp?.(`${e.effectiveDirective} ${e.blockedURI || "inline"}`),
        );
      });
      page.on("console", (m) => {
        if (m.type() === "error" && !EXPECTED_HTTP.test(m.text())) problems.push(`console: ${m.text()}`);
      });
      page.on("pageerror", (e) => problems.push(`pageerror: ${e.name}: ${e.message}`));
      page.on("request", (r) => {
        const url = new URL(r.url());
        if (/^https?:$/.test(url.protocol) && url.origin !== origin) problems.push(`remote: ${url.origin}`);
      });
      await use({ problems, clear: () => void problems.splice(0) });
      expect(problems, "the browser gate: CSP violations, console or page errors, remote requests").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Axe's WCAG 2.2 AA violations on the page as it stands: rule, impact and how many elements. */
export async function axeViolations(page: Page): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze();
  return result.violations.map((v) => `${v.id} (${v.impact ?? "?"}): ${v.nodes.length} × ${v.nodes[0]?.target.join(" ")}`);
}

/** Fails the test if the screen breaks WCAG 2.2 AA. */
export async function expectAccessible(page: Page, screen: string): Promise<void> {
  expect(await axeViolations(page), `${screen}: WCAG 2.2 AA (axe)`).toEqual([]);
}
