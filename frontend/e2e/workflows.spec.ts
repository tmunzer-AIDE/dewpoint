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
