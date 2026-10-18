// SPDX-License-Identifier: Apache-2.0
// Slice 4e-1b in the browser (the runs design §5, §6): the Runs page and a run's page against the real stack, its
// dispatcher and worker, behind nginx, under the served CSP, with axe, light and dark, at 1280 and 320 px. The runs are
// seeded through the API: workflows of control steps only, run live (nothing leaves the stack, D24) and simulated, one
// failing at a `fail` step, a loop, and a run held by a delay to be cancelled. The gate fails any request to another
// origin.
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

const ENDED = new Set(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** The API as the web client calls it: an unsafe request names the client and carries the session's CSRF token.
 * Publishing names the draft's revision it publishes (`If-Match`, as the editor does); a start, its idempotency key. */
async function api(page: Page) {
  const tenant = await tenantId(page);
  const { csrf_token } = (await (await page.request.get("/api/v1/auth/session")).json()) as { csrf_token: string };
  const headers = { "X-Dewpoint-Client": "web", "X-CSRF-Token": csrf_token };
  const post = async (path: string, data: unknown, more: Record<string, string> = {}) => {
    const answer = await page.request.post(`/api/v1/t/${tenant}${path}`, { data, headers: { ...headers, ...more } });
    expect(answer.ok(), `POST ${path}: ${answer.status()}`).toBe(true);
    return (await answer.json()) as Record<string, unknown>;
  };
  return {
    tenant,
    /** A fixture imported under `name` and published: its workflow's id. */
    async publish(fixture: string, name: string): Promise<string> {
      const document = JSON.parse(readFileSync(`e2e/fixtures/${fixture}`, "utf8")) as unknown;
      const workflow = await post("/workflows/import", { name, document });
      await post(`/workflows/${String(workflow.id)}/publish`, { expected_latest_version: null }, { "If-Match": String(workflow.draft_revision) });
      return String(workflow.id);
    },
    /** A run started by hand: its id. */
    async start(workflowId: string, input: Record<string, unknown>, mode: "live" | "simulate" = "live"): Promise<string> {
      return String((await post(`/workflows/${workflowId}/runs`, { input, mode }, { "Idempotency-Key": crypto.randomUUID() })).id);
    },
    /** Waits for a run to end, as the dispatcher and the worker run it. */
    async ended(runId: string): Promise<void> {
      await expect
        .poll(async () => ENDED.has(((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status), { timeout: 60_000 })
        .toBe(true);
    },
    /** Waits for a run to be running. */
    async running(runId: string): Promise<void> {
      await expect
        .poll(async () => ((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status, { timeout: 60_000 })
        .toBe("running");
    },
  };
}

/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
async function accessibleBothWays(page: Page, screen: string): Promise<void> {
  await expectAccessible(page, `${screen}, light`);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page, `${screen}, dark`);
  await page.emulateMedia({ colorScheme: "light" });
}

const tags = (page: Page, key: string) => page.getByRole("list", { name: `${key}: result` });

test("the Runs page lists runs, filters them in its address, and says when none match (the Main and ListStates boards)", async ({ page }) => {
  const seed = await api(page);
  const check = await seed.publish("runs-check.dewpoint.json", "Runs A");
  const ok = await seed.start(check, { site: "HQ Paris" });
  const failed = await seed.start(check, { site: "X" });
  const simulated = await seed.start(check, { site: "Lab" }, "simulate");
  for (const id of [ok, failed, simulated]) await seed.ended(id);
  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
  await expect(page.getByRole("heading", { level: 1, name: "Runs" })).toBeVisible();
  await expect(page.getByText("Updates every 5 s")).toBeVisible();
  const table = page.getByRole("region", { name: "Runs" });
  await expect(table.getByRole("link", { name: failed.slice(0, 8) })).toBeVisible();
  await expect(table.getByRole("link", { name: ok.slice(0, 8) })).toBeVisible();
  await expect(table.getByRole("row").filter({ has: page.getByRole("link", { name: simulated.slice(0, 8) }) })).toContainText("Simulated");
  await expect(table.getByRole("row").filter({ has: page.getByRole("link", { name: failed.slice(0, 8) }) })).toContainText("workflow_failed");
  await accessibleBothWays(page, "runs: the list");
  // One status, from its menu: the address keeps it.
  await page.getByRole("button", { name: "Status · Any" }).click();
  await accessibleBothWays(page, "runs: the status menu");
  await page.getByRole("menuitemradio", { name: "Failed" }).click();
  await expect(page).toHaveURL(/status=failed/);
  await expect(table.getByRole("link", { name: ok.slice(0, 8) })).toHaveCount(0);
  await expect(table.getByRole("link", { name: failed.slice(0, 8) })).toBeVisible();
  // The workflow, from a list that can be searched.
  await page.getByRole("button", { name: "Workflow · Runs A" }).click();
  await page.getByRole("dialog", { name: "Choose a workflow" }).getByRole("combobox").fill("Runs A");
  await accessibleBothWays(page, "runs: choosing a workflow");
  await page.keyboard.press("Escape");
  // Nothing matches: said, with Clear the filters.
  await page.getByRole("button", { name: "Trigger · Any" }).click();
  await page.getByRole("menuitemradio", { name: "Schedule" }).click();
  await expect(page.getByText("No runs match these filters in the last 24 hours.")).toBeVisible();
  await accessibleBothWays(page, "runs: nothing matches");
  await page.getByRole("button", { name: "Clear the filters" }).click();
  await expect(page).toHaveURL(/\/runs$/);
});

test("a failed live run opens on its failed step, its result in the drawer (the RunFailed board)", async ({ page }) => {
  const seed = await api(page);
  const check = await seed.publish("runs-check.dewpoint.json", "Runs B");
  const failed = await seed.start(check, { site: "X" });
  await seed.ended(failed);
  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
  await page.getByRole("link", { name: failed.slice(0, 8) }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Runs B" })).toBeVisible();
  await expect(page.getByRole("note").filter({ hasText: /^Live run\./ })).toHaveText("Live run. It acted for real: steps marked sent called their connections.");
  await expect(tags(page, "greet")).toContainText("succeeded");
  await expect(tags(page, "check")).toContainText("→ false");
  await expect(tags(page, "done")).toContainText("skipped");
  const drawer = page.getByRole("complementary", { name: "halt" });
  await expect(drawer.getByRole("tab", { name: "Result", selected: true })).toBeVisible();
  await expect(drawer.getByText("workflow_failed").first()).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "halt" })).toBeFocused();
  await accessibleBothWays(page, "a run: failed, its failed step's result");
  await drawer.getByRole("tab", { name: "Setup" }).click();
  await expect(drawer.getByText("Message", { exact: true }).first()).toBeVisible();
  await accessibleBothWays(page, "a run: its failed step's setup");
});

test("a loop's iterations, four at a time, and one step's, picked (the RunLoop board)", async ({ page }) => {
  const seed = await api(page);
  const loop = await seed.publish("runs-loop.dewpoint.json", "Runs C");
  const run = await seed.start(loop, { sites: ["Paris-Opera", "Lyon", "Nice", "Bordeaux-Centre", "Lille-Flandres"] });
  await seed.ended(run);
  await page.goto(`/t/${seed.tenant}/runs/${run}`);
  await expect(tags(page, "each_site")).toContainText("5 iterations");
  await expect(tags(page, "is_long")).toContainText("5 instances: 5 succeeded");
  await page.getByRole("button", { name: /^each_site, Loop/ }).click();
  const drawer = page.getByRole("complementary", { name: "each_site" });
  await expect(drawer.getByRole("list", { name: "each_site's iterations, 1 to 4 of 5" })).toBeVisible();
  await accessibleBothWays(page, "a run: a loop's iterations");
  await drawer.getByRole("button", { name: "Next 1" }).click();
  await expect(drawer.getByRole("list", { name: "each_site's iterations, 5 to 5 of 5" })).toBeVisible();
  await page.getByRole("button", { name: /^mark, Transform/ }).click();
  const mark = page.getByRole("complementary", { name: "mark" });
  await mark.getByRole("button", { name: "Show" }).click();
  await expect(mark.getByRole("region", { name: "Output" })).toContainText("Paris-Opera");
  await accessibleBothWays(page, "a run: a step's iteration");
});

test("a running live run is cancelled after its question (the RunRunning board)", async ({ page }) => {
  const seed = await api(page);
  // `first`, then `wait`'s delay: the engine sends a sleeping delay's `running` row once another unit ends (here, the
  // projection of `first`'s end). A delay that starts the run alone isn't recorded until it ends (M109).
  const wait = await seed.publish("runs-wait.dewpoint.json", "Runs D");
  const run = await seed.start(wait, {});
  await seed.running(run);
  await page.goto(`/t/${seed.tenant}/runs/${run}`);
  await expect(page.getByRole("note").filter({ hasText: /^Live run\./ })).toHaveText("Live run. It acts for real: steps marked sent called their connections.");
  await expect(tags(page, "wait")).toContainText("running", { timeout: 15_000 }); // its steps are read every 5 s
  await accessibleBothWays(page, "a run: running");
  await page.getByRole("button", { name: "Cancel the run" }).click();
  const ask = page.getByRole("alertdialog", { name: "Cancel this run?" });
  await expect(ask).toBeVisible();
  await accessibleBothWays(page, "a run: cancel's question");
  await ask.getByRole("button", { name: "Cancel the run" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused(); // its Cancel is gone: focus on the run's name
  await expect(page.getByRole("heading", { level: 1 }).locator("..").getByText(/^(Cancel requested|Cancelled)$/)).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 }).locator("..").getByText("Cancelled", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(tags(page, "wait")).toContainText("cancelled", { timeout: 15_000 }); // its steps read again at the end
  await accessibleBothWays(page, "a run: cancelled");
});

test("at 320 px: the list as a list, a simulation's page and its start, and a run not kept (the RunOther and Narrow boards)", async ({ page }) => {
  const seed = await api(page);
  const check = await seed.publish("runs-check.dewpoint.json", "Runs E");
  const simulated = await seed.start(check, { site: "Lab" }, "simulate");
  await seed.ended(simulated);
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
  const list = page.getByRole("list", { name: "Runs" });
  await expect(list.getByRole("link", { name: simulated.slice(0, 8) })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await accessibleBothWays(page, "runs: the list, 320 px");
  // The graph it ran is read once its steps are: their "Ended" line is drawn before the canvas fits the graph, on the
  // least height it gets. The graph is taller than that even at the farthest zoom: centred, it hid the start card under
  // the banner.
  const stepsRead = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/v1/t/${seed.tenant}/runs/${simulated}/steps`);
  await page.route(`**/api/v1/t/${seed.tenant}/workflows/${check}/versions/*`, async (route) => {
    await stepsRead;
    await route.continue();
  });
  await list.getByRole("link", { name: simulated.slice(0, 8) }).click();
  await expect(page.getByText(/^Simulated\./).first()).toBeVisible();
  await expect(tags(page, "greet")).toContainText("succeeded");
  await expect(page.getByRole("button", { name: /^Start: by hand/ })).toBeInViewport({ ratio: 0.99 }); // on the canvas: its scaled box rounds
  await page.getByRole("button", { name: /^Start: by hand/ }).click();
  const start = page.getByRole("complementary", { name: "Start" });
  await expect(start.getByRole("region", { name: "Input" })).toContainText("Lab");
  await accessibleBothWays(page, "a run: its start, 320 px");
  await page.goto(`/t/${seed.tenant}/runs/0d4f9b2a-0000-4000-8000-000000000000`);
  await expect(page.getByText("This run isn't kept any more, or it never existed here.")).toBeVisible();
  await accessibleBothWays(page, "a run: not kept, 320 px");
  await page.setViewportSize({ width: 1280, height: 720 });
});
