// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schedule } from "../../../lib/triggers";
import { SCHEDULE } from "../../../test/triggers";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

// The OtherForms board's schedule: version 3's form, its site picked from Acme Prod's sites (a made-up service, D24).
const C1 = "00000000-0000-4000-8000-0000000000c1";
const LYON = "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d";
const FORM = {
  workflow_id: "w1", version_id: "v3", csv: null,
  fields: [{
    name: "site_id", title: "Site ID", type: "string", required: true, sensitive: false,
    picker: { node: "acme.sites.get@1", field: "site_id", connection: C1, list: { plugin: "Acme", title: "Org sites", noun: "sites" } },
  }],
};  // prettier-ignore
const NAMES = { site_id: { value: LYON, label: "Lyon DC" } };
const section = () => screen.getByRole("region", { name: "Schedules" });

function api(schedules: Schedule[], more: Record<string, () => Response> = {}) {
  return fakeApi({
    "GET /api/v1/trigger-types": () => json([]),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings: [] }),
    "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: { graph_format: 1 } }),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules }),
    "GET /api/v1/t/t1/workflows/w1/start-form": () => json(FORM),
    "GET /api/v1/t/t1/connections": () => json([{ id: C1, name: "Acme Prod", type: "acme", status: "ok", revision: 1, config: {}, secret_set: true }]),
    "POST /api/v1/t/t1/workflows/w1/input-options": () => json({ options: [{ value: LYON, label: "Lyon DC" }] }),
    ...more,
  });
}
afterEach(() => vi.restoreAllMocks());

async function pick(form: HTMLElement) {
  await userEvent.click(within(form).getByRole("button", { name: "Show choices: Site ID" }));
  await userEvent.click(await within(form).findByRole("option", { name: /^Lyon DC/ }));
}

describe("a picker in a schedule's form (the 4f-3 design §5.3, §5.5)", () => {
  it("lists the choices of the version whose input it shows, and adds the schedule with the pick's name", async () => {
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await pick(form);
    expect(sent.find((r) => r.path.endsWith("/input-options"))?.body).toEqual({ field: "site_id", query: "", expected_version_id: "v3" });
    expect(await within(form).findByText("Lyon DC, picked from Acme Prod's sites.")).toBeTruthy();
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "POST" && r.path.endsWith("/schedules"))?.body).toMatchObject({ input: { site_id: LYON }, names: NAMES }));
  });

  it("sends names only with an edited schedule's replaced input", async () => {
    const sent = api([SCHEDULE], { "PATCH /api/v1/t/t1/schedules/s1": () => json(SCHEDULE) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Every day at 07:00" }));
    const form = within(section()).getByRole("form", { name: 'Editing "Every day at 07:00"' });
    await userEvent.click(within(form).getByRole("button", { name: "Replace the input…" }));
    await pick(form);
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ input: { site_id: LYON }, names: NAMES }));
  });

  it("closes only the list on Escape, never the schedule's form", async () => {
    api([]);
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(within(form).getByRole("button", { name: "Show choices: Site ID" }));
    await within(form).findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}{Escape}");
    expect(within(form).queryByRole("listbox")).toBeNull();
    expect(within(section()).getByRole("form", { name: "New schedule" })).toBe(form);
  });

  it("says a simulated schedule's listing still reads the connection now", async () => {
    api([]);
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(within(form).getByRole("radio", { name: "Simulate" }));
    await userEvent.click(within(form).getByRole("button", { name: "Show choices: Site ID" }));
    await within(form).findByRole("listbox");
    expect(within(form).getByText("Read from Acme Prod now: listing changes nothing in Mist.")).toBeTruthy();
  });
});
