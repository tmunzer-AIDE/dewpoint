// SPDX-License-Identifier: Apache-2.0
// Editor 4f-3b in the browser (the 4f-3 design §5, §6): a start form's picker in the run form at 1280 and 320 px, the
// run page's name, a re-run's, the schedule form and Simulate. Behind nginx, under the served CSP, with axe, light and
// dark. Mist is never called (D24): the fixture's picker is bound at import to "Acme Prod" (made by the foundations
// project, never verified), its steps are control steps only, and each listing is answered in the browser with
// made-up sites: none reaches the API, so no worker calls Mist.
import type { Locator, Page, Route } from "@playwright/test";
import { expect, test } from "./gate";
import { accessibleBothWays, api } from "./seed";

test.describe.configure({ mode: "serial" });

const RUN_PAGE = /\/t\/[^/]+\/runs\/[0-9a-f-]{36}$/;
const LYON = "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d";
const SITES = [
  { value: LYON, label: "Lyon DC" },
  { value: "1b6e93f2-7a4c-4d1e-8b2f-0c9d8e7f6a5b", label: "Lyon store 4" },
  { value: "c0d4a7e1-2b3c-4d5e-8f6a-7b8c9d0e1f2a", label: "Paris HQ" }, // no "ly" in its name: two of three answer "ly"
];

/** Every listing answered here, with the made-up sites whose name holds what's typed: what each asked, in order. */
async function answerListings(page: Page): Promise<unknown[]> {
  const asked: unknown[] = [];
  const answer = async (route: Route) => {
    const body = route.request().postDataJSON() as { query: string };
    asked.push(body);
    await route.fulfill({ json: { options: SITES.filter((s) => s.label.toLowerCase().includes(body.query.toLowerCase())) } });
  };
  await page.route("**/api/v1/t/*/workflows/*/input-options", answer);
  await page.route("**/api/v1/t/*/node-types/*/options", answer);
  return asked;
}

/** The picker workflow, published under `name`, its picker bound to Acme Prod. */
async function published(page: Page, name: string) {
  const seed = await api(page);
  const acme = await seed.connection("Acme Prod");
  return { seed, acme, workflow: await seed.publish("picker.dewpoint.json", name, { b1: acme }) };
}

const tall = async (target: Locator) => expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44);

test("the run form lists a picker's choices, picks one by the keyboard and names it, as the run page does (the Main and States boards)", async ({ page }) => {
  const { seed } = await published(page, "Picker A");
  const asked = await answerListings(page);
  await page.goto(`/t/${seed.tenant}/workflows`);
  await page.getByRole("button", { name: "Start a run of Picker A" }).click();
  const form = page.getByRole("dialog", { name: "Start a run" });
  const site = form.getByRole("combobox", { name: /^Site ID/ });
  await expect(site).toBeFocused();
  await expect(form.getByText("One of Acme Prod's sites: type part of its name, then Show choices.")).toBeVisible();
  await site.fill("ly");
  await site.press("Enter");
  await expect(form.getByText("2 of Acme Prod's sites have “ly” in their name.")).toBeVisible();
  await accessibleBothWays(page, "the run form: a picker's choices");
  await site.press("Escape");
  await expect(form.getByRole("listbox")).toHaveCount(0);
  await expect(form).toBeVisible(); // Escape closed the list, never the form; Enter listed, never started
  await site.press("Enter");
  await expect(form.getByRole("listbox")).toBeVisible(); // Down enters a list shown, never one on its way
  await site.press("ArrowDown");
  await expect(form.getByRole("listbox", { name: "Choices for Site ID" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(site).toBeFocused();
  await expect(site).toHaveValue(LYON);
  await expect(form.getByText("Lyon DC, picked from Acme Prod's sites.")).toBeVisible();
  await accessibleBothWays(page, "the run form: a pick named");
  const version = (asked[0] as { expected_version_id: string }).expected_version_id;
  expect(asked).toEqual([{ field: "site_id", query: "ly", expected_version_id: version }, { field: "site_id", query: "ly", expected_version_id: version }]);
  await form.getByRole("button", { name: "Start the live run" }).click();
  await expect(page).toHaveURL(RUN_PAGE);
  await page.getByRole("button", { name: /^Start: by hand/ }).click();
  const input = page.getByRole("complementary", { name: "Start" }).getByRole("region", { name: "Input" });
  await expect(input.getByText("Lyon DC", { exact: true })).toBeVisible();
  await expect(input.getByText(LYON)).toBeVisible();
  await expect(input.getByText("site_id's name as picked when the run started.")).toBeVisible();
  await accessibleBothWays(page, "a run: its start's picked name");
});

test("a re-run names its value as picked for the first run (the OtherForms board)", async ({ page }) => {
  const { seed, workflow } = await published(page, "Picker B");
  const run = await seed.start(workflow, { site_id: LYON }, "live", { site_id: { value: LYON, label: "Lyon DC" } });
  await seed.ended(run);
  await page.goto(`/t/${seed.tenant}/runs/${run}`);
  await page.getByRole("button", { name: "Re-run…" }).click();
  const form = page.getByRole("dialog", { name: `Re-run ${run.slice(0, 8)}` });
  await expect(form.getByRole("combobox", { name: /^Site ID/ })).toHaveValue(LYON);
  await expect(form.getByText("Lyon DC, as picked for the first run.")).toBeVisible();
  await accessibleBothWays(page, "the re-run form: a picked name");
  await form.getByRole("button", { name: "Re-run live" }).click();
  await expect(page).toHaveURL(RUN_PAGE);
  await expect(page).not.toHaveURL(new RegExp(`${run}$`));
});

test("at 320 px every target of the run form is 44 px, a choice's name over its id (the Narrow320 boards)", async ({ page }) => {
  const { seed, workflow } = await published(page, "Picker C");
  await answerListings(page);
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto(`/t/${seed.tenant}/runs?workflow=${workflow}`);
  await page.getByRole("button", { name: "Start a run…" }).click();
  const form = page.getByRole("dialog", { name: "Start a run" });
  const site = form.getByRole("combobox", { name: /^Site ID/ });
  await expect(site).toBeFocused();
  await site.fill("ly");
  await site.press("Enter");
  await expect(form.getByRole("listbox")).toBeVisible();
  for (const target of [
    site, form.getByLabel(/^Change ticket/), form.getByRole("button", { name: "Show choices: Site ID" }), form.getByRole("button", { name: "Edit as JSON" }),
    form.getByRole("button", { name: "Start the live run" }), form.getByRole("button", { name: "Cancel" }), form.getByRole("button", { name: "Close" }),
    form.locator("label").filter({ has: page.getByRole("radio", { name: "Live" }) }), ...(await form.getByRole("option").all()),
  ]) await tall(target);  // prettier-ignore
  const row = form.getByRole("option", { name: /^Lyon DC/ });
  const [name, id] = [(await row.getByText("Lyon DC", { exact: true }).boundingBox())!, (await row.getByText("8a27c4d0…").boundingBox())!];
  expect(id.y).toBeGreaterThan(name.y);
  await accessibleBothWays(page, "the run form at 320 px: a picker's choices");
  await page.setViewportSize({ width: 1280, height: 720 });
});

test("the schedule form lists the published version's choices, and Simulate the draft's, read now (the OtherForms board)", async ({ page }) => {
  const { seed, acme, workflow } = await published(page, "Picker D");
  const asked = await answerListings(page);
  await page.goto(`/t/${seed.tenant}/workflows/${workflow}?triggers=true`);
  const schedules = page.getByRole("complementary", { name: "Triggers" }).getByRole("region", { name: "Schedules" });
  await schedules.getByRole("button", { name: "＋ Schedule" }).click();
  const form = schedules.getByRole("form", { name: "New schedule" });
  await form.getByRole("button", { name: "Show choices: Site ID" }).click();
  await form.getByRole("option", { name: /^Lyon DC/ }).click();
  await expect(form.getByText("Lyon DC, picked from Acme Prod's sites.")).toBeVisible();
  await accessibleBothWays(page, "editor: a schedule's picked name");
  await form.getByRole("button", { name: "Cancel" }).click();
  await page.goto(`/t/${seed.tenant}/workflows/${workflow}`);
  await page.getByRole("button", { name: "◌ Simulate workflow" }).click();
  const dialog = page.getByRole("dialog", { name: "Simulate workflow" });
  await dialog.getByRole("button", { name: "Show choices: Site ID" }).click();
  await expect(dialog.getByText("Read from Acme Prod now: listing changes nothing in Mist.")).toBeVisible();
  await accessibleBothWays(page, "simulate: a picker's choices");
  expect(asked.at(-1)).toEqual({ field: "site_id", connection_id: acme, query: "" });
  await dialog.getByRole("button", { name: "Cancel" }).click();
});
