// SPDX-License-Identifier: Apache-2.0
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";
import * as OTPAuth from "otpauth";

const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "violet-otter-canyon-42";
let totpSecret = "";

function code(secret: string, offsetSeconds = 0): string {
  return new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(secret) }).generate({ timestamp: Date.now() + offsetSeconds * 1000 });
}

async function passwordLogin(page: Page) {
  await page.goto("/login");
  await expectAccessible(page, "login");
  await page.getByTestId("login-email").fill(EMAIL);
  await page.getByTestId("login-password").fill(PASSWORD);
  await page.getByTestId("login-submit").click();
}

test.describe.serial("foundations", () => {
  test("first login enrolls TOTP, creates a tenant and a Mist connection", async ({ page }) => {
    await passwordLogin(page);
    await expect(page).toHaveURL(/\/enroll/);
    await expectAccessible(page, "enroll: choose a method");
    await page.getByRole("button", { name: "Authenticator app" }).click();
    totpSecret = (await page.getByTestId("totp-secret").textContent())!.replace(/\s/g, "");
    await expectAccessible(page, "enroll: authenticator app");
    await page.getByTestId("totp-code").fill(code(totpSecret));
    await page.getByTestId("totp-submit").click();
    await expect(page.getByTestId("recovery-codes")).toBeVisible();
    await expectAccessible(page, "enroll: recovery codes");
    await page.getByTestId("recovery-ack").check();
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page).toHaveURL(/\/tenants/);
    await expectAccessible(page, "tenants");
    await page.getByTestId("tenant-name").fill("Acme Retail");
    await page.getByTestId("tenant-slug").fill("acme-retail");
    await page.getByTestId("tenant-create").click();
    await page.getByTestId("tenant-switcher").click();
    await expect(page.getByRole("menuitem", { name: /Acme Retail/ })).toBeVisible();
    await expectAccessible(page, "tenant menu");
    await page.getByRole("menuitem", { name: /Acme Retail/ }).click();
    // This stack is a development deployment (Compose's dev override): every signed-in screen says so.
    await expect(page.getByRole("note", { name: "Deployment" })).toContainText("Development deployment");
    await expectAccessible(page, "connections");

    await page.getByTestId("conn-add").click();
    await page.getByTestId("conn-name").fill("Acme Prod");
    await page.getByTestId("conn-cloud").selectOption("emea_01");
    await page.getByTestId("conn-org").fill("6a1f6c34-6e8e-4b35-9a4c-1f0b8f1f2c11");
    await page.getByTestId("conn-token").fill("tok_" + "a".repeat(36));
    await page.getByTestId("conn-save").click();
    const row = page.getByTestId("conn-row").filter({ hasText: "Acme Prod" });
    await expect(row).toContainText("api.eu.mist.com");
    await expect(row).toContainText("Not verified");
    await expect(page.locator("body")).not.toContainText("tok_");
    await expectAccessible(page, "connections, with a connection");

    // Settings → Members & roles: the platform admin created the tenant, so owns it.
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: /Settings · Acme Retail/ })).toBeVisible();
    await expect(page.getByLabel(`Role of ${EMAIL}`)).toHaveValue("owner");
    await expectAccessible(page, "settings: members");
    await page.getByLabel("Email").fill("nobody@example.com");
    await page.getByRole("button", { name: "Add member" }).click();
    await expect(page.getByRole("alert")).toContainText("No Dewpoint account has that email");
    await page.getByRole("button", { name: `Remove ${EMAIL}` }).click();
    const confirm = page.getByRole("dialog", { name: "Remove a member" });
    await expect(confirm).toBeVisible();
    await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused(); // the safe choice first
    await expectAccessible(page, "settings: confirm a removal");
    await page.keyboard.press("Escape");
    await expect(confirm).toBeHidden();

    // The ⌘K palette: a native modal dialog, keyboard only. Escape closes it; a choice goes there.
    await page.keyboard.press("ControlOrMeta+k");
    const palette = page.getByRole("dialog", { name: "Search or jump to" });
    await expect(palette).toBeVisible();
    await expectAccessible(page, "command palette");
    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();
    await page.keyboard.press("ControlOrMeta+k");
    await page.keyboard.type("secur");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/account\/security/);
  });

  test("passkey added with a virtual authenticator signs in without a password", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true,
                 isUserVerified: true },
    });
    await passwordLogin(page);
    await expect(page).toHaveURL(/\/mfa/);
    await expectAccessible(page, "mfa");
    await page.getByTestId("totp-code").fill(code(totpSecret, 30)); // next step: the current one was consumed
    await page.getByTestId("totp-submit").click();
    await expect(page).toHaveURL(/\/tenants/); // wait: the MFA response rotates the session cookie
    await page.goto("/account/security");
    await expectAccessible(page, "security");
    page.once("dialog", (d) => void d.accept("E2E key"));
    await page.getByTestId("passkey-add").click();
    await expect(page.getByText("E2E key")).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();

    await page.goto("/login");
    await page.getByTestId("login-passkey").click();
    await expect(page).toHaveURL(/\/tenants/);
  });
});
