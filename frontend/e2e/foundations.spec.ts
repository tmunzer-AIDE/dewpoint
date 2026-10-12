// SPDX-License-Identifier: Apache-2.0
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";
import { ADMIN_STATE } from "./state";
import * as OTPAuth from "otpauth";

const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "violet-otter-canyon-42";
let totpSecret = "";

function code(secret: string, offsetSeconds = 0): string {
  return new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(secret) }).generate({ timestamp: Date.now() + offsetSeconds * 1000 });
}

async function passwordLogin(page: Page) {
  await page.goto("/login");
  await expect(page.getByTestId("login-submit")).toBeVisible(); // axe checks the form, not the page before it
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
    await expect(page.getByRole("img", { name: "QR code for your authenticator app" })).toBeVisible();
    await expectAccessible(page, "enroll: authenticator app");
    await page.getByTestId("totp-code").fill(code(totpSecret));
    await page.getByTestId("totp-submit").click();
    await expect(page.getByTestId("recovery-codes")).toBeVisible();
    await expectAccessible(page, "enroll: recovery codes");
    await page.getByTestId("recovery-ack").check();
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page).toHaveURL(/\/tenants/);
    await expect(page.getByText("You're not a member of any tenant yet.")).toBeVisible();
    await expectAccessible(page, "tenants");
    await page.getByTestId("tenant-name").fill("Acme Retail");
    await page.getByTestId("tenant-slug").fill("acme-retail");
    await page.getByTestId("tenant-create").click();
    await page.getByTestId("tenant-switcher").click();
    await expect(page.getByRole("menuitem", { name: /Acme Retail/ })).toBeVisible();
    await expectAccessible(page, "tenant menu");
    await page.getByRole("menuitem", { name: /Acme Retail/ }).click();
    await expect(page).toHaveURL(/\/t\/[0-9a-f-]+\/workflows$/); // a tenant opens on its workflows (4b ruling 19)
    await page.getByRole("link", { name: "Connections" }).click();
    await expect(page).toHaveURL(/\/t\/[0-9a-f-]+\/connections/);
    const connectionsPath = new URL(page.url()).pathname;
    // This stack is a development deployment (Compose's dev override): every signed-in screen says so.
    await expect(page.getByRole("note", { name: "Deployment" })).toContainText("Development deployment");
    await expect(page.getByText("No Mist connection yet.")).toBeVisible();
    await expectAccessible(page, "connections");

    await page.getByTestId("conn-add").click();
    await expectAccessible(page, "connections, adding one");
    await page.getByTestId("conn-name").fill("Acme Prod");
    await page.getByTestId("conn-cloud").selectOption("emea_01");
    await page.getByTestId("conn-org").fill("6a1f6c34-6e8e-4b35-9a4c-1f0b8f1f2c11");
    await page.getByTestId("conn-token").fill("tok_" + "a".repeat(36));
    await page.getByTestId("conn-save").click();
    const row = page.getByTestId("conn-row").filter({ hasText: "Acme Prod" });
    await expect(row).toContainText("api.eu.mist.com");
    await expect(row).toContainText("Not verified");
    await expect(page.locator("body")).not.toContainText("tok_");
    const tokenInAField = await page.evaluate(() =>
      [...document.querySelectorAll("input, textarea")].some((f) => (f as HTMLInputElement).value.includes("tok_")),
    );
    expect(tokenInAField, "the saved token stays in a field").toBe(false);
    await expectAccessible(page, "connections, with a connection");

    // Settings → Members & roles: the platform admin created the tenant, so owns it.
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: /Settings · Acme Retail/ })).toBeVisible();
    await expect(page.getByLabel(`Role of ${EMAIL}`)).toHaveValue("owner");
    await expectAccessible(page, "settings: members");
    await page.getByLabel("Email").fill("nobody@example.com");
    await page.getByRole("button", { name: "Add member" }).click();
    await expect(page.getByRole("alert")).toContainText("No Dewpoint account has that email");
    await expectAccessible(page, "settings: members, a refused addition");
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
    // Enter goes to the option the palette has selected: each step waits for what it acts on (the owner's review of
    // 5c6d802, after a run that went to Members; its cause unknown): the search focused, the letters in it, then
    // Security the selected option.
    const search = palette.getByRole("combobox");
    await expect(search).toBeVisible();
    await expect(search).toBeFocused();
    // Escape then ⌘K at once reopens it: the dialog's close event comes a task after Escape, and a ⌘K in between was
    // lost (a CI run of #82).
    await page.keyboard.press("Escape");
    await page.keyboard.press("ControlOrMeta+k");
    await expect(search).toBeVisible();
    await expect(search).toBeFocused();
    await page.keyboard.type("secur");
    await expect(search).toHaveValue("secur");
    await expect(palette.getByRole("option", { name: "Security", selected: true })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/account\/security/);

    // Reflow (WCAG 1.4.10): at 320 CSS pixels (1280 at 400 % zoom), no screen scrolls sideways, and each stays AA.
    await page.setViewportSize({ width: 320, height: 640 });
    const membersPath = connectionsPath.replace("/connections", "/settings/members");
    // Each screen is measured with its data in (a table widens a screen only once it has rows) and its banner shown.
    const screens: [string, string][] = [
      [connectionsPath, "Acme Prod"], [membersPath, EMAIL], ["/account/security", "No passkeys yet."], ["/tenants", "acme-retail"],
    ];
    for (const [path, content] of screens) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(content).first()).toBeVisible();
      await expect(page.getByRole("note", { name: "Deployment" })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${path} scrolls sideways at 320 px`).toBeLessThanOrEqual(0);
      await expectAccessible(page, `${path} at 320 px`);
    }
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.context().storageState({ path: ADMIN_STATE });
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
    await expect(page.getByText("No passkeys yet.")).toBeVisible(); // past the session check, with the list in
    await expectAccessible(page, "security");
    // Setting up an authenticator: its QR code and key, or the re-authentication it asks for first.
    await page.getByRole("button", { name: "Set up or replace authenticator app" }).click();
    await page.getByTestId("totp-start").click();
    // Sign-in was moments ago, inside the re-authentication window: the setup shows its QR code and key.
    await expect(page.getByRole("img", { name: "QR code for your authenticator app" })).toBeVisible();
    await expectAccessible(page, "security: authenticator setup");
    page.once("dialog", (d) => void d.accept("E2E key"));
    await page.getByTestId("passkey-add").click();
    await expect(page.getByText("E2E key")).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();

    await page.goto("/login");
    await page.getByTestId("login-passkey").click();
    await expect(page).toHaveURL(/\/tenants/);
  });
});
