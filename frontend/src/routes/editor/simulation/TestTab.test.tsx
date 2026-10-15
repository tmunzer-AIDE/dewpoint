// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/client";
import type { SeedContract, SeedEntry } from "../../../lib/simulations";
import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
import { TestTab } from "./TestTab";
import type { SimulationSession } from "./useSimulation";

const SEEDS = "/api/v1/t/t1/workflows/w1/draft/steps/id-notify/seeds";
const NOTIFY = { id: "id-notify", key: "notify", type: "slack.post@1", config: {} } as unknown as GraphNode;
const DOC = { graph_format: 1, nodes: [NOTIFY], edges: [] } as unknown as GraphDoc;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let contract: (revision: number) => Response;
let asked: string[];
beforeEach(() => {
  asked = [];
  contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: null, entries: [] } satisfies SeedContract);
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = new URL((input as Request).url);
    asked.push(url.pathname + url.search);
    return Promise.resolve(url.pathname === SEEDS ? contract(Number(url.searchParams.get("revision"))) : json({ error: "not_found" }, 404));
  });
});
afterEach(() => vi.restoreAllMocks());

/** A paragraph saying exactly this, whatever its parts (a key in mono). */
const said = (text: string) => (_: string, el: Element | null) => el?.tagName === "P" && el.textContent === text;

function idle(): SimulationSession {
  return {
    local: { kind: "idle" }, state: null, steps: null, phase: null, busy: false, readFailed: false, asOf: null,
    start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(), readAgain: vi.fn(),
  };  // prettier-ignore
}

function show(over: Partial<Parameters<typeof TestTab>[0]> = {}) {
  const props = {
    tenantId: "t1", workflowId: "w1", node: NOTIFY, doc: DOC, types: new Map<string, NodeType>(), revision: 14, session: idle(),
    blocked: false, onSave: vi.fn(() => Promise.resolve(14)), onStart: vi.fn(), onSimulateWorkflow: vi.fn(), onGoTo: vi.fn(),
    onShowProblems: vi.fn(), ...over,
  };  // prettier-ignore
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <TestTab {...props} />
    </QueryClientProvider>,
  );
  /** The editor's next render: a revision saved, a simulation sent. */
  const again = (more: Partial<Parameters<typeof TestTab>[0]>) =>
    view.rerender(
      <QueryClientProvider client={qc}>
        <TestTab {...props} {...more} />
      </QueryClientProvider>,
    );
  return { ...props, again };
}

describe("the Test tab (§7.6; the TestTab and TestOther boards)", () => {
  it("reads the values a step reads, at the draft's saved revision", async () => {
    show();
    expect(await screen.findByText(said("Runs notify alone, with these values in place of what the steps before it would give. Nothing is sent."))).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Values it reads" })).toBeTruthy();
    expect(screen.getByText("revision 14")).toBeTruthy();
    expect(asked).toEqual([`${SEEDS}?revision=14`]);
  });

  it("says why a step can't run alone, in the server's words, and offers Simulate workflow", async () => {
    contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: "This step can't be simulated alone: simulate the workflow to see it run.", entries: [] });
    const p = show();
    expect(await screen.findByText("This step can't be simulated alone: simulate the workflow to see it run.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Values it reads" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
    expect(p.onSimulateWorkflow).toHaveBeenCalled();
  });

  it("asks for the draft's problems to be fixed first", async () => {
    contract = () => json({ error: "invalid", diagnostics: [{ code: "ref.unknown", message: "A reference to get_sit, which isn't a step.", node: "id-notify", field: null, fix: null, severity: "error" }] }, 422);
    const p = show();
    expect(await screen.findByText("Fix 1 problem first: a draft with problems isn't simulated.")).toBeTruthy();
    expect(screen.queryByText("Not simulated")).toBeNull(); // nothing was tried yet
    await userEvent.click(screen.getByRole("button", { name: "Show the problems" }));
    expect(p.onShowProblems).toHaveBeenCalled();
  });

  it("says a new step is read once the draft is saved", async () => {
    contract = () => json({ error: "not_found" }, 404);
    show();
    expect(await screen.findByText("This step isn't in the saved draft yet: its values are read once it's saved.")).toBeTruthy();
  });

  it("says when the values couldn't be read, and reads them again", async () => {
    contract = () => json({ error: "http_error" }, 500);
    show();
    expect(await screen.findByText("The values it reads couldn't be read.")).toBeTruthy();
    contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: null, entries: [] });
    await userEvent.click(screen.getByRole("button", { name: "Read them again" }));
    expect(await screen.findByRole("heading", { name: "Values it reads" })).toBeTruthy();
  });
});

const entry = (pointer: string, over: Partial<SeedEntry> = {}): SeedEntry => ({
  pointer, types: ["string"], required: true, nullable: false, sensitive: false, prefill: { state: "typed", reason: "not_step_output", value: null }, ...over,
});  // prettier-ignore
const ENTRIES = [
  entry("/steps/get_site/output/name", { prefill: { state: "prefilled", reason: null, value: "HQ Paris" } }),
  entry("/vars/channel", { required: false, nullable: true }),
  entry("/trigger/api_token", { sensitive: true, prefill: { state: "typed", reason: "sensitive", value: null } }),
];
/** What a control's description says: its hint and its error, as a screen reader reads them. */
const description = (el: HTMLElement) =>
  (el.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean).map((id) => document.getElementById(id)?.textContent ?? "").join(" ");

describe("the values a step test sends (§7.6; the TestTab and TestOther boards)", () => {
  beforeEach(() => {
    contract = (revision) => json({ draft_revision: revision, step_id: "id-notify", refused: null, entries: ENTRIES } satisfies SeedContract);
  });

  it("prefills a value from its step's own sample, and clears it", async () => {
    show();
    const name = await screen.findByRole("textbox", { name: "name required text" });
    expect(name).toHaveProperty("value", "HQ Paris");
    expect(description(name)).toBe("From get_site's sample.");
    expect(screen.getByText("/steps/get_site/output/name")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Clear name" }));
    expect(name).toHaveProperty("value", "");
    expect(description(name)).toBe("");
  });

  it("offers Null and Absent where the step's read allows them", async () => {
    show();
    const choice = await screen.findByRole("radiogroup", { name: "channel optional nullable text" });
    expect(within(choice).getAllByRole("radio").map((r) => r.parentElement?.textContent)).toEqual(["A value", "Null", "Absent: as if it was never set"]);
  });

  it("types a sensitive value, never prefilled", async () => {
    show();
    const token = await screen.findByLabelText("api_token required sensitive text");
    expect(token.getAttribute("type")).toBe("password");
    expect(description(token)).toBe("Sensitive: typed, never prefilled. Kept as a protected value.");
  });

  it("says which values are missing, on each, and sends nothing", async () => {
    const p = show();
    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate step" }));
    expect(await screen.findByText("Not simulated: 2 values are missing.")).toBeTruthy();
    expect(description(screen.getByLabelText("api_token required sensitive text"))).toContain("Give a value: notify reads it without a default.");
    expect(screen.getByText("Give a value, or choose Absent.")).toBeTruthy();
    expect(p.onStart).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("api_token required sensitive text"), "s3cret");
    expect(screen.getByText("Not simulated: 1 value is missing.")).toBeTruthy(); // as each is given
  });

  it("sends the values at the revision the save made, as the step's own simulation", async () => {
    const p = show();
    await userEvent.type(await screen.findByLabelText("api_token required sensitive text"), "s3cret");
    await userEvent.click(within(screen.getByRole("radiogroup", { name: "channel optional nullable text" })).getByRole("radio", { name: "Absent: as if it was never set" }));
    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate step" }));
    await vi.waitFor(() => expect(p.onStart).toHaveBeenCalled());
    expect(p.onSave).toHaveBeenCalled();
    expect(vi.mocked(p.onStart).mock.calls[0]![0]).toMatchObject({
      revision: 14,
      body: { target: { step_id: "id-notify", values: { "/steps/get_site/output/name": "HQ Paris", "/trigger/api_token": "s3cret" }, absent: ["/vars/channel"] } },
    });
    expect(screen.getByText("Each value is checked against what notify reads.")).toBeTruthy();
  });

  it("reads the values again when saving moved the draft, and sends nothing until they're checked", async () => {
    contract = (revision) =>
      json({ draft_revision: revision, step_id: "id-notify", refused: null, entries: revision === 15 ? [...ENTRIES, entry("/vars/severity")] : ENTRIES });
    const p = show({ onSave: vi.fn(() => Promise.resolve(15)) });
    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate step" }));
    p.again({ revision: 15 });
    expect(await screen.findByText("Saving moved the draft to revision 15, and notify now reads one more value. Check the values, then simulate.")).toBeTruthy();
    expect(screen.getByText("new in revision 15")).toBeTruthy();
    expect(p.onStart).not.toHaveBeenCalled();
  });

  it("puts a refused value's problem on its field, and one with no field above the form", async () => {
    const p = show();
    await screen.findByLabelText("api_token required sensitive text");
    const frozen = { key: "k1", revision: 14, body: { target: { step_id: "id-notify", values: {}, absent: [] } } };
    const error = new ApiError(422, "seed_missing", { error: "seed_missing", problems: [
      { code: "seed_missing", pointer: "/trigger/api_token", message: "A value is required here." },
      { code: "seed_unknown", pointer: "/vars/gone", message: "Nothing reads this." },
    ] });  // prettier-ignore
    p.again({ session: { ...idle(), local: { kind: "refused", frozen, error } } });
    expect(description(await screen.findByLabelText("api_token required sensitive text"))).toContain("A value is required here.");
    expect(screen.getByText("Not simulated")).toBeTruthy();
    expect(screen.getByText("/vars/gone: Nothing reads this.")).toBeTruthy();
  });

  it("waits while Simulate waits", async () => {
    show({ blocked: true });
    expect((await screen.findByRole("button", { name: "◌ Simulate step" })).hasAttribute("disabled")).toBe(true);
  });
});
