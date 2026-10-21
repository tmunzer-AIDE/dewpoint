// SPDX-License-Identifier: Apache-2.0
// Editor 4f-1 in the browser: the message composer in a step's drawer, behind nginx, under the served CSP, with axe,
// light and dark, at 1280 and 320 px. Nothing is published and no message is sent (D24): a Slack step without a
// connection is written and previewed as a draft.
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** The message fixture imported as a new workflow, opened on its canvas, its step's drawer open. */
async function openMessage(page: Page, name: string) {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/message.dewpoint.json");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  await page.goto(new URL(page.url()).pathname);
  await page.getByRole("button", { name: /^notify, / }).click();
  const drawer = page.getByRole("complementary", { name: "notify" });
  return { drawer, message: drawer.getByRole("group", { name: "Message" }) };
}

/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
async function accessibleBothWays(page: Page, screen: string): Promise<void> {
  await expectAccessible(page, `${screen}, light`);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page, `${screen}, dark`);
  await page.emulateMedia({ colorScheme: "light" });
}

test("a message is written in the composer and previewed as Slack lays it out", async ({ page }) => {
  const { drawer, message } = await openMessage(page, "Composer");
  await expect(drawer.getByText("No Slack connection yet: an admin adds one.")).toBeVisible({ timeout: 10_000 });
  await expect(message.getByRole("radio", { name: "Warning" })).toBeChecked();
  // The text on several lines: Enter starts one at the caret, ↑ goes back up.
  const text = message.getByLabel("Text", { exact: true });
  await text.click();
  await text.press("End");
  await page.keyboard.press("Enter");
  await page.keyboard.type("Last seen by its switch.");
  await expect(message.getByRole("textbox", { name: "Text, line 2" })).toHaveValue("Last seen by its switch.");
  await page.keyboard.press("ArrowUp");
  await expect(text).toBeFocused();
  // A link's address checked as it's typed.
  await message.getByRole("button", { name: "＋ Add a link" }).click();
  await message.getByLabel("Link 1 label", { exact: true }).fill("Runbook");
  const address = message.getByLabel("Link 1 address", { exact: true });
  await address.fill("ftp://runbook");
  await expect(message.getByText("A link's address starts with http:// or https://.")).toBeVisible();
  await address.fill("https://runbook.example.test");
  await expect(message.getByText("A link's address starts with http:// or https://.")).toHaveCount(0);
  const preview = drawer.getByRole("region", { name: "Preview in Slack" });
  await expect(preview.getByText("trigger.site").first()).toBeVisible();
  await expect(preview.getByText("Runbook")).toBeVisible();
  await expect(preview.getByText("Severity: warning")).toBeVisible();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  await accessibleBothWays(page, "drawer: the message composer");
});

test("at 320 px the composer stacks a row's parts, its targets 44 px, and stays AA", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  const { drawer, message } = await openMessage(page, "Composer narrow");
  // Measured once the drawer has settled: the connection's words replace "Loading connections…" and take two lines
  // here, moving everything under them.
  await expect(drawer.getByText("No Slack connection yet: an admin adds one.")).toBeVisible({ timeout: 10_000 });
  const box = async (name: string) => (await message.getByText(name, { exact: true }).boundingBox())!;
  const [info, success, warning] = [await box("Info"), await box("Success"), await box("Warning")];
  expect(success.y).toBe(info.y); // the severity in two rows of two
  expect(warning.y).toBeGreaterThan(info.y);
  expect(info.height).toBeGreaterThanOrEqual(44);
  for (const name of ["Remove field 1", "＋ Add a field"]) {
    expect((await message.getByRole("button", { name }).boundingBox())!.height, name).toBeGreaterThanOrEqual(44);
  }
  const label = (await message.getByLabel("Field 1 label", { exact: true }).boundingBox())!;
  const value = (await message.getByLabel("Field 1 value", { exact: true }).boundingBox())!;
  expect(value.y).toBeGreaterThan(label.y); // label over value
  expect(await drawer.evaluate((el) => el.scrollWidth - el.clientWidth), "the drawer scrolls sideways at 320 px").toBeLessThanOrEqual(0);
  await accessibleBothWays(page, "drawer at 320 px: the message composer");
});
