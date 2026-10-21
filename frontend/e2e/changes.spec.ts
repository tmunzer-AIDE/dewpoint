// SPDX-License-Identifier: Apache-2.0
// Editor 4f-2b in the browser: a Mist update's changes, a create's settings and a device's kind, in a step's drawer,
// behind nginx, under the served CSP, with axe, light and dark, at 1280 and 320 px. Nothing is published and Mist is
// never called (D24): the steps have no connection.
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** The changes fixture imported as a new workflow and opened on its canvas. */
async function openChanges(page: Page, name: string) {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/changes.dewpoint.json");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  await page.goto(new URL(page.url()).pathname);
}

async function drawerOf(page: Page, key: string) {
  await page.getByRole("button", { name: new RegExp(`^${key}, `) }).click();
  return page.getByRole("complementary", { name: key });
}

/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
async function accessibleBothWays(page: Page, screen: string): Promise<void> {
  await expectAccessible(page, `${screen}, light`);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page, `${screen}, dark`);
  await page.emulateMedia({ colorScheme: "light" });
}

test("an update's changes: found, set, cleared, sent by merge or replace", async ({ page }) => {
  await openChanges(page, "Changes");
  const drawer = await drawerOf(page, "update_settings");
  const changes = drawer.getByRole("group", { name: "Changes" });
  await expect(changes.getByRole("radio", { name: "Merge with the current settings" })).toBeChecked();
  await expect(changes.getByText("1 of 93 settings change; the others stay as they are.")).toBeVisible();
  // A part of Rogue, found among its own.
  await changes.getByRole("button", { name: "＋ Another setting of Rogue" }).click();
  await changes.getByRole("combobox", { name: "Find a setting of Rogue" }).fill("rssi");
  await changes.getByRole("option", { name: /Min rogue RSSI/ }).click();
  await changes.getByLabel("Min rogue RSSI").fill("-80");
  // Remote syslog, found by its name, then cleared.
  await changes.getByRole("combobox", { name: "Find a setting" }).fill("remote syslog");
  await changes.getByRole("option", { name: /^Remote syslog/ }).first().click(); // the setting itself: top-level first
  await changes.getByRole("group", { name: "What happens to Remote syslog" }).getByRole("button", { name: "Clear" }).click();
  await expect(changes.getByText("Sent empty: Mist removes this setting.")).toBeVisible();
  await expect(changes.getByText("2 of 93 settings change; the others stay as they are.")).toBeVisible();
  await changes.getByRole("radio", { name: "Replace them" }).click();
  await expect(changes.getByText(/^Replace sends each setting below as written/)).toBeVisible();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  await accessibleBothWays(page, "drawer: an update's changes");
});

test("a create's settings, a union setting as JSON, a device's kind", async ({ page }) => {
  await openChanges(page, "Settings");
  const create = await drawerOf(page, "create_wlan");
  const settings = create.getByRole("group", { name: "Settings" });
  await expect(settings.getByLabel("SSID")).toBeVisible(); // required: first, given or not
  await expect(settings.getByRole("button", { name: "Remove SSID" })).toHaveCount(0);
  await settings.getByRole("combobox", { name: "Find a setting" }).fill("vlan id");
  await settings.getByRole("option", { name: /^VLAN ID/ }).first().click();
  await expect(settings.getByText(/As JSON: Mist takes it in more than one shape\./)).toBeVisible();
  await accessibleBothWays(page, "drawer: a create's settings");
  const device = await drawerOf(page, "rename_ap");
  const kind = device.getByRole("radiogroup", { name: "Kind of device" });
  await expect(kind.getByRole("radio", { name: "AP" })).toBeChecked(); // its height: only an AP has one
  await kind.getByRole("radio", { name: "Switch" }).click();
  await expect(device.getByText("Kind changed to Switch: Name is kept; Height is dropped, as a Switch doesn't have it.")).toBeVisible();
  await accessibleBothWays(page, "drawer: a device's kind");
});

test("at 320 px the changes stack, their targets 44 px, and stay AA", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await openChanges(page, "Changes narrow");
  const drawer = await drawerOf(page, "update_settings");
  const changes = drawer.getByRole("group", { name: "Changes" });
  const [merge, replace] = [
    (await changes.getByText("Merge with the current settings", { exact: true }).boundingBox())!,
    (await changes.getByText("Replace them", { exact: true }).boundingBox())!,
  ];
  expect(replace.y).toBeGreaterThan(merge.y); // stacked
  const rogue = changes.getByRole("group", { name: "What happens to Rogue" });
  for (const target of [rogue.getByRole("button", { name: "Set" }), changes.getByRole("button", { name: "Keep Rogue as it is" }), changes.getByRole("button", { name: "＋ Add a setting" })]) {
    expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  await accessibleBothWays(page, "drawer: changes at 320 px");
});
