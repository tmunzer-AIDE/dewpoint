// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schedule } from "../../../lib/triggers";
import type { Validation } from "../../../lib/workflows";
import { SCHEDULE } from "../../../test/triggers";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

const FORM = {
  workflow_id: "w1", version_id: "v3", csv: null,
  fields: [{ name: "site", type: "string", required: true, sensitive: false, title: "Site" }, { name: "note", type: "string", required: false, sensitive: false, title: "Note" }],
};  // prettier-ignore
const section = () => screen.getByRole("region", { name: "Schedules" });

function api(schedules: Schedule[], more: Record<string, () => Response | Promise<Response>> = {}) {
  return fakeApi({
    "GET /api/v1/trigger-types": () => json([]),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings: [] }),
    "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: { graph_format: 1 } }),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules }),
    "GET /api/v1/t/t1/workflows/w1/start-form": () => json(FORM),
    ...more,
  });
}
afterEach(() => vi.restoreAllMocks());

describe("a workflow's schedules", () => {
  it("says each one in words, and what its sync proves, as the Schedules board does", async () => {
    api([
      SCHEDULE,
      { ...SCHEDULE, id: "s2", cron: "0 6 * * 1", generation: 1, synced_generation: 0 },
      { ...SCHEDULE, id: "s3", cron: "30 8 * * 1-5", time_zone: "America/New_York", generation: 4, synced_generation: 3, sync_error: "invalid_spec", sync_error_at: "2026-10-11T08:00:00Z" },
      { ...SCHEDULE, id: "s4", cron: null, every_s: 900, mode: "simulate", enabled: false },
      { ...SCHEDULE, id: "s5", cron: "0 */6 * * 1-5", time_zone: "UTC", misses: 3, misses_read_at: "2026-10-11T14:05:00Z", accounting_complete: false },
    ]);
    await showPanel();
    const rows = (await within(section()).findAllByRole("listitem")).map((r) => r.textContent ?? "");
    const said = [
      ["Every day at 07:00", "Europe/Paris · live · synced"],
      ["At 0 6 * * 1", "Saved; sync not yet confirmed: it may already fire."], // no preset says Mondays: its cron
      ["Weekdays at 08:30", "Sync failed: the scheduler refused this change. Its previous time may still fire"],
      ["Every 15 minutes", "simulated: nothing is sent · off · synced"],
      ["At 0 */6 * * 1-5", "UTC · live · custom · synced", "3 firings missed, counted at", "Some may be missed still, not yet counted."],
    ];
    said.forEach((parts, i) => parts.forEach((part) => expect(rows[i]).toContain(part)));
    expect(within(section()).getByRole("switch", { name: "Every day at 07:00" }).getAttribute("aria-checked")).toBe("true");
  });

  it("can't add one before a first publish, nor to a workflow that takes a CSV file, and says why", async () => {
    api([]);
    await showPanel({ activeNumber: null, activeVersionId: null });
    expect(within(section()).getByRole<HTMLButtonElement>("button", { name: "＋ Schedule" }).disabled).toBe(true);
    expect(section().textContent).toContain("A schedule runs the published version: publish a first version to add one.");
  });

  it("says a workflow that takes a CSV file can't run on a schedule", async () => {
    api([], { "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, csv: { columns: [], max_rows: 10, max_bytes: 10 } }) });
    await showPanel();
    await vi.waitFor(() => expect(section().textContent).toContain("It takes a CSV file: its rows come from an upload, so it can't run on a schedule."));
    expect(within(section()).getByRole<HTMLButtonElement>("button", { name: "＋ Schedule" }).disabled).toBe(true);
  });

  it("adds one on the published version's form, checking the input before anything is sent", async () => {
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    expect(form.textContent).toContain("Input · version 3's form");
    const zone = within(form).getByRole("combobox", { name: "Time zone" });
    await userEvent.clear(zone);
    await userEvent.type(zone, "Europe/Paris");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("Site is required.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.type(within(form).getByRole("textbox", { name: "Site (required)" }), "HQ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({
        cron: "0 7 * * *", every_s: null, offset_s: 0, time_zone: "Europe/Paris", catchup_window_s: 600, mode: "live", input: { site: "HQ" },
      }),
    );  // prettier-ignore
  });

  it("shows each refusal of its timing at the field it names", async () => {
    api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ error: "schedule_invalid", problems: [{ field: "cron", code: "cron_day_fields" }] }, 422) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "When" }), "Custom (cron)");
    await userEvent.type(within(form).getByRole("textbox", { name: "Cron" }), "0 9 1 * MON");
    await userEvent.type(within(form).getByRole("textbox", { name: "Site (required)" }), "HQ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    const cron = within(form).getByRole("textbox", { name: "Cron" });
    await vi.waitFor(() => expect(cron.getAttribute("aria-invalid")).toBe("true"));
    expect(form.textContent).toContain("Choose a day of the month or a day of the week, not both: put * in one of them.");
  });

  it("edits one: its stored input kept unless replaced whole, and only what changed sent", async () => {
    const sent = api([SCHEDULE], { "PATCH /api/v1/t/t1/schedules/s1": () => json({ ...SCHEDULE, mode: "simulate" }) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Every day at 07:00" }));
    const form = within(section()).getByRole("form", { name: 'Editing "Every day at 07:00"' });
    expect(form.textContent).toContain("Set when it was created; not shown back.");
    await userEvent.click(within(form).getByRole("radio", { name: "Simulate" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ mode: "simulate" }));
  });

  it.each([
    { title: "Every 90 seconds", every_s: 90, offset_s: 0 },
    { title: "Every 72 hours", every_s: 72 * 3600, offset_s: 51 * 3600 },
  ])("keeps a timing no preset says, $title, as it is, and sends the mode alone when only it changes", async ({ title, every_s, offset_s }) => {
    // The review of revision 1: such a timing opened as an empty cron, or a first run at 51:00, and blocked every save.
    const kept: Schedule = { ...SCHEDULE, cron: null, every_s, offset_s, time_zone: "UTC" };
    const sent = api([kept], { "PATCH /api/v1/t/t1/schedules/s1": () => json({ ...kept, mode: "simulate" }) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: `Edit ${title}` }));
    const form = within(section()).getByRole("form", { name: `Editing "${title}"` });
    expect(within(form).getByRole<HTMLOptionElement>("option", { name: `${title}, as it is` }).selected).toBe(true);
    expect(form.textContent).toContain("Set outside this form, it's kept as it is: choosing another When replaces it.");
    await userEvent.click(within(form).getByRole("radio", { name: "Simulate" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ mode: "simulate" }));
  });

  it("takes a list, an object or a value of several types as JSON, keeps a choice's type, and leaves out what isn't given", async () => {
    // The review of revision 1: ["ap-1"] typed for a list was sent as text.
    const fields = [
      { name: "aps", type: "array", required: true, sensitive: false, title: "APs" },
      { name: "meta", type: "object", required: false, sensitive: false },
      { name: "note", type: ["string", "null"], required: false, sensitive: false },
      { name: "level", type: "integer", required: false, sensitive: false, enum: [1, 2] },
    ];
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    const aps = within(form).getByRole("textbox", { name: "APs (required)" });
    expect(form.textContent).toContain('As JSON, like ["ap-1"] or {"site": "HQ"}; text in quotes.');
    await userEvent.click(aps);
    await userEvent.paste('["ap-1"');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("This isn't valid JSON, so it isn't saved.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.clear(aps);
    await userEvent.paste('["ap-1"]');
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "level" }), "2");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ aps: ["ap-1"], level: 2 }));
  });

  it.each([
    { what: "allOf", input_schema: { type: "object", allOf: [{ properties: { site: { type: "string" } }, required: ["site"] }] } },
    { what: "a $ref", input_schema: { $ref: "#/$defs/in", $defs: { in: { type: "object", properties: { site: { type: "string" } }, required: ["site"] } } } },
  ])("takes the whole input as JSON when the form can't show it field by field ($what)", async ({ input_schema }) => {
    // The review of revision 2: the start form has no field for these, so the form sent {}.
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields: [] }),
      "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: { graph_format: 1, settings: { input_schema } } }),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    const box = await within(form).findByRole("textbox", { name: "The input, as JSON" });
    expect(form.textContent).toContain("Version 3's input has rules this form can't show field by field: it's entered as JSON.");
    await userEvent.click(box);
    await userEvent.paste("[1]");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain('An object, like {"site": "HQ"}.');
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.clear(box);
    await userEvent.paste('{"site": "HQ"}');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "HQ" }));
  });

  it("takes the whole input as JSON on request, beside its fields", async () => {
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(within(form).getByRole("button", { name: "Enter it as JSON" }));
    await userEvent.click(within(form).getByRole("textbox", { name: "The input, as JSON" }));
    await userEvent.paste('{"site": "HQ", "extra": [1]}');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "HQ", extra: [1] }));
  });

  it("waits for the version's input before taking any, then starts its JSON from the fields' defaults", async () => {
    // The review of revision 3: a field filled while the version loaded was lost when its rules turned the form to JSON.
    let version: ((r: Response) => void) | undefined;
    const fields = [{ name: "site", type: "string", required: true, sensitive: false, title: "Site", default: "Lab" }];
    const input_schema = { type: "object", properties: { site: { type: "string", default: "Lab" } }, allOf: [{ required: ["site"] }] };
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }),
      "GET /api/v1/t/t1/workflows/w1/versions/v3": () => new Promise<Response>((resolve) => (version = resolve)),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    expect(form.textContent).toContain("Loading version 3's input…");
    expect(within(form).queryByRole("textbox", { name: "Site (required)" })).toBeNull();
    expect(within(form).getByRole<HTMLButtonElement>("button", { name: "Add the schedule" }).disabled).toBe(true);
    await vi.waitFor(() => expect(version).toBeDefined());
    version!(json({ id: "v3", number: 3, graph: { graph_format: 1, settings: { input_schema } } }));
    const box = await within(form).findByRole<HTMLTextAreaElement>("textbox", { name: "The input, as JSON" });
    expect(JSON.parse(box.value)).toEqual({ site: "Lab" });
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "Lab" }));
  });

  it("carries what's entered between the fields and the JSON, and keeps JSON no field can show", async () => {
    // The review of revision 3: a switch either way sent the other entry's empty input.
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.type(await within(form).findByRole("textbox", { name: "Site (required)" }), "HQ");
    await userEvent.type(within(form).getByRole("textbox", { name: "Note" }), "n");
    await userEvent.click(within(form).getByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole<HTMLTextAreaElement>("textbox", { name: "The input, as JSON" });
    expect(JSON.parse(box.value)).toEqual({ site: "HQ", note: "n" });
    await userEvent.clear(box);
    await userEvent.paste('{"site": "Lab", "extra": 1}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(form.textContent).toContain("No field here shows extra as written: it stays as JSON.");
    await userEvent.clear(box);
    await userEvent.paste('{"site": "Lab"}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Site (required)" }).value).toBe("Lab");
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Note" }).value).toBe("");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "Lab" }));
  });

  it("keeps an empty text in the JSON, required or not: a field's empty control means not given", async () => {
    // The review of revision 4: {"site": ""} moved to the fields was sent as {}, or refused as required.
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(form).findByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole("textbox", { name: "The input, as JSON" });
    await userEvent.click(box);
    await userEvent.paste('{"site": "HQ", "note": ""}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(form.textContent).toContain("No field here shows note as written: it stays as JSON.");
    await userEvent.clear(box);
    await userEvent.paste('{"site": ""}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(form.textContent).toContain("No field here shows site as written: it stays as JSON.");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "" }));
  });

  it("keeps text with a line break in the JSON, and moves spaces and tabs to a field as they are", async () => {
    // The review of revision 5: a one-line field drops line breaks, so "HQ\nLab" was sent as "HQLab".
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(form).findByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole("textbox", { name: "The input, as JSON" });
    for (const broken of ["HQ\nLab", "HQ\rLab", "HQ\r\nLab"]) {
      await userEvent.clear(box);
      await userEvent.click(box);
      await userEvent.paste(JSON.stringify({ site: broken }));
      await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
      expect(form.textContent, JSON.stringify(broken)).toContain("No field here shows site as written: it stays as JSON.");
    }
    await userEvent.clear(box);
    await userEvent.click(box);
    await userEvent.paste(JSON.stringify({ site: " HQ\tLab " }));
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Site (required)" }).value).toBe(" HQ\tLab ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: " HQ\tLab " }));
  });

  it("refuses JSON whose numbers parsing would change, in the whole input and in a field", async () => {
    // The review of revision 3: 9007199254740993 was sent as …992, and 1e400 as null.
    const fields = [{ name: "aps", type: "array", required: false, sensitive: false, title: "APs" }];
    const sent = api([], { "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(form).findByRole("textbox", { name: "APs" }));
    await userEvent.paste("[9007199254740993]");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("A whole number here is too large to keep exactly, so it isn't saved.");
    await userEvent.clear(within(form).getByRole("textbox", { name: "APs" }));
    await userEvent.click(within(form).getByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole("textbox", { name: "The input, as JSON" });
    await userEvent.click(box);
    await userEvent.paste('{"meta": [1e400]}');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("A number here is too large to keep, so it isn't saved.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
  });

  it("keeps a key named __proto__, typed in the JSON or as a field's name", async () => {
    // The review of revision 3: copying the input set its prototype instead, and the key was gone.
    const fields = [{ name: "__proto__", type: "string", required: true, sensitive: false, title: "Proto" }];
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    const proto = await within(form).findByRole<HTMLInputElement>("textbox", { name: "Proto (required)" });
    expect(proto.value).toBe("");
    await userEvent.type(proto, "HQ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect(sent.filter((r) => r.method === "POST")).toHaveLength(1));
    const first = (sent.find((r) => r.method === "POST")!.body as { input: object }).input;
    expect(Object.getOwnPropertyDescriptor(first, "__proto__")?.value).toBe("HQ");
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const again = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(again).findByRole("button", { name: "Enter it as JSON" }));
    await userEvent.click(within(again).getByRole("textbox", { name: "The input, as JSON" }));
    await userEvent.paste('{"__proto__": "HQ", "site": "HQ"}');
    await userEvent.click(within(again).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect(sent.filter((r) => r.method === "POST")).toHaveLength(2));
    const second = (sent.filter((r) => r.method === "POST")[1]!.body as { input: object }).input;
    expect(Object.keys(second)).toEqual(["__proto__", "site"]);
  });

  it("replaces an edited one's input whole, never showing the stored one", async () => {
    const sent = api([SCHEDULE], { "PATCH /api/v1/t/t1/schedules/s1": () => json(SCHEDULE) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Every day at 07:00" }));
    const form = within(section()).getByRole("form", { name: 'Editing "Every day at 07:00"' });
    await userEvent.click(within(form).getByRole("button", { name: "Replace the input…" }));
    expect(form.textContent).toContain("The stored input isn't shown back: what you enter here replaces it whole.");
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Site (required)" }).value).toBe("");
    await userEvent.type(within(form).getByRole("textbox", { name: "Site (required)" }), "Lab");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ input: { site: "Lab" } }));
  });

  it("gives focus back to a schedule's Edit once its form closes, by Cancel, Escape or Save", async () => {
    // The final review: an edited schedule's form left focus on the page's body.
    api([SCHEDULE], { "PATCH /api/v1/t/t1/schedules/s1": () => json({ ...SCHEDULE, mode: "simulate" }) });
    await showPanel();
    const edit = () => within(section()).getByRole("button", { name: "Edit Every day at 07:00" });
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Every day at 07:00" }));
    await userEvent.click(within(section()).getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(edit()));
    await userEvent.click(edit());
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() => expect(document.activeElement).toBe(edit()));
    await userEvent.click(edit());
    await userEvent.click(within(section()).getByRole("radio", { name: "Simulate" }));
    await userEvent.click(within(section()).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(edit()));
  });

  it("turns one off at once, and deletes one after asking", async () => {
    const sent = api([SCHEDULE], {
      "PATCH /api/v1/t/t1/schedules/s1": () => json({ ...SCHEDULE, enabled: false }),
      "DELETE /api/v1/t/t1/schedules/s1": () => new Response(null, { status: 204 }),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("switch", { name: "Every day at 07:00" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ enabled: false }));
    await userEvent.click(within(section()).getByRole("button", { name: "Edit Every day at 07:00" }));
    await userEvent.click(within(section()).getByRole("button", { name: "Delete the schedule…" }));
    const ask = screen.getByRole("dialog", { name: 'Delete the schedule "Every day at 07:00"?' });
    expect(ask.textContent).toContain("Runs it started stay in the run history.");
    await userEvent.click(within(ask).getByRole("button", { name: "Delete the schedule" }));
    await vi.waitFor(() => expect(sent.some((r) => r.method === "DELETE" && r.path === "/api/v1/t/t1/schedules/s1")).toBe(true));
  });

  it("says which live schedules the draft would break, from the server's check", async () => {
    api([SCHEDULE]);
    const check: Validation = {
      draft_revision: 1, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] }, conditional_steps: [],
      schedule_breaks: [{ schedule_id: "s1", reasons: ["`site` is required now."], more: false }],
    };  // prettier-ignore
    await showPanel({ check });
    await vi.waitFor(() =>
      expect(section().textContent).toContain(
        "Publishing this draft would make it fail each time: its stored input doesn't fit the draft's input (`site` is required now). After publishing, replace its input; or change the draft's input back.",
      ),
    );
  });

  it("shows a viewer each schedule without its controls", async () => {
    api([SCHEDULE]);
    await showPanel({ editable: false, manage: false, viewer: true });
    await within(section()).findByText("Every day at 07:00");
    expect(within(section()).queryByRole("switch")).toBeNull();
    expect(within(section()).queryByRole("button", { name: "＋ Schedule" })).toBeNull();
    expect(section().textContent).toContain("On");
  });
});
