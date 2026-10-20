// SPDX-License-Identifier: Apache-2.0
// Slice 4e-2b in the browser (the run form design §5, §6): the run form against the real stack, behind nginx, under
// the served CSP, with axe, light and dark, at 1280 and 320 px. A typed start from the Workflows list lands on its
// run's page; a CSV start from the Runs page is refused by a file with errors, then started from a clean one; an ended
// run is re-run with its input changed. The workflows are control steps only, run live: nothing leaves the stack (D24).
import { expect, test } from "./gate";
import { accessibleBothWays, api } from "./seed";

test.describe.configure({ mode: "serial" });

const RUN_PAGE = /\/t\/[^/]+\/runs\/[0-9a-f-]{36}$/;
const csvFile = (text: string) => ({ name: "sites.csv", mimeType: "text/csv", buffer: Buffer.from(text) });

test("a typed start from the Workflows list lands on its run's page (the Main and EntryPoints boards)", async ({ page }) => {
  const seed = await api(page);
  await seed.publish("runs-check.dewpoint.json", "Form A");
  await page.goto(`/t/${seed.tenant}/workflows`);
  await page.getByRole("button", { name: "Start a run of Form A" }).click();
  const form = page.getByRole("dialog", { name: "Start a run" });
  await expect(form.getByText(/^Version 1 · published /)).toBeVisible();
  await expect(form.getByLabel(/^Site/)).toBeFocused();
  await accessibleBothWays(page, "the run form: live");
  await form.getByRole("radio", { name: "Simulated" }).click();
  await expect(form.getByRole("button", { name: "◌ Start the simulation" })).toBeVisible();
  await accessibleBothWays(page, "the run form: simulated");
  await form.getByRole("radio", { name: "Live" }).click();
  await form.getByLabel(/^Site/).fill("HQ Paris");
  await form.getByRole("button", { name: "Start the live run" }).click();
  await expect(page).toHaveURL(RUN_PAGE);
  await expect(page.getByRole("heading", { level: 1, name: "Form A" })).toBeFocused();
  await accessibleBothWays(page, "a run just started");
});

test("a CSV start: a file with errors says them at a glance, a clean one starts (the CsvStates board)", async ({ page }) => {
  const seed = await api(page);
  await seed.publish("runs-csv.dewpoint.json", "Form B");
  await page.goto(`/t/${seed.tenant}/runs`);
  await page.getByRole("button", { name: "Start a run…" }).click();
  const chooser = page.getByRole("dialog", { name: "Choose a workflow" });
  await chooser.getByRole("combobox").fill("Form B");
  await chooser.getByRole("option", { name: "Form B" }).click();
  const form = page.getByRole("dialog", { name: "Start a run" });
  await expect(form.getByText("This workflow starts from a CSV file: one run, one pass of its loop per row.")).toBeVisible();
  await accessibleBothWays(page, "the run form: before a file");
  await form.getByLabel("Choose a file").setInputFiles(csvFile("Site,VLAN\nParis,10\n,x\n"));
  await expect(form.getByText("2 errors in 1 of 2 rows")).toBeVisible();
  await expect(form.getByRole("button", { name: "Start the live run" })).toBeDisabled();
  await accessibleBothWays(page, "the run form: a file's errors");
  await form.getByLabel("Choose another file").setInputFiles(csvFile("Site,VLAN\nParis,10\nLyon,20\n"));
  await expect(form.getByText("All 2 rows pass.")).toBeVisible();
  await accessibleBothWays(page, "the run form: every row passes");
  await form.getByLabel(/^Region/).fill("EMEA");
  await form.getByRole("button", { name: "Start the live run · 2 rows" }).click();
  await expect(page).toHaveURL(RUN_PAGE);
  await expect(page.getByRole("heading", { level: 1, name: "Form B" })).toBeFocused();
});

test("an ended run is re-run with its input changed (the Rerun board)", async ({ page }) => {
  const seed = await api(page);
  const check = await seed.publish("runs-check.dewpoint.json", "Form C");
  const run = await seed.start(check, { site: "HQ" });
  await seed.ended(run);
  await page.goto(`/t/${seed.tenant}/runs/${run}`);
  await page.getByRole("button", { name: "Re-run…" }).click();
  const form = page.getByRole("dialog", { name: `Re-run ${run.slice(0, 8)}` });
  await expect(form.getByText(`It runs version 1, the same version as run ${run.slice(0, 8)}.`)).toBeVisible();
  await expect(form.getByLabel(/^Site/)).toHaveValue("HQ");
  await accessibleBothWays(page, "the re-run form");
  await form.getByLabel(/^Site/).fill("HQ Lyon");
  await expect(form.getByText("Changed from the original run's input.")).toBeVisible();
  await form.getByRole("button", { name: "Re-run live" }).click();
  await expect(page).toHaveURL(RUN_PAGE);
  await expect(page).not.toHaveURL(new RegExp(`${run}$`));
  await expect(page.getByRole("heading", { level: 1, name: "Form C" })).toBeFocused();
});

test("at 320 px the form fills the screen, its buttons stacked (the Narrow320 boards)", async ({ page }) => {
  const seed = await api(page);
  const check = await seed.publish("runs-check.dewpoint.json", "Form D");
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
  await page.getByRole("button", { name: "Start a run…" }).click();
  const form = page.getByRole("dialog", { name: "Start a run" });
  await expect(form.getByLabel(/^Site/)).toBeFocused();
  await accessibleBothWays(page, "the run form, 320 px");
  await form.getByRole("button", { name: "Close" }).click();
  await expect(form).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start a run…" })).toBeFocused(); // back to its opener
  await page.setViewportSize({ width: 1280, height: 720 });
});
