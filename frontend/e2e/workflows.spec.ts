// SPDX-License-Identifier: Apache-2.0
// Slice 4b in the browser: the list, the chooser and the canvas, behind nginx, under the served CSP, with axe.
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

async function newWorkflow(page: Page, name: string): Promise<void> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await expect(dialog.getByLabel("Name")).toBeFocused();
  await expectAccessible(page, "new workflow");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("button", { name: "Create and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
}

test("a blank workflow takes its first steps with a pointer, under the CSP", async ({ page }) => {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await expect(page.getByRole("heading", { level: 1, name: "Workflows" })).toBeVisible();
  await expectAccessible(page, "workflows");
  await newWorkflow(page, "Pointer flow");
  await expect(page.getByRole("button", { name: /^Start, where every run begins/ })).toBeVisible();
  await expectAccessible(page, "editor: blank");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByRole("button", { name: /^transform, Transform/ })).toBeFocused();
  await page.getByRole("button", { name: "Add a step after transform" }).click();
  await page.getByRole("option", { name: /flow\.if@1/ }).click();
  await page.getByRole("button", { name: "Add a step after if (true)" }).click();
  await page.getByRole("option", { name: /flow\.stop@1/ }).click();
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  await page.getByRole("button", { name: "Insert a step between transform and if" }).click();
  await expect(page.getByText("Only steps that continue the flow can go here.")).toBeVisible();
  await page.getByRole("option", { name: /flow\.delay@1/ }).click();
  await expect(page.getByRole("button", { name: /^delay, Delay/ })).toBeVisible();
  await page.getByRole("button", { name: "Auto layout" }).click();
  await expectAccessible(page, "editor: four steps");
});

test("a workflow built with the keyboard alone: Tab in, arrows along the edges, A, Delete, undo", async ({ page }) => {
  await newWorkflow(page, "Keyboard flow");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.type("transform");
  await page.keyboard.press("Enter");
  const transform = page.getByRole("button", { name: /^transform, Transform/ });
  await expect(transform).toBeFocused();
  await page.keyboard.press("a");
  await page.keyboard.type("flow.if");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^if, If/ })).toBeFocused();
  await page.keyboard.press("ArrowDown"); // the if step's free true port
  await expect(page.getByRole("button", { name: "Add a step after if (true)" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "Add a step after if (false)" })).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.type("stop");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeFocused();
  await page.keyboard.press("ArrowUp"); // the edge from if's false port
  await expect(page.getByRole("button", { name: "Insert a step between if and stop" })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(start).toBeFocused();
  // Tab leaves the canvas at once: one tab stop.
  await page.keyboard.press("Tab");
  await expect(page.locator("[data-item]:focus")).toHaveCount(0);
  await page.keyboard.press("Shift+Tab");
  await expect(start).toBeFocused();
  // Delete asks first; Escape keeps the step; undo brings back what Delete removed.
  await page.getByRole("button", { name: /^stop, Stop/ }).focus();
  await page.keyboard.press("Delete");
  const ask = page.getByRole("dialog", { name: "Delete a step" });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "editor: delete a step");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toHaveCount(0);
  // Focus goes to the step it came after, once drawn (a frame later); the editor hears Control+z from there.
  await expect(page.getByRole("button", { name: /^if, If/ })).toBeFocused();
  await page.keyboard.press("Control+z");
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  // Enter opens a step's panel; Escape gives focus back.
  await transform.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 2, name: "transform" })).toBeFocused();
  await expectAccessible(page, "editor: step panel");
  await page.keyboard.press("Escape");
  await expect(transform).toBeFocused();
});

test("a step is placed with single clicks, never a drag (WCAG 2.5.7)", async ({ page }) => {
  await newWorkflow(page, "Placed flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  const card = page.getByRole("button", { name: /^transform, Transform/ });
  await card.click(); // its panel
  await page.getByRole("button", { name: "Place on the canvas…" }).click();
  await expect(page.getByText("Click an empty place on the canvas to put transform there.")).toBeVisible();
  await expectAccessible(page, "editor: placing a step");
  // An empty place: the canvas's top right, clear of the cards (fitted to its middle), the minimap (bottom right)
  // and the zoom controls (bottom left).
  const pane = (await page.locator(".react-flow__pane").boundingBox())!;
  const target = { x: pane.x + pane.width * 0.85, y: pane.y + pane.height * 0.2 };
  await page.mouse.click(target.x, target.y);
  await expect(card).toBeFocused();
  const placed = (await card.boundingBox())!;
  expect(Math.abs(placed.x + placed.width / 2 - target.x)).toBeLessThan(4);
  expect(Math.abs(placed.y + placed.height / 2 - target.y)).toBeLessThan(4);
  // Its panel's buttons move it a step at a time.
  await card.click();
  await page.getByRole("button", { name: "Move transform left" }).click();
  await expect.poll(async () => (await card.boundingBox())!.x).toBeLessThan(placed.x);
});

async function importFile(page: Page, name: string, file: string): Promise<void> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles(file);
  await expect(dialog.getByText("The file names no connection or workflow.")).toBeVisible();
  await expectAccessible(page, "new workflow: import");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
}

test("the keys reach every step of an imported cycle no entry leads into", async ({ page }) => {
  await importFile(page, "Cycle", "e2e/fixtures/cycle.dewpoint.json");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Insert a step before entry" })).toBeFocused();
  await page.keyboard.press("ArrowRight"); // the cycle, linked under the start card
  await expect(page.getByRole("button", { name: /^a, Transform/ })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Insert a step between a and b" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: /^b, Transform/ })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Insert a step between b and a" })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(start).toBeFocused();
  await expectAccessible(page, "editor: an imported cycle");
});

test("an edge spelling its steps' ids otherwise is drawn, walked and deleted with them", async ({ page }) => {
  await importFile(page, "Aliases", "e2e/fixtures/aliases.dewpoint.json");
  // One entry (a), and the edge from a to b, though the edge spells their ids in capitals and without hyphens.
  await expect(page.getByRole("button", { name: "Insert a step before a" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Insert a step before b" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Insert a step between a and b" })).toHaveCount(1);
  const b = page.getByRole("button", { name: /^b, Transform/ });
  await b.focus();
  await page.keyboard.press("Delete");
  await page.getByRole("dialog", { name: "Delete a step" }).getByRole("button", { name: "Delete" }).click();
  await expect(b).toHaveCount(0);
  // Its edge went with it: a's port is free again.
  await expect(page.getByRole("button", { name: "Insert a step between a and b" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add a step after a" })).toHaveCount(1);
  await expectAccessible(page, "editor: an edge spelling ids otherwise");
});

test("undo and redo from the keyboard keep focus in the editor, never repaired by hand", async ({ page }) => {
  await newWorkflow(page, "Undo flow");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.type("transform");
  await page.keyboard.press("Enter");
  const transform = page.getByRole("button", { name: /^transform, Transform/ });
  await expect(transform).toBeFocused();
  await page.keyboard.press("Control+z"); // the step it was on is gone: focus goes back to the start card
  await expect(transform).toHaveCount(0);
  await expect(start).toBeFocused();
  await page.keyboard.press("Control+Shift+z");
  await expect(transform).toBeVisible();
  await expect(start).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(transform).toBeFocused(); // the keys still walk from where focus was kept
});
