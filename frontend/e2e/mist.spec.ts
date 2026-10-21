// SPDX-License-Identifier: Apache-2.0
// Editor 4f-2a in the browser: a Mist step added through the picker by its resource, and its site's id, which takes a
// value from an earlier step and offers the connection's choices. Behind nginx, under the served CSP, with axe, light
// and dark, at 1280 and 320 px. Nothing is published and Mist is never called (D24): the steps have no connection, so
// their choices can't load.
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** The Mist fixture imported as a new workflow and opened on its canvas; the picker opened after its step. */
async function openPicker(page: Page, name: string) {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/mist.dewpoint.json");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  await page.goto(new URL(page.url()).pathname);
  await page.getByRole("button", { name: "Add a step after get_site" }).click();
  return page.getByRole("dialog", { name: /^Add a step/ });
}

/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
async function accessibleBothWays(page: Page, screen: string): Promise<void> {
  await expectAccessible(page, `${screen}, light`);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page, `${screen}, dark`);
  await page.emulateMedia({ colorScheme: "light" });
}

test("a Mist step is found by its resource, and its site's id takes a value or a choice", async ({ page }) => {
  const picker = await openPicker(page, "Mist step");
  await expect(picker.getByText("Mist: 85 resources, type to find one")).toBeVisible();
  await accessibleBothWays(page, "picker: Mist's resources");
  await picker.getByRole("combobox").fill("site settings");
  await expect(picker.getByRole("option", { name: /^Site settings/ })).toContainText("2 actions");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Add a step: Site settings" })).toBeVisible();
  await expect(picker.getByRole("option", { name: /^Update site settings/ })).toContainText("Uses a Juniper Mist connection");
  await accessibleBothWays(page, "picker: a resource's actions");
  await picker.getByRole("option", { name: /^Update site settings/ }).click();
  await page.getByRole("button", { name: /^update, Update site settings/ }).click();
  const drawer = page.getByRole("complementary", { name: "update" });
  await expect(drawer.getByText("Mist · Site settings")).toBeVisible();
  const site = drawer.locator('[data-pointer="/site_id"]');
  await expect(site.getByRole("button", { name: "Text" })).toHaveAttribute("aria-pressed", "true");
  await expect(site.getByRole("button", { name: "＋ Data" })).toBeVisible();
  await expect(site.getByRole("button", { name: "Show choices: Site ID" })).toBeDisabled();
  await expect(site.getByText("Choose the step's connection first: the choices come from it.")).toBeVisible();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  await accessibleBothWays(page, "drawer: a Mist step's site id");
});

test("at 320 px the picker's targets are 44 px and a step's ref goes under its title", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  const picker = await openPicker(page, "Mist step narrow");
  await picker.getByRole("combobox").fill("site settings");
  await page.keyboard.press("Enter");
  expect((await picker.getByRole("button", { name: "Back to every step" }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
  const update = picker.getByRole("option", { name: /^Update site settings/ });
  const [title, ref] = [(await update.getByText("Update site settings", { exact: true }).boundingBox())!, (await update.getByText("mist.site_settings.update@1").boundingBox())!];
  expect(ref.y).toBeGreaterThan(title.y);
  expect((await update.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await accessibleBothWays(page, "picker at 320 px");
  await update.click();
  await page.getByRole("button", { name: /^update, Update site settings/ }).click();
  const drawer = page.getByRole("complementary", { name: "update" });
  expect((await drawer.getByRole("button", { name: "Show choices: Site ID" }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await accessibleBothWays(page, "drawer at 320 px");
});
