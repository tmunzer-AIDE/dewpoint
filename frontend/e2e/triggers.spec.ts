// SPDX-License-Identifier: Apache-2.0
// Slice 4c-3b in the browser: Settings → Webhook endpoints, the Triggers panel (the input, schedules, webhooks), New
// workflow's "What starts it?" and the list's Trigger column, behind nginx, under the served CSP, with axe. Nothing
// leaves the stack (D24): an endpoint is made and bound, never sent to; a schedule is simulated, and deleted.
import type { Locator, Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** New workflow, as `choose` sets it up; it opens on its Triggers. */
async function create(page: Page, name: string, choose: (dialog: Locator) => Promise<void> = () => Promise.resolve()): Promise<Locator> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await choose(dialog);
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("button", { name: /^(Create|Import) and open$/ }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  const panel = page.getByRole("complementary", { name: "Triggers" });
  await expect(panel.getByRole("heading", { name: "Triggers" })).toBeFocused();
  return panel;
}

const importing = (file: string) => async (dialog: Locator) => {
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles(file);
  await expect(dialog.getByText("The file names no connection or workflow.")).toBeVisible();
};

test("Settings → Webhook endpoints: a Mist endpoint shows its token once; rotating asks first", async ({ page }) => {
  await page.goto(`/t/${await tenantId(page)}/settings/webhooks`);
  await expect(page.getByRole("heading", { name: "Webhook endpoints" })).toBeVisible();
  await expect(page.getByText("No endpoint yet.")).toBeVisible();
  await expectAccessible(page, "settings: webhook endpoints, none yet");
  await page.getByRole("button", { name: "＋ Endpoint" }).click();
  const form = page.getByRole("form", { name: "New endpoint" });
  await form.getByLabel("Name").fill("Mist prod");
  await expectAccessible(page, "settings: a new Mist endpoint");
  await form.getByRole("radio", { name: "Another sender" }).check();
  await form.getByRole("radio", { name: "An HMAC signature" }).check();
  await form.getByRole("radio", { name: /^A list in the body, at/ }).check();
  await expect(form.getByText(/^Fixed once made: an HMAC signature; events in the list at \/items; no ids\.$/)).toBeVisible();
  await expectAccessible(page, "settings: another sender's endpoint");
  await form.getByRole("radio", { name: "Mist" }).check();
  await form.getByRole("button", { name: "Create the endpoint" }).click();
  const shown = page.getByRole("status").filter({ hasText: "Mist prod is ready" });
  await expect(shown).toBeVisible();
  await expectAccessible(page, "settings: a token shown once");
  await shown.getByRole("button", { name: "I've copied it" }).click();
  await expect(page.getByText("Mist prod is ready")).toHaveCount(0);
  const table = page.getByRole("region", { name: "Webhook endpoints" });
  await table.getByRole("button", { name: "Mist prod, details" }).click();
  await expect(table.getByText(/^Path \/hooks\/[0-9a-f-]{36}, on your Dewpoint webhook address\./)).toBeVisible();
  await table.getByRole("button", { name: "Rotate the token…" }).click();
  const ask = page.getByRole("dialog", { name: "Rotate Mist prod's token?" });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "settings: rotating a token");
  await page.keyboard.press("Escape");
  await expect(ask).toBeHidden();
});

test("the Triggers panel's input: form fields, a Mist event's shape, a CSV file, JSON held while it can't be saved", async ({ page }) => {
  const panel = await create(page, "Input flow");
  await expectAccessible(page, "editor: triggers, a new workflow");
  await panel.getByRole("button", { name: "＋ Field" }).click();
  const field = panel.getByRole("group", { name: "The field field_1" });
  await field.getByLabel("Label").fill("Site");
  await field.getByLabel("Required").check();
  await expectAccessible(page, "editor: triggers, a field");
  await field.getByRole("button", { name: "Done" }).click();
  await expect(panel.getByText("field_1 · Site · Text · required")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Edit field_1" })).toBeFocused(); // the review of revision 1
  await panel.getByRole("button", { name: "Use a Mist event…" }).click();
  await panel.getByRole("searchbox", { name: "Find a topic" }).fill("device-events");
  await panel.getByRole("radio", { name: "device-events" }).check();
  await panel.getByRole("button", { name: "Use device-events" }).click();
  await expect(panel.getByText("A Mist event: device-events")).toBeVisible();
  await expectAccessible(page, "editor: triggers, a Mist event's shape");
  await panel.getByRole("button", { name: "Use form fields instead" }).click();
  await panel.getByRole("button", { name: "＋ CSV file" }).click();
  await expect(panel.getByRole("button", { name: "Edit Column 1" })).toBeFocused();
  await panel.getByRole("button", { name: "Edit Column 1" }).click();
  await panel.getByRole("group", { name: "The column Column 1" }).getByLabel("Header in the file").fill("AP name");
  await expectAccessible(page, "editor: triggers, a CSV column");
  await panel.getByRole("button", { name: "Done" }).click();
  await expect(panel.getByRole("button", { name: "Edit AP name" })).toBeFocused();
  await panel.getByRole("button", { name: "Edit as JSON" }).click();
  await panel.getByRole("textbox", { name: "The input's schema and CSV columns" }).fill("{");
  await expect(panel.getByText("Line 1: This isn't valid JSON, so it isn't saved.")).toBeVisible();
  await expect(page.getByRole("button", { name: "1 edit not applied" })).toBeVisible();
  await expectAccessible(page, "editor: triggers, JSON held");
  await panel.getByRole("button", { name: "Discard what isn't saved" }).click();
  await expect(page.getByRole("button", { name: "1 edit not applied" })).toHaveCount(0);
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
});

test("a published workflow's schedule and webhook are live at once, said in words, and summed up on its start card", async ({ page }) => {
  const panel = await create(page, "Report T", importing("e2e/fixtures/report.dewpoint.json"));
  const schedules = panel.getByRole("region", { name: "Schedules" });
  await expect(schedules.getByRole("button", { name: "＋ Schedule" })).toBeDisabled();
  await expect(schedules.getByText("A schedule runs the published version: publish a first version to add one.")).toBeVisible();
  await expect(page.getByRole("button", { name: "No problems" })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Publish v1" }).click();
  await page.getByRole("dialog", { name: "Publish version 1" }).getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v1")).toBeVisible({ timeout: 10_000 });
  await expect(schedules.getByText("Live · on version 1")).toBeVisible();
  await schedules.getByRole("button", { name: "＋ Schedule" }).click();
  const form = schedules.getByRole("form", { name: "New schedule" });
  await form.getByLabel("Time zone").fill("Europe/Paris");
  await form.getByRole("radio", { name: "Simulate" }).check();
  await expect(form.getByText("Version 1 takes no input.")).toBeVisible();
  await expectAccessible(page, "editor: triggers, a new schedule");
  await form.getByRole("button", { name: "Add the schedule" }).click();
  await expect(schedules.getByText("Every day at 07:00")).toBeVisible();
  await expect(schedules.getByText(/^Europe\/Paris · simulated: nothing is sent/)).toBeVisible();
  const webhooks = panel.getByRole("region", { name: "Webhooks" });
  await webhooks.getByRole("button", { name: "＋ Webhook" }).click();
  const bind = webhooks.getByRole("form", { name: "New webhook" });
  await bind.getByLabel("Endpoint", { exact: true }).selectOption({ label: "Mist prod · Mist" });
  await bind.getByLabel("Topic", { exact: true }).selectOption("device-events");
  await expectAccessible(page, "editor: triggers, a new webhook");
  await bind.getByRole("button", { name: "Add the webhook" }).click();
  await expect(webhooks.getByText("Mist · topic device-events")).toBeVisible();
  await expect(webhooks.getByText("Version 1's input isn't device-events' shape: events it doesn't fit are refused.")).toBeVisible();
  await expect(webhooks.getByText("In the draft: it applies once published.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start: by hand, 1 schedule, 1 webhook. Open its triggers" })).toBeVisible();
  await expectAccessible(page, "editor: triggers, a schedule and a webhook");
  await schedules.getByRole("button", { name: "Edit Every day at 07:00" }).click();
  await schedules.getByRole("button", { name: "Delete the schedule…" }).click();
  const ask = page.getByRole("dialog", { name: 'Delete the schedule "Every day at 07:00"?' });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "editor: triggers, deleting a schedule");
  await ask.getByRole("button", { name: "Delete the schedule" }).click();
  await expect(schedules.getByText("No schedule starts this workflow.")).toBeVisible();
});

test("New workflow: a Mist webhook gives the input its topic's shape, is bound at once, and opens on Triggers", async ({ page }) => {
  const panel = await create(page, "AP alarms", async (dialog) => {
    await dialog.getByRole("radio", { name: /^A Mist webhook/ }).check();
    await dialog.getByLabel("Endpoint", { exact: true }).selectOption({ label: "Mist prod" });
    await dialog.getByLabel("Topic", { exact: true }).selectOption("alarms");
    await expect(dialog.getByText("It opens on its Triggers: the input is alarms' shape, and the webhook is bound to Mist prod.")).toBeVisible();
    await expectAccessible(page, "new workflow: a Mist webhook");
  });
  await expect(panel.getByText("A Mist event: alarms")).toBeVisible();
  await expect(panel.getByRole("region", { name: "Webhooks" }).getByText("Mist · topic alarms")).toBeVisible();
});

test("the list names what starts each workflow besides a person", async ({ page }) => {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  const row = (name: string) => page.getByRole("link", { name, exact: true }).locator("xpath=ancestor::tr");
  await expect(row("AP alarms").getByRole("cell").nth(1)).toHaveText("Webhook");
  await expect(row("Report T").getByRole("cell").nth(1)).toHaveText("Webhook");
  await expect(row("Input flow").getByRole("cell").nth(1)).toHaveText("By hand"); // its CSV file is the draft's: never published
  await expectAccessible(page, "workflows: the Trigger column");
});

test("Settings → Webhook endpoints and the Triggers panel's forms reflow at 320 px and stay AA (WCAG 1.4.10)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  await page.goto(`/t/${await tenantId(page)}/settings/webhooks`);
  await expect(page.getByRole("list", { name: "Webhook endpoints" }).getByText("Mist prod")).toBeVisible();
  expect(await overflow(), "Settings → Webhook endpoints scrolls sideways at 320 px").toBeLessThanOrEqual(0);
  await expectAccessible(page, "settings: webhook endpoints at 320 px");
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByRole("link", { name: "Report T", exact: true }).click();
  await page.getByRole("button", { name: /^Start: by hand/ }).click();
  const panel = page.getByRole("complementary", { name: "Triggers" });
  await panel.getByRole("button", { name: "＋ Schedule" }).click();
  await expect(panel.getByRole("form", { name: "New schedule" })).toBeVisible();
  expect(await overflow(), "the schedule's form scrolls sideways at 320 px").toBeLessThanOrEqual(0);
  await expectAccessible(page, "editor: triggers, a schedule's form at 320 px");
  await page.setViewportSize({ width: 1280, height: 720 });
});
