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
  await expect(page.getByRole("button", { name: "Insert a step between if (false) and stop" })).toBeFocused();
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

/** The JavaScript and CSS a page fetched while `act` ran, by file, with their sizes. */
async function assetsFetched(page: Page, act: () => Promise<void>): Promise<Map<string, number>> {
  const seen = new Map<string, number>();
  const pending: Promise<void>[] = [];
  const onResponse = (response: import("@playwright/test").Response) => {
    const path = new URL(response.url()).pathname;
    if (/\.(?:js|css)$/.test(path)) pending.push(response.body().then((b) => void seen.set(path, b.length)));
  };
  page.on("response", onResponse);
  await act();
  page.off("response", onResponse);
  await Promise.all(pending);
  return seen;
}

const EDITOR_CHUNK = /^\/assets\/Editor-[\w-]+\.(?:js|css)$/;

test("the list and sign-in load without the editor's code, which loads when a workflow opens", async ({ page, browser }) => {
  const total = (m: Map<string, number>) => [...m.values()].reduce((a, b) => a + b, 0);
  const list = await assetsFetched(page, async () => {
    await page.goto(`/t/${await tenantId(page)}/workflows`);
    await expect(page.getByRole("heading", { level: 1, name: "Workflows" })).toBeVisible();
  });
  expect([...list.keys()].filter((p) => EDITOR_CHUNK.test(p))).toEqual([]);
  const fresh = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const signIn = await fresh.newPage();
  const login = await assetsFetched(signIn, async () => {
    await signIn.goto("/login");
    await expect(signIn.getByRole("button", { name: /Sign in/ }).first()).toBeVisible();
  });
  await fresh.close();
  expect([...login.keys()].filter((p) => EDITOR_CHUNK.test(p))).toEqual([]);
  const opened = await assetsFetched(page, async () => {
    await page.getByRole("link", { name: "Cycle" }).click();
    await expect(page.getByRole("button", { name: /^Start, where every run begins/ })).toBeVisible();
  });
  expect([...opened.keys()].filter((p) => EDITOR_CHUNK.test(p)).length).toBe(2); // its script and its stylesheet
  console.log(`first load: list ${total(list)} bytes, sign-in ${total(login)} bytes; the editor adds ${total(opened)} bytes`);
});

/** Each control is clicked by a pointer (Playwright refuses a click another element would take), and no two overlap. */
async function eachReachableByPointer(page: Page, names: string[]): Promise<void> {
  const boxes = [];
  for (const name of names) {
    const control = page.getByRole("button", { name, exact: true });
    await control.click();
    await expect(page.getByRole("dialog", { name: "Add a step" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Add a step" })).toHaveCount(0);
    boxes.push((await control.boundingBox())!);
  }
  for (const [i, a] of boxes.entries()) {
    for (const b of boxes.slice(i + 1)) {
      const apart = a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
      expect(apart, "two controls overlap").toBe(true);
    }
  }
}

test("each edge's + is reachable by a pointer: reciprocal edges, and a join from two ports", async ({ page }) => {
  await importFile(page, "Reciprocal", "e2e/fixtures/cycle.dewpoint.json");
  await eachReachableByPointer(page, ["Insert a step between a and b", "Insert a step between b and a"]);
  await expectAccessible(page, "editor: reciprocal edges");
  await importFile(page, "Join", "e2e/fixtures/join.dewpoint.json");
  await eachReachableByPointer(page, ["Insert a step between if (true) and j", "Insert a step between if (false) and j"]);
  await expectAccessible(page, "editor: a join from two ports");
  // The same join climbing to a step above and to the right (the owner's review of 6d7766e): both edges run up the
  // same side, and their "+" must still sit apart.
  await importFile(page, "Join up", "e2e/fixtures/join-up.dewpoint.json");
  await eachReachableByPointer(page, ["Insert a step between if (true) and j", "Insert a step between if (false) and j"]);
  await expectAccessible(page, "editor: a join climbing from two ports");
});

test("zoomed out every way, a step stays a 24 px target, and each + has an unscaled twin in its panel (WCAG 2.5.8)", async ({ page }) => {
  await importFile(page, "Zoomed join", "e2e/fixtures/join-up.dewpoint.json");
  const card = page.getByRole("button", { name: /^if, If/ });
  await expect(card).toBeVisible();
  const tall = async () => expect((await card.boundingBox())!.height).toBeGreaterThanOrEqual(24);
  for (let i = 0; i < 12; i++) await page.getByRole("button", { name: "Zoom out" }).click();
  await tall();
  await page.getByRole("button", { name: "Fit" }).click();
  await tall();
  const pane = (await page.locator(".react-flow__pane").boundingBox())!;
  await page.mouse.move(pane.x + 40, pane.y + 40);
  for (let i = 0; i < 12; i++) await page.mouse.wheel(0, 600);
  await tall();
  // The canvas's "+" scale with it; its panel offers each of them at full size.
  await card.click();
  const panel = page.getByRole("complementary", { name: "if" });
  await panel.getByRole("button", { name: "Insert a step between if (false) and j", exact: true }).click();
  await page.getByRole("dialog", { name: "Add a step" }).getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByRole("button", { name: /^transform, Transform/ })).toHaveCount(1);
  await expectAccessible(page, "editor: zoomed out, a step's panel");
});

test("at 320 px a panel leaves the canvas room: Go to shows its step, and a step is placed with a click", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await newWorkflow(page, "Narrow flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  const problems = page.getByRole("button", { name: /^Problems · \d+$/ });
  await expect(problems).toBeVisible({ timeout: 10_000 });
  const step = page.getByRole("button", { name: /^transform, Transform, \d+ problems?/ });
  // Drag the canvas until the step is off it entirely.
  const canvas = page.getByRole("group", { name: "Workflow steps" });
  for (let i = 0; i < 4; i++) {
    const box = (await canvas.boundingBox())!;
    await page.mouse.move(box.x + box.width - 8, box.y + 8);
    await page.mouse.down();
    await page.mouse.move(box.x + 8, box.y + 8, { steps: 8 });
    await page.mouse.up();
  }
  await expect(step).not.toBeInViewport();
  await problems.click();
  const panel = page.getByRole("complementary", { name: "Problems" });
  await expect(panel).toBeVisible();
  expect((await canvas.boundingBox())!.width).toBeGreaterThan(200); // the panel leaves the canvas room
  await expectAccessible(page, "editor at 320 px: the problems panel");
  await panel.getByRole("button", { name: "Go to transform" }).click();
  await expect(step).toBeFocused();
  await expect(step).toBeInViewport({ ratio: 0.5 });
  // The canvas's own controls fit it (the final checkpoint's second review): nothing runs past its right edge.
  const frame = (await canvas.boundingBox())!;
  for (const control of [page.getByRole("button", { name: "Fit" }), page.getByText(/^\d+%$/)]) {
    const b = (await control.boundingBox())!;
    expect(b.x + b.width).toBeLessThanOrEqual(frame.x + frame.width);
  }
  // A step whose panel opens in the canvas's lower half stays in view as the panel takes that half.
  await panel.getByRole("button", { name: "Close" }).click(); // the canvas takes the height again
  await expect(panel).toHaveCount(0);
  const full = (await canvas.boundingBox())!;
  const card = (await step.boundingBox())!;
  const drop = full.y + full.height * 0.8 - (card.y + card.height / 2); // drag the step down to 80 % of the height
  await page.mouse.move(full.x + 8, full.y + 8);
  await page.mouse.down();
  await page.mouse.move(full.x + 8, full.y + 8 + drop, { steps: 8 });
  await page.mouse.up();
  await step.click();
  await expect(page.getByRole("complementary", { name: "transform" })).toBeVisible();
  await expect(step).toBeInViewport({ ratio: 0.9 });
  // Placed with a click at 320 px: the panel's Place, then a click on the canvas, where the step lands and shows.
  await page.getByRole("button", { name: "Place on the canvas…" }).click();
  // An empty place: the first point of a grid over the canvas where the pane itself, not a card or a control, is hit.
  const box = (await canvas.boundingBox())!;
  const grid = [0.5, 0.35, 0.65, 0.2, 0.8].flatMap((fy) => [0.5, 0.3, 0.7].map((fx) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy })));
  const hits = await page.evaluate((points) => points.map(({ x, y }) => document.elementFromPoint(x, y)?.classList.contains("react-flow__pane") ?? false), grid);
  const at = grid[hits.indexOf(true)]!;
  await page.mouse.click(at.x, at.y);
  await expect(page.getByText("Click an empty place on the canvas")).toHaveCount(0);
  await expect(step).toBeInViewport({ ratio: 0.5 });
  const placed = (await step.boundingBox())!;
  expect(Math.abs(placed.y + placed.height / 2 - at.y)).toBeLessThan(8); // centred on the click
  await page.setViewportSize({ width: 1280, height: 720 });
});

const overlaps = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

test("the minimap never hides what the keys reach, and gives way to a panel and to a narrow canvas", async ({ page }) => {
  await importFile(page, "Spread", "e2e/fixtures/spread.dewpoint.json");
  const minimap = page.locator(".react-flow__minimap");
  const far = page.getByRole("button", { name: /^far, Transform/ });
  await expect(minimap).toBeVisible();
  expect(overlaps((await far.boundingBox())!, (await minimap.boundingBox())!), "the fixture puts far under the minimap").toBe(true);
  await page.getByRole("button", { name: /^Start, where every run begins/ }).focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowDown");
  await expect(far).toBeFocused();
  await expect.poll(async () => overlaps((await far.boundingBox())!, (await minimap.boundingBox())!)).toBe(false);
  await page.keyboard.press("Enter"); // its panel: the minimap gives way
  await expect(page.getByRole("heading", { level: 2, name: "far" })).toBeFocused();
  await expect(minimap).toHaveCount(0);
  await expectAccessible(page, "editor: a panel, no minimap");
  await page.keyboard.press("Escape");
  await expect(minimap).toBeVisible();
  await page.setViewportSize({ width: 640, height: 720 }); // the canvas is narrower than the minimap allows
  await expect(minimap).toBeHidden();
  await expectAccessible(page, "editor: a narrow canvas");
  await page.setViewportSize({ width: 1280, height: 720 });
});

const importReport = (page: Page, name: string) => importFile(page, name, "e2e/fixtures/report.dewpoint.json");

test("edits save themselves and survive a reload; a step's problems show on it, and a problem focuses it", async ({ page }) => {
  await newWorkflow(page, "Saved flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  const problems = page.getByRole("button", { name: /^Problems · \d+$/ });
  await expect(problems).toBeVisible({ timeout: 10_000 });
  const step = page.getByRole("button", { name: /^transform, Transform, \d+ problems?/ });
  await expect(step).toBeVisible();
  await page.reload();
  await expect(step).toBeVisible(); // the server kept it
  await problems.click();
  const panel = page.getByRole("complementary", { name: "Problems" });
  await expect(panel.getByRole("heading", { name: "Problems" })).toBeFocused();
  await expectAccessible(page, "editor: problems");
  await panel.getByRole("button", { name: "Go to transform" }).first().click();
  await expect(step).toBeFocused();
});

test("a step a pointer sends focus to comes into view when it's off the canvas (WCAG 2.4.11)", async ({ page }) => {
  await newWorkflow(page, "Far flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  const problems = page.getByRole("button", { name: /^Problems · \d+$/ });
  await expect(problems).toBeVisible({ timeout: 10_000 });
  // Drag the canvas until the step is off it entirely.
  const step = page.getByRole("button", { name: /^transform, Transform, \d+ problems?/ });
  const pane = (await page.locator(".react-flow__pane").boundingBox())!;
  await page.mouse.move(pane.x + pane.width - 40, pane.y + 40);
  await page.mouse.down();
  await page.mouse.move(pane.x + pane.width - 1240, pane.y + 40, { steps: 12 });
  await page.mouse.up();
  await expect(step).not.toBeInViewport();
  // "Go to" with a pointer: focus lands on the step, and the step is where it can be seen.
  await problems.click();
  await page.getByRole("complementary", { name: "Problems" }).getByRole("button", { name: "Go to transform" }).click();
  await expect(step).toBeFocused();
  await expect(step).toBeInViewport();
});

test("publishing names the version; a version is viewed read only and made active", async ({ page }) => {
  await importReport(page, "Report A");
  await expect(page.getByRole("button", { name: "No problems" })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Publish v1" }).click();
  const ask = page.getByRole("dialog", { name: "Publish version 1" });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "editor: publish");
  await ask.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v1")).toBeVisible({ timeout: 10_000 });
  // A change makes it unpublished; publishing again makes version 2. A stop step may end a run before any step
  // finishes, so the fixture's output guards its read with has(), as publish requires.
  await page.getByRole("button", { name: "Add a step after t" }).click();
  await page.getByRole("option", { name: /flow\.stop@1/ }).click();
  await expect(page.getByText("Saved · unpublished changes since v1")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Publish v2" }).click();
  await page.getByRole("dialog", { name: "Publish version 2" }).getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v2")).toBeVisible({ timeout: 10_000 });
  // Version 1, read only: no stop step, nothing to add; then back, and version 1 made active.
  await page.getByRole("button", { name: "Versions" }).click();
  await expectAccessible(page, "editor: versions");
  await page.getByRole("button", { name: "View version 1" }).click();
  await expect(page.getByText("Viewing version 1, read only. The draft is unchanged.")).toBeVisible();
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Insert a step/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Back to the draft" }).click();
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  await page.getByRole("button", { name: "Versions" }).click();
  await page.getByRole("button", { name: "Make version 1 active" }).click();
  await page.getByRole("dialog", { name: "Make version 1 active" }).getByRole("button", { name: "Make active" }).click();
  await expect(page.getByText("Saved · unpublished changes since v1")).toBeVisible({ timeout: 10_000 });
  // The list agrees.
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  const row = page.getByRole("link", { name: "Report A" }).locator("xpath=ancestor::tr");
  await expect(row).toContainText("v1 · unpublished changes");
  await expect(row.getByRole("switch", { name: "Enable Report A" })).toBeVisible();
});

test("a draft changed elsewhere turns this editor read only, its work downloadable", async ({ page, context }) => {
  await importReport(page, "Report B");
  const other = await context.newPage();
  await other.goto(page.url());
  await expect(other.getByRole("button", { name: /^t, Transform/ })).toBeVisible();
  // This editor saves first: revision 2.
  await page.getByRole("button", { name: "Add a step after t" }).click();
  await page.getByRole("option", { name: /flow\.stop@1/ }).click();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  // The other, still at revision 1, is refused, and stops.
  await other.getByRole("button", { name: "Add a step after t" }).click();
  await other.getByRole("option", { name: /flow\.delay@1/ }).click();
  const alert = other.getByRole("alert");
  await expect(alert).toContainText("changed elsewhere", { timeout: 10_000 });
  await expect(other.getByRole("button", { name: /Add step/ })).toHaveCount(0);
  const download = other.waitForEvent("download");
  await alert.getByRole("button", { name: "Download my version" }).click();
  expect((await download).suggestedFilename()).toBe("report-b.draft.json");
  // Its unsaved version is guarded: leaving asks, and Reload asks before discarding it.
  await other.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Workflows" }).click();
  const leave = other.getByRole("dialog", { name: "Your latest changes aren't saved" });
  await expect(leave).toContainText("changed elsewhere");
  await expectAccessible(other, "editor: leaving unsaved work");
  await leave.getByRole("button", { name: "Stay" }).click();
  await alert.getByRole("button", { name: "Reload" }).click();
  await other.getByRole("dialog", { name: "Reload the saved draft" }).getByRole("button", { name: "Discard my version and reload" }).click();
  await expect(other.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  await expect(other.getByRole("button", { name: /^delay, Delay/ })).toHaveCount(0);
  await other.close();
});

test("a workflow exports to a file and imports back as a new one", async ({ page }, info) => {
  await importReport(page, "Report C");
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByRole("button", { name: "Actions for Report C" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Export" }).click();
  const file = info.outputPath("report-c.dewpoint.json");
  await (await download).saveAs(file);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill("Report C copy");
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles(file);
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Report C copy" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^t, Transform/ })).toBeVisible();
});

test("leaving through the breadcrumb saves the last edit first", async ({ page }) => {
  await newWorkflow(page, "Leaving flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByText("Unsaved changes")).toBeVisible(); // inside the second before it would save
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Workflows" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Workflows" })).toBeVisible();
  await page.getByRole("link", { name: "Leaving flow" }).click();
  await expect(page.getByRole("button", { name: /^transform, Transform/ })).toBeVisible(); // the server kept it
});

test("a publish names the version it makes, even when another lands first", async ({ page, context }) => {
  await importReport(page, "Report D");
  const other = await context.newPage();
  await other.goto(page.url());
  const publish = page.getByRole("button", { name: "Publish v1" });
  await expect(publish).toBeEnabled({ timeout: 10_000 });
  await publish.click();
  const ask = page.getByRole("dialog", { name: "Publish version 1" });
  await expect(ask).toBeVisible();
  // Meanwhile, the other editor publishes version 1.
  await other.getByRole("button", { name: "Publish v1" }).click();
  await other.getByRole("dialog", { name: "Publish version 1" }).getByRole("button", { name: "Publish" }).click();
  await expect(other.getByText("Saved · published as v1")).toBeVisible({ timeout: 10_000 });
  await other.close();
  // This one still names version 1: the server refuses it, and the editor asks again with the new number.
  await ask.getByRole("button", { name: "Publish" }).click();
  const again = page.getByRole("dialog", { name: "Publish version 2" });
  await expect(again).toContainText("Version 1 was published since you opened this", { timeout: 10_000 });
  await again.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v2")).toBeVisible({ timeout: 10_000 });
});

test("the list reflows at 320 px and stays AA (WCAG 1.4.10)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await expect(page.getByRole("link", { name: "Report A" })).toBeVisible();
  await expect(page.getByRole("note", { name: "Deployment" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "the workflows list scrolls sideways at 320 px").toBeLessThanOrEqual(0);
  await expectAccessible(page, "workflows at 320 px");
});
