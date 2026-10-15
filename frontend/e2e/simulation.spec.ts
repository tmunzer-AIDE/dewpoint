// SPDX-License-Identifier: Apache-2.0
// Slice 4d-1c in the browser (the simulation design §7, §8): Simulate workflow and Simulate step against the real stack,
// its dispatcher and worker, behind nginx, under the served CSP, with axe, light and dark, at 1280 and 320 px. Nothing
// leaves the stack (D24): the gate fails any request to another origin.
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** The simulation fixture, imported as a new workflow and opened on its canvas alone. */
async function importSimulate(page: Page, name: string): Promise<void> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/simulate.dewpoint.json");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  await page.goto(new URL(page.url()).pathname);
  await expect(page.getByRole("button", { name: "No problems" })).toBeVisible({ timeout: 10_000 });
}

/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
async function accessibleBothWays(page: Page, screen: string): Promise<void> {
  await expectAccessible(page, `${screen}, light`);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page, `${screen}, dark`);
  await page.emulateMedia({ colorScheme: "light" });
}

const tags = (page: Page, key: string) => page.getByRole("list", { name: `${key}: simulated result` });
const overlaps = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

test("a workflow is simulated from its toolbar: the result beside each step, and in the panel", async ({ page }) => {
  await importSimulate(page, "Simulate A");
  await page.getByRole("button", { name: "◌ Simulate workflow" }).click();
  const dialog = page.getByRole("dialog", { name: "Simulate workflow" });
  await dialog.getByLabel("Site required").fill("HQ Paris");
  await accessibleBothWays(page, "simulate: the input");
  await dialog.getByRole("button", { name: "◌ Simulate" }).click();
  const panel = page.getByRole("complementary", { name: "Simulation" });
  await expect(panel.getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 60_000 }); // the dispatcher, the worker, the end
  await expect(page.getByText("Simulated.", { exact: true }).first()).toBeVisible();
  await expect(tags(page, "greet")).toContainText("succeeded");
  await expect(tags(page, "check")).toContainText("evaluated · → true");
  await expect(tags(page, "long")).toContainText("succeeded");
  await expect(tags(page, "short")).toContainText("skipped");
  // `long` and `short` are 60 px apart: `long`'s tags go under it, never over `short` (the review's 1).
  const besideShort = (await tags(page, "long").boundingBox())!;
  const shortCard = (await page.getByRole("button", { name: /^short, Transform/ }).boundingBox())!;
  expect(overlaps(besideShort, shortCard)).toBe(false);
  await expect(panel.getByRole("region", { name: "Steps, in run order" })).toBeVisible();
  await expect(panel.getByRole("region", { name: "Input used" })).toContainText("HQ Paris");
  await accessibleBothWays(page, "simulate: the result");
  // Hidden: one bar, the simulation untouched; shown again.
  await page.getByRole("button", { name: "Hide the result" }).click();
  await expect(page.getByText(/^Simulation result hidden · Succeeded · revision \d+$/)).toBeVisible();
  await expect(tags(page, "greet")).toHaveCount(0);
  await page.getByRole("button", { name: "Show the result" }).click();
  await expect(tags(page, "greet")).toBeVisible();
});

test("a result after an edit says so, and a draft with problems isn't simulated (the Stale and Refusals boards)", async ({ page }) => {
  await importSimulate(page, "Simulate C");
  await page.getByRole("button", { name: "◌ Simulate workflow" }).click();
  const dialog = page.getByRole("dialog", { name: "Simulate workflow" });
  await dialog.getByLabel("Site required").fill("HQ Paris");
  await dialog.getByRole("button", { name: "◌ Simulate" }).click();
  await expect(page.getByRole("complementary", { name: "Simulation" }).getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 60_000 });
  // A step added after it: the result is from before the edit, the new step has none.
  await page.getByRole("button", { name: "Add a step after long" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByText(/^Before your edits: this result is for revision \d+; the draft is at revision \d+\.$/).first()).toBeVisible({ timeout: 10_000 });
  await expect(tags(page, "transform")).toContainText(/new since revision \d+: no result/);
  await accessibleBothWays(page, "simulate: a result after an edit");
  // The new step has problems: simulating the draft is refused, in the server's words.
  await page.getByRole("button", { name: "◌ Simulate workflow" }).click();
  await page.getByRole("dialog", { name: "Simulate workflow" }).getByLabel("Site required").fill("HQ Paris");
  await page.getByRole("dialog", { name: "Simulate workflow" }).getByRole("button", { name: "◌ Simulate" }).click();
  const panel = page.getByRole("complementary", { name: "Simulation" });
  await expect(panel.getByText(/^Fix \d+ problems? first: a draft with problems isn't simulated\.$/)).toBeVisible();
  await accessibleBothWays(page, "simulate: refused");
  await panel.getByRole("button", { name: "Show the problems" }).click();
  await expect(page.getByRole("complementary", { name: "Problems" })).toBeVisible();
});

test("a step is tested alone with its values, at 320 px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await importSimulate(page, "Simulate B");
  await page.getByRole("button", { name: /^greet, Transform/ }).click();
  const drawer = page.getByRole("complementary", { name: "greet" });
  await drawer.getByRole("tab", { name: "Test" }).click();
  await drawer.getByLabel("Site required text").fill("HQ Paris");
  await accessibleBothWays(page, "simulate step: the values, 320 px");
  await drawer.getByRole("button", { name: "◌ Simulate step" }).click();
  const result = drawer.getByRole("region", { name: "Result · greet" });
  await expect(result.getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(result.getByRole("region", { name: "Values used" })).toContainText("HQ Paris");
  await expect(result.getByRole("region", { name: "Output" })).toContainText("hello HQ Paris");
  await expect(page.getByText("Step test: greet.", { exact: true })).toBeVisible();
  await expect(tags(page, "check")).toHaveCount(0); // only the step tested carries a result
  await accessibleBothWays(page, "simulate step: the result, 320 px");
  await page.setViewportSize({ width: 1280, height: 720 });
});
