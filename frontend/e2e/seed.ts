// SPDX-License-Identifier: Apache-2.0
// Seeding the browser gate's runs through the API (editor 4e-1b; shared with 4e-2b's run form): workflows imported and
// published, their bindings bound to this tenant's connections (4f-3b), runs started and waited for, as the web client
// calls the API. Screens are checked light and dark.
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { expect, expectAccessible } from "./gate";

const ENDED = new Set(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** The API as the web client calls it: an unsafe request names the client and carries the session's CSRF token.
 * Publishing names the draft's revision it publishes (`If-Match`, as the editor does); a start, its idempotency key. */
export async function api(page: Page) {
  const tenant = await tenantId(page);
  const { csrf_token } = (await (await page.request.get("/api/v1/auth/session")).json()) as { csrf_token: string };
  const headers = { "X-Dewpoint-Client": "web", "X-CSRF-Token": csrf_token };
  const post = async (path: string, data: unknown, more: Record<string, string> = {}) => {
    const answer = await page.request.post(`/api/v1/t/${tenant}${path}`, { data, headers: { ...headers, ...more } });
    expect(answer.ok(), `POST ${path}: ${answer.status()}`).toBe(true);
    return (await answer.json()) as Record<string, unknown>;
  };
  const imported = async (fixture: string, name: string, bind: Record<string, string>) => {
    const document = JSON.parse(readFileSync(`e2e/fixtures/${fixture}`, "utf8")) as unknown;
    return post("/workflows/import", { name, document, bind });
  };
  return {
    tenant,
    /** A connection of this tenant's, by its name: its id. */
    async connection(name: string): Promise<string> {
      const listed = (await (await page.request.get(`/api/v1/t/${tenant}/connections`)).json()) as { id: string; name: string }[];
      return listed.find((c) => c.name === name)!.id;
    },
    /** A fixture imported under `name`, each binding in `bind` bound to the id given (one left out stays open), not
     * published: its workflow's id. */
    async imported(fixture: string, name: string, bind: Record<string, string> = {}): Promise<string> {
      return String((await imported(fixture, name, bind)).id);
    },
    /** A fixture imported under `name`, each binding in `bind` bound to the id given, and published: its workflow's id. */
    async publish(fixture: string, name: string, bind: Record<string, string> = {}): Promise<string> {
      const workflow = await imported(fixture, name, bind);
      await post(`/workflows/${String(workflow.id)}/publish`, { expected_latest_version: null }, { "If-Match": String(workflow.draft_revision) });
      return String(workflow.id);
    },
    /** A run started by hand, with the names its start form picked: its id. */
    async start(
      workflowId: string, input: Record<string, unknown>, mode: "live" | "simulate" = "live", names: Record<string, { value: string; label: string }> = {},
    ): Promise<string> {  // prettier-ignore
      return String((await post(`/workflows/${workflowId}/runs`, { input, mode, ...(Object.keys(names).length > 0 ? { names } : {}) }, { "Idempotency-Key": crypto.randomUUID() })).id);
    },
    /** Waits for a run to end, as the dispatcher and the worker run it. */
    async ended(runId: string): Promise<void> {
      await expect
        .poll(async () => ENDED.has(((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status), { timeout: 60_000 })
        .toBe(true);
    },
    /** Waits for a run to be running. */
    async running(runId: string): Promise<void> {
      await expect
        .poll(async () => ((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status, { timeout: 60_000 })
        .toBe("running");
    },
  };
}

/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
export async function accessibleBothWays(page: Page, screen: string): Promise<void> {
  await expectAccessible(page, `${screen}, light`);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page, `${screen}, dark`);
  await page.emulateMedia({ colorScheme: "light" });
}
