// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Sample, ScopeEntry } from "../../../lib/data";
import { typeWith } from "../../../test/nodeTypes";
import { fakeApi, json, NODE_ID, showFields } from "./harness";
import { PillDetails } from "./PillDetails";

const NOTE = typeWith({ type: "object", properties: { message: { type: "string" } } }, { ref: "acme.note@1", type: "acme.note", title: "Post a note" });
const SITE = "00000000-0000-4000-8000-000000000002";
const steps = [
  { id: NODE_ID, key: "step", title: "Post a note" },
  { id: SITE, key: "get_site", title: "Get a site" },
];
const PATH = "steps.get_site.output.timezone";
const ENTRY: ScopeEntry = {
  children: false, format: null, missing: true, name: "timezone", nameable: true, nullable: false, parent: null, path: PATH,
  problem: null, root: "steps", sensitive: false, step: SITE, types: ["string"],
  formula: { guards: [{ kind: "present", path: PATH, size: null }], null_test: false, sensitive: false },
};  // prettier-ignore

const sample = (over: Partial<Sample> = {}): Sample => ({
  attempt: 1, captured_at: "2026-10-10T14:02:00Z", iteration_key: "", mode: "live", run_id: "4f2c19e1-0000-4000-8000-000000000000",
  run_kind: "run", same_config: true, same_type: true, stale: false, type: "mist.site.get@1", version_id: "v", version_number: 3,
  output: { name: "HQ", timezone: "America/Los_Angeles" },
  connections: { state: "recorded", items: [{ connection_id: "c1", context: {}, current_revision: 1, name: "Acme Prod", revision: 1, state: "unchanged", type: "mist" }] },
  ...over,
});  // prettier-ignore

function show(answer: { sample: Sample | null; searched_runs?: number }) {
  fakeApi({
    "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
      json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [ENTRY], more: false, problem: null }),
    "GET /api/v1/t/t1/workflows/w1/draft/samples": (q) =>
      q.get("node") === SITE
        ? json({ draft_revision: 1, node: SITE, sample: answer.sample, searched_runs: answer.searched_runs ?? 1, search_limit: 200 })
        : json({ error: "not_found" }, 404),
  });
  showFields(NOTE, { steps }, <PillDetails field="/message" pill={{ ref: PATH }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
}

afterEach(() => vi.restoreAllMocks());

describe("a pill's details", () => {
  it("says its type, why it may be missing, and the value a past run gave, with that run", async () => {
    show({ sample: sample() });
    expect(await screen.findByText("text")).toBeTruthy();
    expect(screen.getByText(/it's optional in its data/)).toBeTruthy();
    expect((await screen.findByText(/America\/Los_Angeles/)).textContent).toBe('"America/Los_Angeles"');
    expect(screen.getByText(/4f2c19e1 · version 3 · live · succeeded/)).toBeTruthy();
    expect(screen.getByText("Acme Prod (mist) · unchanged since")).toBeTruthy();
  });

  it("asks for a step's sample again each time its details open: a run may have ended since (the review of revision 1)", async () => {
    let current: Sample | null = null;
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [ENTRY], more: false, problem: null }),
      "GET /api/v1/t/t1/workflows/w1/draft/samples": () =>
        json({ draft_revision: 1, node: SITE, sample: current, searched_runs: current ? 1 : 0, search_limit: 200 }),
    });
    const f = showFields(NOTE, { steps }, <PillDetails field="/message" pill={{ ref: PATH }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText(/hasn't finished a run yet/)).toBeTruthy();
    current = sample();
    f.remount();
    expect(await screen.findByText(/America\/Los_Angeles/)).toBeTruthy();
  });

  it("says a version's details show no sample, and never asks for one (the review of milestone 2)", () => {
    const sent = fakeApi({});
    showFields(NOTE, { steps, revision: null, editable: false }, <PillDetails field="/message" pill={{ ref: PATH }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText("A version's data isn't shown: open the draft to see a past run's sample.")).toBeTruthy();
    expect(screen.queryByText("Looking for a sample…")).toBeNull();
    expect(sent).toEqual([]);
  });

  it("says a pill to a step no longer in the draft has no sample, never that it's looking (the final review)", async () => {
    const sent = fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [], more: false, problem: null }),
    });
    showFields(NOTE, { steps }, <PillDetails field="/message" pill={{ ref: "steps.gone.output.x" }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText("gone isn't a step of this draft, so it has no sample.")).toBeTruthy();
    expect(screen.queryByText("Looking for a sample…")).toBeNull();
    expect(sent.some((r) => r.path.endsWith("/samples"))).toBe(false);
  });

  it("shows a default already written though the value is always there now, and removable (the final review)", async () => {
    const always: ScopeEntry = { ...ENTRY, missing: false, formula: { guards: [], null_test: false, sensitive: false } };
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [always], more: false, problem: null }),
      "GET /api/v1/t/t1/workflows/w1/draft/samples": () => json({ draft_revision: 1, node: SITE, sample: null, searched_runs: 0, search_limit: 200 }),
    });
    showFields(NOTE, { steps }, <PillDetails field="/message" pill={{ ref: PATH, default: "UTC" }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
    expect((await screen.findByLabelText<HTMLInputElement>("If it's missing or null")).value).toBe("UTC");
    expect(screen.getByRole("button", { name: "Remove the default" })).toBeTruthy();
  });

  it("shows a default in a version's view, read only (the final review)", () => {
    fakeApi({});
    showFields(NOTE, { steps, revision: null, editable: false }, <PillDetails field="/message" pill={{ ref: PATH, default: "UTC" }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
    const input = screen.getByLabelText<HTMLInputElement>("If it's missing or null");
    expect([input.value, input.disabled]).toEqual(["UTC", true]);
    expect(screen.queryByRole("button", { name: "Remove the default" })).toBeNull();
  });

  it("shows a redacted value as a chip, never the value", async () => {
    show({ sample: sample({ output: { timezone: "Bearer [redacted]" } }) });
    const chip = await screen.findByText("redacted");
    expect(chip.parentElement?.textContent).toBe('"Bearer redacted"');
  });

  it("says a preview too large to keep, and what the step's settings or connection changed", async () => {
    show({ sample: sample({ output: "[truncated]", same_config: false }) });
    expect(await screen.findByText("truncated")).toBeTruthy();
    expect(screen.getByText(/over 8 KiB/)).toBeTruthy();
    expect(screen.getByText(/get_site's settings have changed since this run/)).toBeTruthy();
  });

  it("says a run's connection changed since, or isn't known, or wasn't used", async () => {
    show({ sample: sample({ stale: true, connections: { state: "recorded", items: [{ connection_id: "c1", context: {}, current_revision: 5, name: "Acme Prod", revision: 3, state: "changed", type: "mist" }] } }) });
    expect(await screen.findByText("Acme Prod (mist) · revision 3 then, 5 now")).toBeTruthy();
    expect(screen.getByText(/Its connection has changed since this run/)).toBeTruthy();
  });

  it("says when no run gave a sample: none finished, none succeeded, or none in the newest 200", async () => {
    show({ sample: null, searched_runs: 0 });
    expect(await screen.findByText(/hasn't finished a run yet/)).toBeTruthy();
  });

  it("says no sample was found in the newest runs searched", async () => {
    show({ sample: null, searched_runs: 200 });
    expect(await screen.findByText("get_site hasn't succeeded in the newest 200 finished runs of this workflow.")).toBeTruthy();
  });
});
