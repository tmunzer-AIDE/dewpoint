// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "violet-otter-canyon-42";
let totpSecret = "";

function code(secret: string, offsetSeconds = 0): string {
  return new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(secret) }).generate({ timestamp: Date.now() + offsetSeconds * 1000 });
}

async function passwordLogin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("login-email").fill(EMAIL);
  await page.getByTestId("login-password").fill(PASSWORD);
  await page.getByTestId("login-submit").click();
}

test.describe.serial("foundations", () => {
  test("first login enrolls TOTP, creates a tenant and a Mist connection", async ({ page }) => {
    await passwordLogin(page);
    await expect(page).toHaveURL(/\/enroll/);
    await page.getByRole("button", { name: "Authenticator app" }).click();
    totpSecret = (await page.getByTestId("totp-secret").textContent())!.replace(/\s/g, "");
    await page.getByTestId("totp-code").fill(code(totpSecret));
    await page.getByTestId("totp-submit").click();
    await expect(page.getByTestId("recovery-codes")).toBeVisible();
    await page.getByTestId("recovery-ack").check();
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page).toHaveURL(/\/tenants/);
    await page.getByTestId("tenant-name").fill("Acme Retail");
    await page.getByTestId("tenant-slug").fill("acme-retail");
    await page.getByTestId("tenant-create").click();
    await page.getByTestId("tenant-switcher").click();
    await page.getByRole("menuitem", { name: /Acme Retail/ }).click();

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
    await page.getByTestId("totp-code").fill(code(totpSecret, 30)); // next step: the current one was consumed
    await page.getByTestId("totp-submit").click();
    await expect(page).toHaveURL(/\/tenants/); // wait: the MFA response rotates the session cookie
    await page.goto("/account/security");
    page.once("dialog", (d) => void d.accept("E2E key"));
    await page.getByTestId("passkey-add").click();
    await expect(page.getByText("E2E key")).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();

    await page.goto("/login");
    await page.getByTestId("login-passkey").click();
    await expect(page).toHaveURL(/\/tenants/);
  });
});
