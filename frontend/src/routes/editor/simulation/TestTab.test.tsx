// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SeedContract } from "../../../lib/simulations";
import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
import { TestTab } from "./TestTab";
import type { SimulationSession } from "./useSimulation";

const SEEDS = "/api/v1/t/t1/workflows/w1/draft/steps/id-notify/seeds";
const NOTIFY = { id: "id-notify", key: "notify", type: "slack.post@1", config: {} } as unknown as GraphNode;
const DOC = { graph_format: 1, nodes: [NOTIFY], edges: [] } as unknown as GraphDoc;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let contract: () => Response;
let asked: string[];
beforeEach(() => {
  asked = [];
  contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: null, entries: [] } satisfies SeedContract);
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = new URL((input as Request).url);
    asked.push(url.pathname + url.search);
    return Promise.resolve(url.pathname === SEEDS ? contract() : json({ error: "not_found" }, 404));
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
  render(
    <QueryClientProvider client={qc}>
      <TestTab {...props} />
    </QueryClientProvider>,
  );
  return props;
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
