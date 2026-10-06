// SPDX-License-Identifier: Apache-2.0
/* The gate's own tests: each provokes the problem it must catch, under the CSP nginx really serves, then clears it. */
import { axeViolations, expect, test } from "./gate";

test("the served CSP refuses an injected stylesheet, and the gate sees it", async ({ page, gate }) => {
  await page.goto("/login");
  await page.evaluate(() => {
    const style = document.createElement("style");
    style.textContent = "body { outline: 1px solid; }";
    document.head.append(style);
  });
  await expect.poll(() => gate.problems.join("\n")).toMatch(/csp: style-src/);
  gate.clear();
});

test("the served CSP refuses a request to another origin, and the gate sees it", async ({ page, gate }) => {
  await page.goto("/login");
  await page.evaluate(() => fetch("https://example.invalid/probe").catch(() => undefined));
  await expect.poll(() => gate.problems.join("\n")).toMatch(/csp: connect-src https:\/\/example\.invalid/);
  gate.clear();
});

test("a resource that fails to load is a problem, unlike an API's 4xx answer", async ({ page, gate }) => {
  await page.goto("/login");
  await page.evaluate(() => fetch("/assets/no-such-font.woff2").catch(() => undefined));
  await expect.poll(() => gate.problems.join("\n")).toMatch(/http 404: \/assets\/no-such-font\.woff2/);
  gate.clear();
  await page.evaluate(() => fetch("/api/v1/auth/session").catch(() => undefined)); // 401: the API's contract
  await page.waitForTimeout(300);
  expect(gate.problems).toEqual([]);
});

test("a 4xx console line is exempt only from the API: from anything else it is a problem", async ({ page, gate }) => {
  await page.goto("/login");
  await page.evaluate(() => console.error("Failed to load resource: the server responded with a status of 404 (Not Found)"));
  await expect.poll(() => gate.problems.join("\n")).toMatch(/console: Failed to load resource/);
  gate.clear();
});

test("axe reports text below 4.5:1", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => {
    const p = document.createElement("p");
    p.textContent = "Too faint to read";
    // The separator colour as text: 1.4:1 on the ground. Set through the CSSOM, which the CSP allows.
    p.style.color = getComputedStyle(document.documentElement).getPropertyValue("--line-strong");
    document.body.append(p);
  });
  expect((await axeViolations(page)).join("\n")).toMatch(/^color-contrast/m);
});
