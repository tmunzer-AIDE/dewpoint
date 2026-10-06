// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { cancelLeaving, mayLeave } from "../../lib/leaving";
import type { CanvasProps } from "./Canvas";
import { EditorPage } from "./Editor";

// Every document the stand-in canvas was handed: what was drawn, and what never was.
const { drawn } = vi.hoisted(() => ({ drawn: [] as { doc: GraphDoc; editable: boolean }[] }));

vi.mock("./Canvas", async () => {
  const { useEffect } = await import("react");
  return {
    Canvas: (props: CanvasProps) => {
      drawn.push({ doc: props.doc, editable: props.editable });
      useEffect(() => {
        if (props.focusRequest) document.querySelector<HTMLElement>(`[data-item="${props.focusRequest.id}"]`)?.focus();
      }, [props.focusRequest]);
      return (
        <div
          role="group"
          aria-label="Workflow steps"
          onKeyDown={props.onKeyDown}
          onFocus={(e) => {
            // As the canvas does: the item that takes focus, by a click, Tab or a key, becomes the tab stop.
            const id = (e.target as HTMLElement).dataset.item;
            if (id) props.onFocusItem(id);
          }}
          data-editable={String(props.editable)}
          data-problems={String(props.problems.size)}
          data-problem-steps={[...props.problems.keys()].join(",")}
        >
          <button data-item="start" onClick={() => props.onItem({ kind: "after", from: null })}>Start</button>
          {(props.doc.nodes ?? []).map((n) => (
            <span key={n.id}>
              <button data-item={`node:${n.id}`} onClick={() => props.onItem({ kind: "open", node: n.id })}>{n.key}</button>
              <button onClick={() => props.onItem({ kind: "after", from: { node: n.id, port: "out" } })}>after {n.key}</button>
            </span>
          ))}
          {props.placing && <button onClick={() => props.onPlace({ x: 400, y: 300 })}>place here</button>}
        </div>
      );
    },
  };
});

const TYPES = [{
  ref: "flow.transform@1", type: "flow.transform", version: 1, kind: "control", state: "active", title: "Transform",
  description: "", ports: ["out"], dynamic_ports: null, config_schema: {}, output_schema: {}, side_effect: "none",
  credentials: [], capabilities: [], retry: { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] }, timeout_s: 60,
}];  // prettier-ignore
/** A draft of transform steps with these keys, one under the other. */
const draftWith = (...keys: string[]): GraphDoc => ({
  graph_format: 1,
  nodes: keys.map((key, i) => ({ id: `id-${key}`, key, type: "flow.transform@1", position: { x: 0, y: 140 * (i + 1) } })),
  edges: [],
});
const WORKFLOW = {
  id: "w1", name: "Nightly", enabled: true, draft_revision: 1, active_version_id: null, active_version_number: null,
  executable: null, blocked_by: [], created_at: "", updated_at: "", unpublished_changes: true, draft_graph_hash: "h1",
  last_run: null, last_simulation: null, runs_24h: { live: 0, simulate: 0 }, needs_attention: [], draft: draftWith(),
};  // prettier-ignore
const BASE = "/api/v1/t/t1/workflows/w1";
type Answer = () => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
let role = "editor";
let answers: Map<string, Answer>; // "METHOD path" → its answer: a test sets what it needs
let sent: { method: string; path: string; headers: Headers; body: unknown }[];

beforeEach(() => {
  role = "editor";
  drawn.length = 0;
  sent = [];
  answers = new Map<string, Answer>([
    ["GET /api/v1/node-types", () => json(TYPES)],
    ["GET /api/v1/t/t1", () => json({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role })],
    [`GET ${BASE}`, () => json(WORKFLOW)],
    [`PUT ${BASE}/draft`, () =>
      json({ draft_revision: 2, unpublished_changes: true, graph_hash: "h2", active_version_id: null, active_version_number: null })],
    [`POST ${BASE}/validate`, () => json({ draft_revision: 1, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] } })],
  ]);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, headers: request.headers, body: text ? JSON.parse(text) : null });
    const answer = answers.get(`${request.method} ${path}`);
    return answer ? answer() : json({ error: "not_found" }, 404);
  });
});

/** The editor on its route, beside the list's; `seed` fills the query cache first, as an earlier visit would. */
async function show({ seed }: { seed?: (qc: QueryClient) => void } = {}) {
  const root = createRootRoute({ component: Outlet });
  const list = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows", component: () => <p>list</p> });
  const editor = createRoute({
    getParentRoute: () => root,
    path: "/t/$tenantId/workflows/$workflowId",
    component: () => <EditorPage tenantId="t1" workflowId="w1" />,
  });
  const router = createRouter({
    routeTree: root.addChildren([list, editor]),
    history: createMemoryHistory({ initialEntries: ["/t/t1/workflows/w1"] }),
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed?.(qc);
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("group", { name: "Workflow steps" });
  return { router, qc };
}

it("heads the editor with the way back and the workflow's name", async () => {
  await show();
  expect(screen.getByRole("link", { name: "Workflows" })).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1, name: "Nightly" })).toBeTruthy();
});

it("adds a first step from the start card, then one after it, through the picker", async () => {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
});

it("offers a viewer no Add step", async () => {
  role = "viewer";
  await show();
  expect(screen.queryByRole("button", { name: /Add step/ })).toBeNull();
});

async function withTwoSteps() {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await screen.findByRole("button", { name: "transform_2" });
}

it("deletes the focused step with Delete, after asking, and heals the chain in words", async () => {
  await withTwoSteps();
  screen.getByRole("button", { name: "transform" }).focus();
  await userEvent.keyboard("{Delete}");
  const ask = screen.getByRole("dialog", { name: "Delete a step" });
  expect(ask.textContent).toContain("transform and its edges are deleted.");
  await userEvent.click(within(ask).getByRole("button", { name: "Delete" }));
  expect(screen.queryByRole("button", { name: "transform" })).toBeNull();
  expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
});

it("opens the picker after the focused step with A, and undoes and redoes", async () => {
  await withTwoSteps();
  screen.getByRole("button", { name: "transform_2" }).focus();
  await userEvent.keyboard("a");
  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
  await userEvent.keyboard("{Escape}");
  screen.getByRole("button", { name: "transform_2" }).focus();
  await userEvent.keyboard("{Control>}z{/Control}");
  expect(screen.queryByRole("button", { name: "transform_2" })).toBeNull();
  // Focus moved to the step before it by itself (the owner's review of M3): redo is heard without repairing it.
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "transform" })));
  await userEvent.keyboard("{Control>}{Shift>}z{/Shift}{/Control}");
  expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
});

it("opens a step's panel on Enter, its heading focused, and Escape gives focus back to the step", async () => {
  await withTwoSteps();
  const step = screen.getByRole("button", { name: "transform_2" });
  step.focus();
  await userEvent.keyboard("{Enter}");
  const panel = screen.getByRole("complementary", { name: "transform_2" });
  expect(document.activeElement).toBe(within(panel).getByRole("heading", { name: "transform_2" }));
  expect(panel.textContent).toContain("Transform · flow.transform@1");
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(document.activeElement).toBe(step);
});

const at = (key: string) => drawn.at(-1)!.doc.nodes!.find((n) => n.key === key)!.position;

it("places a step where a single pointer clicks, never by dragging (WCAG 2.5.7)", async () => {
  await withTwoSteps();
  await userEvent.click(screen.getByRole("button", { name: "transform" })); // its panel
  await userEvent.click(screen.getByRole("button", { name: "Place on the canvas…" }));
  expect(screen.getByText("Click an empty place on the canvas to put transform there.")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "place here" }));
  expect(at("transform")).toEqual({ x: 400 - 130, y: 300 - 32 }); // centred on the click
  expect(screen.queryByText(/Click an empty place/)).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "transform" }));
});

it("stops placing on Escape, leaving the step where it was", async () => {
  await withTwoSteps();
  const before = at("transform");
  await userEvent.click(screen.getByRole("button", { name: "transform" }));
  await userEvent.click(screen.getByRole("button", { name: "Place on the canvas…" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByText(/Click an empty place/)).toBeNull();
  expect(screen.queryByRole("button", { name: "place here" })).toBeNull();
  expect(at("transform")).toEqual(before);
});

it("moves a step 20 px a click from its panel", async () => {
  await withTwoSteps();
  const before = at("transform")!;
  await userEvent.click(screen.getByRole("button", { name: "transform" }));
  await userEvent.click(screen.getByRole("button", { name: "Move transform right" }));
  await userEvent.click(screen.getByRole("button", { name: "Move transform down" }));
  expect(at("transform")).toEqual({ x: before.x! + 20, y: before.y! + 20 });
});

it("keeps focus in the editor through undo and redo, never repairing it by hand (the owner's review of M3)", async () => {
  await withTwoSteps();
  const second = screen.getByRole("button", { name: "transform_2" });
  await vi.waitFor(() => expect(document.activeElement).toBe(second)); // the step just added has focus
  await userEvent.keyboard("{Control>}z{/Control}"); // its addition undone: its card is gone
  expect(screen.queryByRole("button", { name: "transform_2" })).toBeNull();
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "transform" })));
  await userEvent.keyboard("{Control>}z{/Control}"); // and the first: focus falls back to the start card
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Start" })));
  await userEvent.keyboard("{Control>}{Shift>}z{/Shift}{/Control}");
  await userEvent.keyboard("{Control>}{Shift>}z{/Shift}{/Control}"); // both redone, the keys still heard
  expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Start" })); // it survived: focus stays
});

it("closes a step's panel when undo removes its step, and gives focus to what remains", async () => {
  await withTwoSteps();
  await userEvent.click(screen.getByRole("button", { name: "transform_2" })); // its panel, its heading focused
  await userEvent.keyboard("{Control>}z{/Control}");
  expect(screen.queryByRole("complementary")).toBeNull();
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "transform" })));
});

it("leaves focus in a step's panel when undo keeps its step", async () => {
  await withTwoSteps();
  await userEvent.click(screen.getByRole("button", { name: "transform" })); // the first step's panel
  const heading = within(screen.getByRole("complementary", { name: "transform" })).getByRole("heading", { name: "transform" });
  await vi.waitFor(() => expect(document.activeElement).toBe(heading));
  await userEvent.keyboard("{Control>}z{/Control}"); // the second step's addition undone; transform stays
  expect(screen.getByRole("complementary", { name: "transform" })).toBeTruthy();
  expect(document.activeElement).toBe(heading);
});

const steps = () => screen.getByRole("group", { name: "Workflow steps" });

async function addTransform() {
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await screen.findByRole("button", { name: "transform" });
}

it("saves an edit with the revision it was loaded at, and says so", async () => {
  await show();
  await addTransform();
  expect(screen.getByText("Unsaved changes")).toBeTruthy();
  await vi.waitFor(() => expect(sent.find((r) => r.method === "PUT")).toBeTruthy(), { timeout: 3000 });
  const put = sent.find((r) => r.method === "PUT")!;
  expect(put.headers.get("If-Match")).toBe("1");
  expect((put.body as GraphDoc).nodes!.map((n) => n.key)).toEqual(["transform"]);
  await screen.findByText("Saved · not published");
});

it("opens on the server's draft, never a cached one", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 7, draft: draftWith("fresh") }));
  await show({ seed: (qc) => qc.setQueryData(["workflow", "t1", "w1"], { ...WORKFLOW, draft: draftWith("old") }) });
  expect(screen.getByRole("button", { name: "fresh" })).toBeTruthy();
  expect(drawn.some((d) => d.doc.nodes?.some((n) => n.key === "old"))).toBe(false);
});

it("keeps its own document when the workflow is read again while it's open", async () => {
  const { qc } = await show();
  await addTransform();
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 9, draft: draftWith("other") }));
  await qc.refetchQueries({ queryKey: ["workflow", "t1", "w1"] });
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "other" })).toBeNull();
});

it("saves before leaving through a link, then leaves", async () => {
  const { router } = await show();
  await addTransform();
  expect(screen.getByText("Unsaved changes")).toBeTruthy(); // inside the debounce
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  await screen.findByText("list");
  expect(sent.filter((r) => r.method === "PUT")).toHaveLength(1);
  expect(router.state.location.pathname).toBe("/t/t1/workflows");
});

it("asks before leaving work it couldn't save; staying keeps it", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  await show();
  await addTransform();
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  expect(within(ask).getByRole("button", { name: "Download my version" })).toBeTruthy();
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  const again = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  await userEvent.click(within(again).getByRole("button", { name: "Leave without saving" }));
  await screen.findByText("list");
});

it("turns read-only on a conflict, keeping the work downloadable and leaving guarded", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict", draft_revision: 5 }, 409));
  await show();
  await addTransform();
  const alert = await screen.findByRole("alert", {}, { timeout: 3000 });
  expect(alert.textContent).toContain("changed elsewhere");
  expect(screen.queryByRole("button", { name: /Add step/ })).toBeNull();
  expect(within(alert).getByRole("button", { name: "Download my version" })).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  expect(ask.textContent).toContain("changed elsewhere");
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
});

it("answers sign-out's question with the same decision: staying keeps the work", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  await show();
  await addTransform();
  const decision = mayLeave(); // what the shell's Sign out asks before it revokes anything
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
  await expect(decision).resolves.toBe(false);
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
});

it("asks once: a navigation after sign-out's \"leave\" goes without asking again", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  await show();
  await addTransform();
  const decision = mayLeave();
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  await userEvent.click(within(ask).getByRole("button", { name: "Leave without saving" }));
  await expect(decision).resolves.toBe(true);
  await userEvent.click(screen.getByRole("link", { name: "Workflows" })); // as sign-out's navigation to /login
  await screen.findByText("list");
  expect(screen.queryByRole("dialog", { name: "Your latest changes aren't saved" })).toBeNull();
});

it("lets overlapping exits share one question, and a Stay settles every one", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  await show();
  await addTransform();
  const first = mayLeave();
  const second = mayLeave(); // a second Sign out, or the router's blocker, while the first waits
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  expect(screen.getAllByRole("dialog", { name: "Your latest changes aren't saved" })).toHaveLength(1);
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
  await expect(first).resolves.toBe(false);
  await expect(second).resolves.toBe(false);
  expect(sent.filter((r) => r.method === "PUT")).toHaveLength(1); // one decision, one save tried
  expect(steps().dataset.editable).toBe("true"); // staying holds nothing
});

it("holds the document from an exit's consent until the exit is withdrawn", async () => {
  await show();
  await addTransform();
  await expect(mayLeave()).resolves.toBe(true); // saved first: sign-out may go on, and now awaits logout's answer
  await vi.waitFor(() => expect(steps().dataset.editable).toBe("false"));
  await userEvent.click(screen.getByRole("button", { name: "after transform" })); // an edit, under that consent
  expect(screen.queryByRole("dialog", { name: "Add a step" })).toBeNull();
  await userEvent.keyboard("{Control>}z{/Control}");
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy(); // undo is held too
  act(() => cancelLeaving()); // logout failed: still signed in
  await vi.waitFor(() => expect(steps().dataset.editable).toBe("true"));
  await userEvent.click(screen.getByRole("button", { name: "after transform" }));
  expect(await screen.findByRole("dialog", { name: "Add a step" })).toBeTruthy();
});

it("asks again after a sign-out that failed", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  await show();
  await addTransform();
  const decision = mayLeave();
  await userEvent.click(
    within(await screen.findByRole("dialog", { name: "Your latest changes aren't saved" })).getByRole("button", { name: "Leave without saving" }),
  );
  await expect(decision).resolves.toBe(true);
  act(() => cancelLeaving()); // what the shell does when signOut() fails
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  expect(await screen.findByRole("dialog", { name: "Your latest changes aren't saved" })).toBeTruthy();
  expect(screen.queryByText("list")).toBeNull();
});

it("stays open, with its edits, when the step types fail to refresh", async () => {
  const { qc } = await show();
  await addTransform();
  answers.set("GET /api/v1/node-types", () => json({ error: "http_error" }, 500));
  await act(() => qc.refetchQueries({ queryKey: ["node-types"] }));
  expect(await screen.findByText(/The step types couldn't be refreshed/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
  expect(screen.getByRole("group", { name: "Workflow steps" })).toBeTruthy();
});

it("asks before Reload discards the version a conflict kept", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict", draft_revision: 5 }, 409));
  await show();
  await addTransform();
  const alert = await screen.findByRole("alert", {}, { timeout: 3000 });
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 5, draft: draftWith("theirs") }));
  await userEvent.click(within(alert).getByRole("button", { name: "Reload" }));
  const ask = screen.getByRole("dialog", { name: "Reload the saved draft" });
  await userEvent.click(within(ask).getByRole("button", { name: "Discard my version and reload" }));
  expect(await screen.findByRole("button", { name: "theirs" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "transform" })).toBeNull();
});

const valid = (revision: number) => ({ draft_revision: revision, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] } });
const invalid = (revision: number, node: string | null) => ({
  draft_revision: revision, valid: false, expressions: [], taint: { sites: [], declassified: [] },
  diagnostics: [{ code: "config.invalid", message: "fields needs at least one entry", node, field: "/fields", fix: null, severity: "error" }],
});  // prettier-ignore
const checks = () => sent.filter((r) => r.path.endsWith("/validate")).length;

it("says it's checking before the first answer, never No problems", async () => {
  let answer: ((r: Response) => void) | undefined;
  answers.set(`POST ${BASE}/validate`, () => new Promise<Response>((r) => (answer = r)));
  await show();
  expect(screen.getByRole("button", { name: "Checking…" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "No problems" })).toBeNull();
  await vi.waitFor(() => expect(answer).toBeDefined());
  answer!(json(valid(1)));
  expect(await screen.findByRole("button", { name: "No problems" })).toBeTruthy();
});

it("checks the saved revision once a save settles, and counts its problems on the steps", async () => {
  answers.set(`POST ${BASE}/validate`, () => json(invalid(2, "x")));
  await show();
  await addTransform();
  expect(await screen.findByRole("button", { name: "Problems · 1" }, { timeout: 3000 })).toBeTruthy();
  expect(steps().dataset.problems).toBe("1");
});

it("calls an answer for an older revision stale, and never paints it on the steps", async () => {
  answers.set(`POST ${BASE}/validate`, () => json(invalid(1, "x"))); // even after the save made revision 2
  await show();
  await screen.findByRole("button", { name: "Problems · 1" }); // revision 1, on the screen: current
  expect(steps().dataset.problems).toBe("1");
  await addTransform();
  await screen.findByText("Saved · not published", {}, { timeout: 3000 });
  await vi.waitFor(() => expect(checks()).toBe(2));
  expect(screen.getByRole("button", { name: "Problems · 1, before your edits" })).toBeTruthy();
  expect(steps().dataset.problems).toBe("0");
});

it("says when a check failed, and checks again when asked", async () => {
  answers.set(`POST ${BASE}/validate`, () => json({ error: "http_error" }, 500));
  await show();
  await userEvent.click(await screen.findByRole("button", { name: "Check failed" }));
  answers.set(`POST ${BASE}/validate`, () => json(valid(1)));
  const panel = screen.getByRole("complementary", { name: "Problems" });
  await userEvent.click(within(panel).getByRole("button", { name: "Check again" }));
  expect(await screen.findByRole("button", { name: "No problems" })).toBeTruthy();
});

it("offers a viewer no checks", async () => {
  role = "viewer";
  await show();
  expect(screen.queryByRole("button", { name: /Problems|Check|Not checked/ })).toBeNull();
  expect(checks()).toBe(0);
});

it("finds a step whose id the draft spells otherwise by the server's canonical id (the owner's review of M3)", async () => {
  const UPPER = "0B6C2F1E-1D1E-4C1E-8E1E-1E1E1E1E1E0A";
  const draft = { graph_format: 1, nodes: [{ id: UPPER, key: "transform", type: "flow.transform@1", position: { x: 0, y: 140 } }], edges: [] };
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft }));
  answers.set(`POST ${BASE}/validate`, () => json(invalid(1, UPPER.toLowerCase())));
  await show();
  await screen.findByRole("button", { name: "Problems · 1" });
  expect(steps().dataset.problemSteps).toBe(UPPER.toLowerCase()); // keyed as the canvas looks it up (`idKey`)
  await userEvent.click(screen.getByRole("button", { name: "transform" })); // its panel lists the problem
  const panel = screen.getByRole("complementary", { name: "transform" });
  expect(panel.textContent).toContain("fields needs at least one entry");
  await userEvent.click(screen.getByRole("button", { name: "Problems · 1" }));
  expect(within(screen.getByRole("complementary", { name: "Problems" })).getByRole("button", { name: "Go to transform" })).toBeTruthy();
});
