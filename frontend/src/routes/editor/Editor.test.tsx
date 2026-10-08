// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { onAnnounce } from "../../lib/announce";
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
              <button data-item={`port:${n.id}:out`} onClick={() => props.onItem({ kind: "after", from: { node: n.id, port: "out" } })}>after {n.key}</button>
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
let downloads: string[];

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
  answers.set(`GET ${BASE}/versions`, () => json([]));
  answers.set(`POST ${BASE}/publish`, () => json({ version_id: "v1", number: 1, warnings: [] }, 201));
  downloads = [];
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push(this.download);
  });
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
async function show({ seed, at = "/t/t1/workflows/w1" }: { seed?: (qc: QueryClient) => void; at?: string } = {}) {
  const root = createRootRoute({ component: Outlet });
  const list = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows", component: () => <p>list</p> });
  const editor = createRoute({
    getParentRoute: () => root,
    path: "/t/$tenantId/workflows/$workflowId",
    component: () => <EditorPage tenantId="t1" workflowId="w1" />,
  });
  // A page whose loading sends the person straight back to the editor: an exit that never completes.
  const away = createRoute({
    getParentRoute: () => root,
    path: "/away",
    beforeLoad: () => {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router's redirect is thrown, by design
      throw redirect({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId: "t1", workflowId: "w1" } });
    },
  });
  const router = createRouter({
    routeTree: root.addChildren([list, editor, away]),
    history: createMemoryHistory({ initialEntries: [at] }),
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

it("lays the toolbar out as 1c: the state beside the name, Add step first among the actions, Publish last", async () => {
  await show();
  await screen.findByRole("button", { name: "Publish v1" });
  const follows = (a: Node, b: Node) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
  const name = screen.getByRole("heading", { level: 1, name: "Nightly" });
  const state = screen.getByText(/^Saved/);
  const buttons = [...name.parentElement!.querySelectorAll("button")];
  expect(follows(name, state) && follows(state, buttons[0]!)).toBe(true);
  expect(buttons[0]!.textContent).toMatch(/Add step/);
  expect(buttons.at(-1)!.textContent).toBe("Publish v1");
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

it("offers each of a step's + in its panel, at full size, opening the picker as the + does (WCAG 2.5.8)", async () => {
  await withTwoSteps();
  await userEvent.click(screen.getByRole("button", { name: "transform" }));
  const adds = () => within(screen.getByRole("complementary", { name: "transform" })).getByRole("group", { name: "Add a step" });
  expect(within(adds()).getAllByRole("button").map((b) => b.textContent)).toEqual([
    "Insert a step before transform",
    "Insert a step between transform and transform_2",
  ]);
  await userEvent.click(within(adds()).getByRole("button", { name: "Insert a step between transform and transform_2" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  const doc = drawn.at(-1)!.doc;
  const keyOf = (id: string) => doc.nodes!.find((n) => n.id === id)!.key;
  expect(doc.edges!.map((e) => `${keyOf(e.from.node)}->${keyOf(e.to.node)}`).sort()).toEqual(["transform->transform_3", "transform_3->transform_2"]);
  await userEvent.click(screen.getByRole("button", { name: "transform_2" }));
  expect(within(screen.getByRole("complementary", { name: "transform_2" })).getByRole("group", { name: "Add a step" }).textContent).toBe("Add a step after transform_2");
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

/** A version as the list answers it; `hash` is its graph's, which says which draft it holds. */
const version = (number: number, active: boolean, hash = "h") => ({
  id: `v${number}`, number, published_at: "2026-10-06T10:00:00Z", published_by: null, graph_hash: hash, version_hash: "h",
  cel_profile: "p", engine_abi: 6, node_refs: [], active, executable: true, blocked_by: [],
});  // prettier-ignore
const detail = (number: number, key: string) => ({ ...version(number, false), graph: draftWith(key), expressions: [] });
const publishes = () => sent.filter((r) => r.path.endsWith("/publish"));

async function confirmPublish(number: number) {
  await userEvent.click(await screen.findByRole("button", { name: `Publish v${number}` }));
  const ask = screen.getByRole("dialog", { name: `Publish version ${number}` });
  await userEvent.click(within(ask).getByRole("button", { name: "Publish" }));
  return ask;
}

it("publishes after saving, naming the version it confirms", async () => {
  await show();
  await addTransform();
  await confirmPublish(1);
  await screen.findByText("Saved · published as v1", {}, { timeout: 3000 });
  const put = sent.findIndex((r) => r.method === "PUT");
  const publish = sent.findIndex((r) => r.path.endsWith("/publish"));
  expect(put).toBeGreaterThanOrEqual(0);
  expect(publish).toBeGreaterThan(put); // flushed first
  expect(sent[publish]!.headers.get("If-Match")).toBe("2");
  expect(sent[publish]!.body).toEqual({ expected_latest_version: 0 });
});

it("names no number until the versions are read, and says when they can't be", async () => {
  let list: ((r: Response) => void) | undefined;
  answers.set(`GET ${BASE}/versions`, () => new Promise<Response>((r) => (list = r)));
  await show();
  expect(screen.getByRole("button", { name: "Publish" }).hasAttribute("disabled")).toBe(true);
  await vi.waitFor(() => expect(list).toBeDefined());
  list!(json({ error: "http_error" }, 500));
  expect(await screen.findByText("The versions couldn't be read, so publishing waits.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Publish" }).hasAttribute("disabled")).toBe(true);
  answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
  await userEvent.click(screen.getByRole("button", { name: "Read them again" }));
  expect(await screen.findByRole("button", { name: "Publish v2" })).toBeTruthy();
});

it("asks again, with the new number, when another version was published meanwhile", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
    answers.set(`POST ${BASE}/publish`, () => json({ version_id: "v2", number: 2, warnings: [] }, 201));
    return json({ error: "version_changed", latest_version: 1 }, 409);
  });
  await show();
  await confirmPublish(1);
  const again = await screen.findByRole("dialog", { name: "Publish version 2" });
  expect(again.textContent).toContain("Version 1 was published since you opened this");
  await vi.waitFor(() => expect(document.activeElement).toBe(within(again).getByRole("button", { name: "Cancel" })));
  expect(screen.queryByText(/changed elsewhere/)).toBeNull(); // never a draft conflict
  await userEvent.click(within(again).getByRole("button", { name: "Publish" }));
  await vi.waitFor(() => expect(publishes()).toHaveLength(2));
  expect(publishes()[1]!.body).toEqual({ expected_latest_version: 1 });
});

it("keeps the draft still while it's being published", async () => {
  let done: ((r: Response) => void) | undefined;
  answers.set(`POST ${BASE}/publish`, () => new Promise<Response>((r) => (done = r)));
  await show();
  await confirmPublish(1);
  await vi.waitFor(() => expect(done).toBeDefined());
  expect(steps().dataset.editable).toBe("false");
  done!(json({ version_id: "v1", number: 1, warnings: [] }, 201));
  await vi.waitFor(() => expect(steps().dataset.editable).toBe("true"));
});

it("reads what happened when a publish's answer is lost: the version holds the submitted graph, never who made it", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(1, true, "h1")])); // "h1": the draft as loaded
    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, active_version_id: "v1", active_version_number: 1, unpublished_changes: false }));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await confirmPublish(1);
  await vi.waitFor(() => expect(screen.getByRole("status", { name: "Notice" }).textContent).toContain("Version 1 holds the submitted graph. Your publish request's outcome wasn't received."));
  expect(screen.getByText("Saved · published as v1")).toBeTruthy();
  expect(screen.queryByText(/wasn't published|Not published/)).toBeNull();
});

it("never takes another's publication for this draft's when an answer is lost", async () => {
  // Someone published version 1 from an earlier draft; this editor saved revision 2 ("h2"); its publish was refused,
  // and the refusal lost. Version 1 exists and the draft is still at revision 2: neither says this draft is in it.
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(1, true, "h-theirs")]));
    answers.set(`GET ${BASE}`, () =>
      json({ ...WORKFLOW, draft_revision: 2, active_version_id: "v1", active_version_number: 1, unpublished_changes: true }));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await addTransform();
  await confirmPublish(1);
  expect((await screen.findByRole("alert")).textContent).toContain("Version 1 holds another draft: yours wasn't published");
  expect(screen.getByText("Saved · unpublished changes since v1")).toBeTruthy();
  expect(screen.queryByText(/published as v1|holds the submitted graph/)).toBeNull();
});

it("takes the active version from the read, never from the number it hoped for", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(2, true, "h-later"), version(1, false, "h1")]));
    answers.set(`GET ${BASE}`, () =>
      json({ ...WORKFLOW, active_version_id: "v2", active_version_number: 2, unpublished_changes: true }));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await confirmPublish(1);
  await vi.waitFor(() => expect(screen.getByRole("status", { name: "Notice" }).textContent).toContain("Version 1 holds the submitted graph. Your publish request's outcome wasn't received."));
  expect(screen.getByText("Saved · unpublished changes since v2")).toBeTruthy(); // version 2 came after, and is active
});

it("says it isn't known when the draft submitted has no hash to compare", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_graph_hash: null }));
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(1, true, "h-any")]));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await confirmPublish(1);
  expect((await screen.findByRole("alert")).textContent).toContain("it isn't known whether it holds your draft");
  expect(screen.queryByText(/holds another draft|holds the submitted graph/)).toBeNull();
});

it("never calls a lost publish a failure when what happened can't be read", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json({ error: "http_error" }, 502));
    answers.set(`GET ${BASE}`, () => json({ error: "http_error" }, 502));
    return json({ error: "http_error" }, 504);
  });
  await show();
  await confirmPublish(1);
  expect((await screen.findByRole("alert")).textContent).toContain("It isn't known whether version 1 was published");
  expect(screen.getByText("Saved · the active version isn't known")).toBeTruthy();
});

it("keeps what the workflow's read says when only the versions' read fails", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json({ error: "http_error" }, 502));
    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, active_version_id: "v3", active_version_number: 3, unpublished_changes: true }));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await confirmPublish(1);
  expect((await screen.findByRole("alert")).textContent).toContain("It isn't known whether version 1 was published");
  expect(screen.getByText("Saved · unpublished changes since v3")).toBeTruthy(); // the active version, as read
});

it("keeps an activation made when the read after it fails", async () => {
  answers.set(`GET ${BASE}/versions`, () => json([version(2, true), version(1, false)]));
  answers.set(`POST ${BASE}/activate`, () => {
    answers.set(`GET ${BASE}`, () => json({ error: "http_error" }, 500));
    return json({ active_version_id: "v1", number: 1, warnings: [] });
  });
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "Make version 1 active" }));
  await userEvent.click(within(screen.getByRole("dialog", { name: "Make version 1 active" })).getByRole("button", { name: "Make active" }));
  await vi.waitFor(() => expect(screen.getByRole("status", { name: "Notice" }).textContent).toContain("Version 1 is active."));
  expect(screen.getByText("Saved · v1 is active")).toBeTruthy(); // the comparison isn't known: nothing claimed
  expect(screen.queryByText(/wasn't made active/)).toBeNull();
});

it("shows the newest version asked for, whatever order the answers come in", async () => {
  let first: ((r: Response) => void) | undefined;
  answers.set(`GET ${BASE}/versions`, () => json([version(2, true), version(1, false)]));
  answers.set(`GET ${BASE}/versions/v1`, () => new Promise<Response>((r) => (first = r)));
  answers.set(`GET ${BASE}/versions/v2`, () => json(detail(2, "two")));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await userEvent.click(screen.getByRole("button", { name: "View version 2" }));
  expect(await screen.findByRole("button", { name: "two" })).toBeTruthy();
  first!(json(detail(1, "one")));
  await new Promise((r) => setTimeout(r, 20)); // the late answer has landed
  expect(screen.queryByRole("button", { name: "one" })).toBeNull();
  expect(screen.getByText("Viewing version 2, read only. The draft is unchanged.")).toBeTruthy();
});

it("carries no draft diagnostics onto a version's canvas", async () => {
  answers.set(`POST ${BASE}/validate`, () => json(invalid(1, "x")));
  answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
  answers.set(`GET ${BASE}/versions/v1`, () => json(detail(1, "one")));
  await show();
  await screen.findByRole("button", { name: "Problems · 1" });
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await screen.findByRole("button", { name: "one" });
  expect(steps().dataset.problems).toBe("0");
  expect(screen.queryByRole("button", { name: /Problems/ })).toBeNull();
});

it("shows a version's own step in the step panel, never the draft's", async () => {
  const theirs = draftWith("one");
  theirs.nodes![0]!.options = { timeout_s: 30 }; // the draft's "one" keeps the type's 60 s
  const expressions = [{ node: "id-one", field: "/fields/a", mode: "activity", reason: "builds a message" }];
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("one") }));
  answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
  answers.set(`GET ${BASE}/versions/v1`, () => json({ ...version(1, true), graph: theirs, expressions }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await screen.findByText("Viewing version 1, read only. The draft is unchanged.");
  await userEvent.click(screen.getByRole("button", { name: "one" }));
  const panel = screen.getByRole("complementary", { name: "one" });
  expect(panel.textContent).toContain("30 s");
  expect(panel.textContent).toContain("Runs as a separate step: builds a message");
  expect(panel.textContent).toContain("Not checked for what's on the screen.");
});

it("stops an export when the latest edits aren't saved, and offers the saved draft by name", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  answers.set(`GET ${BASE}/export`, () => json({ format: "dewpoint.workflow", format_version: 1, name: "Nightly", graph: {}, bindings: [] }));
  await show();
  await addTransform();
  await userEvent.click(screen.getByRole("button", { name: "Export" }));
  const stop = await screen.findByRole("alert");
  expect(stop.textContent).toContain("Not exported: your latest edits aren't saved");
  expect(sent.some((r) => r.path.endsWith("/export"))).toBe(false);
  await userEvent.click(within(stop).getByRole("button", { name: "Export the last saved draft" }));
  await vi.waitFor(() => expect(downloads).toEqual(["nightly.dewpoint.json"]));
});

it("offers a draft that can't be made portable as it is, labelled", async () => {
  answers.set(`GET ${BASE}/export`, () =>
    json({ error: "not_portable", problems: [{ reason: "unknown_type", binding: null, node: "id-odd", field: null }] }, 422));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("odd") }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Export" }));
  const stop = await screen.findByRole("alert");
  expect(stop.textContent).toContain("can't be exported as a portable file");
  expect(stop.textContent).toContain("odd");
  await userEvent.click(within(stop).getByRole("button", { name: "Download this draft as it is (not portable)" }));
  expect(downloads).toEqual(["nightly.draft.json"]);
});

it("shows what only publish checks, in the problems panel, marked", async () => {
  answers.set(`POST ${BASE}/publish`, () =>
    json({ error: "invalid", diagnostics: [{ code: "connection.unknown", message: "That connection doesn't exist.", node: null, field: null, fix: null, severity: "error" }] }, 422));
  await show();
  await confirmPublish(1);
  const panel = await screen.findByRole("complementary", { name: "Problems" });
  expect(within(panel).getByRole("region", { name: "Found at publish" }).textContent).toContain("That connection doesn't exist.");
});

// Editing that stops while an action is open stops the action too (the owner's review of 6d7766e, correction 1): its
// dialog closes, nothing it would have added lands, and focus goes back to the canvas.
describe("a conflict that arrives while an action is open", () => {
  it.each([
    { action: "the step picker", key: "a", dialog: "Add a step" },
    { action: "the connect dialog", key: "c", dialog: "Connect transform_2 to" },
    { action: "the delete question", key: "{Delete}", dialog: "Delete a step" },
  ])("closes $action, changes nothing and gives focus back to the step", async ({ key, dialog }) => {
    await withTwoSteps();
    let release: ((r: Response) => void) | undefined;
    answers.set(`PUT ${BASE}/draft`, () => new Promise<Response>((r) => (release = r)));
    screen.getByRole("button", { name: "transform_2" }).focus();
    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}"); // an edit, whose save the server holds
    await vi.waitFor(() => expect(release).toBeDefined(), { timeout: 3000 });
    screen.getByRole("button", { name: "transform_2" }).focus();
    await userEvent.keyboard(key);
    const open = screen.getByRole("dialog", { name: dialog });
    const keys = () => drawn.at(-1)!.doc.nodes!.map((n) => n.key);
    const before = keys();
    release!(json({ error: "draft_conflict", draft_revision: 5 }, 409));
    await screen.findByRole("alert");
    await vi.waitFor(() => expect(open.isConnected && open.hasAttribute("open")).toBe(false));
    expect(steps().dataset.editable).toBe("false");
    expect(keys()).toEqual(before);
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "transform_2" })));
  });
});

// Exits that share one decision each keep their own consent (the owner's review of 315e19f): a router exit sent back
// here releases only its own; a sign-out that joined keeps the document held until it fails or the editor goes.
describe("a sign-out and a router exit sharing one decision", () => {
  const saved = () => json({ draft_revision: 2, unpublished_changes: true, graph_hash: "h2", active_version_id: null, active_version_number: null });
  async function overlapping(order: "router first" | "sign-out first", answer: () => Response) {
    let release: ((r: Response) => void) | undefined;
    answers.set(`PUT ${BASE}/draft`, () => new Promise<Response>((r) => (release = r)));
    const { router } = await show();
    await addTransform();
    let signOut!: Promise<boolean>;
    if (order === "router first") {
      act(() => router.history.push("/away")); // waits for the save, then is sent back here
      signOut = mayLeave();
    } else {
      signOut = mayLeave();
      act(() => router.history.push("/away"));
    }
    await vi.waitFor(() => expect(release).toBeDefined(), { timeout: 3000 });
    release!(answer());
    return { router, signOut };
  }

  it.each(["router first", "sign-out first"] as const)("keeps sign-out's hold when the router exit comes back (%s)", async (order) => {
    const { router, signOut } = await overlapping(order, saved);
    expect(await signOut).toBe(true);
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w1"));
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(steps().dataset.editable).toBe("false"); // the sign-out may still be logging out: no edit may land
    // The navigation that follows the logout asks nothing again.
    act(() => router.history.push("/t/t1/workflows"));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows"));
    expect(screen.queryByRole("dialog", { name: "Your latest changes aren't saved" })).toBeNull();
  });

  it.each(["router first", "sign-out first"] as const)("gives the document back when that sign-out fails (%s)", async (order) => {
    const { router, signOut } = await overlapping(order, saved);
    expect(await signOut).toBe(true);
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w1"));
    act(() => cancelLeaving());
    await vi.waitFor(() => expect(steps().dataset.editable).toBe("true"));
  });

  it("asks its one question once, for both, and the router's return still leaves sign-out's hold", async () => {
    const { router, signOut } = await overlapping("router first", () => json({ error: "http_error" }, 500));
    const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
    await userEvent.click(within(ask).getByRole("button", { name: "Leave without saving" }));
    expect(await signOut).toBe(true);
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w1"));
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(steps().dataset.editable).toBe("false");
    expect(screen.queryByRole("dialog", { name: "Your latest changes aren't saved" })).toBeNull();
  });
});

// When editing stops, focus held by a control only editing draws goes somewhere drawn (the final checkpoint's second
// review): never to the page.
describe("focus when editing stops under it", () => {
  function heldEdit() {
    let release: ((r: Response) => void) | undefined;
    answers.set(`PUT ${BASE}/draft`, () => new Promise<Response>((r) => (release = r)));
    return {
      held: () => vi.waitFor(() => expect(release).toBeDefined(), { timeout: 3000 }),
      conflict: async () => {
        release!(json({ error: "draft_conflict", draft_revision: 5 }, 409));
        await screen.findByRole("alert");
      },
    };
  }

  it("goes to the panel's heading from a panel button that's gone", async () => {
    await withTwoSteps();
    const save = heldEdit();
    await userEvent.click(screen.getByRole("button", { name: "transform_2" }));
    const panel = screen.getByRole("complementary", { name: "transform_2" });
    await userEvent.click(within(panel).getByRole("button", { name: "Move transform_2 down" })); // focus stays on it
    await save.held();
    await save.conflict();
    await vi.waitFor(() => expect(document.activeElement).toBe(within(panel).getByRole("heading", { name: "transform_2" })));
  });

  it("stops placing a step, and says so", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    await withTwoSteps();
    const save = heldEdit();
    await userEvent.click(screen.getByRole("button", { name: "transform_2" }));
    const panel = screen.getByRole("complementary", { name: "transform_2" });
    await userEvent.click(within(panel).getByRole("button", { name: "Move transform_2 down" }));
    await save.held();
    await userEvent.click(within(panel).getByRole("button", { name: "Place on the canvas…" }));
    await save.conflict();
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: "place here" })).toBeNull());
    expect(said).toContain("Not placed: the draft can't be changed now");
    stop();
  });

  it("goes back to the step from a + whose picker a conflict closed, not to the start card", async () => {
    await withTwoSteps();
    const save = heldEdit();
    screen.getByRole("button", { name: "transform_2" }).focus();
    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
    await save.held();
    screen.getByRole("button", { name: "after transform_2" }).focus(); // the free port's "+"
    await userEvent.keyboard("a");
    expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
    await save.conflict();
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "transform_2" })));
  });
});

// Only leaving the editor is an exit (the owner's review of 6d7766e, correction 2): a navigation that keeps it asks
// nothing and holds nothing, and an exit that never completes gives the document back.
describe("navigations that keep the editor", () => {
  it.each([
    { what: "a hash", to: { hash: "notes" } },
    { what: "a query", to: { search: { panel: "versions" } } },
  ])("leave it editable when only $what changes", async ({ to }) => {
    const { router } = await show();
    await addTransform();
    await act(() => router.navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId: "t1", workflowId: "w1" }, ...to }));
    expect(router.state.location.pathname).toBe("/t/t1/workflows/w1");
    expect(steps().dataset.editable).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: "after transform" }));
    await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
    expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
  });

  it("keeps it when the same workflow is reached by another spelling of its path", async () => {
    // Opened as /…/w1/ (a bookmark), then picked in the palette as /…/w1: the same route and step, not an exit.
    const { router } = await show({ at: "/t/t1/workflows/w1/" });
    await addTransform();
    act(() => router.history.push("/t/t1/workflows/w1"));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w1"));
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(steps().dataset.editable).toBe("true");
  });

  it("gives the document back when an exit doesn't complete", async () => {
    const { router } = await show();
    await addTransform();
    act(() => router.history.push("/away")); // through the blocker: agreed to, then sent back here
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w1"));
    await vi.waitFor(() => expect(steps().dataset.editable).toBe("true"));
    await userEvent.click(screen.getByRole("button", { name: "after transform" }));
    await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
    expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
  });
});

// What changes without a key being pressed is said (WCAG 4.1.3): a save that failed, and a notice, through a live
// region that's there before its text (one inserted already holding it often goes unsaid).
describe("status messages", () => {
  it("says when the latest edits aren't saved", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
    await show();
    await addTransform();
    await screen.findByText("Not saved", {}, { timeout: 3000 });
    expect(said).toContain("Your latest edits aren't saved. Retry is in the toolbar.");
    stop();
  });

  it("keeps the notices' live region in place before any notice", async () => {
    await show();
    expect(screen.getByRole("status", { name: "Notice" }).textContent).toBe("");
  });
});

// Where focus goes when what held it leaves (the final checkpoint's review, WCAG 2.4.3): never to the page. The test
// setup's dialog returns no focus, as a native one can't when its opener is gone or disabled: the editor places it.
describe("focus, when what held it goes", () => {
  it("returns to the toolbar's button when the problems panel closes", async () => {
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "No problems" }));
    await userEvent.click(within(screen.getByRole("complementary", { name: "Problems" })).getByRole("button", { name: "Close" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "No problems" })));
  });

  it("returns to the toolbar's button when Escape closes the versions panel", async () => {
    await show();
    await userEvent.click(screen.getByRole("button", { name: "Versions" }));
    await screen.findByRole("complementary", { name: "Versions" });
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Versions" })));
  });

  it("lands on the versions panel's heading once a version is made active", async () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(2, true), version(1, false)]));
    answers.set(`POST ${BASE}/activate`, () => json({ active_version_id: "v1", number: 1, warnings: [] }));
    await show();
    await userEvent.click(screen.getByRole("button", { name: "Versions" }));
    await userEvent.click(await screen.findByRole("button", { name: "Make version 1 active" }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "Make version 1 active" })).getByRole("button", { name: "Make active" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "Versions" })));
  });

  it("returns to Publish, naming the next version, once a publish is done", async () => {
    answers.set(`POST ${BASE}/publish`, () => {
      answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
      return json({ version_id: "v1", number: 1, warnings: [] }, 201);
    });
    await show();
    await confirmPublish(1);
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Publish v2" })));
  });

  it("lands on the problems panel's heading when a publish is refused for its problems", async () => {
    answers.set(`POST ${BASE}/publish`, () =>
      json({ error: "invalid", diagnostics: [{ code: "connection.unknown", message: "That connection doesn't exist.", node: null, field: null, fix: null, severity: "error" }] }, 422));
    await show();
    await confirmPublish(1);
    await screen.findByRole("complementary", { name: "Problems" });
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "Problems" })));
  });
});

it("keeps an older draft's publish findings out of the current problems", async () => {
  // The owner's case: a clean check of revision 2 must not show revision 1's publish errors as current.
  answers.set(`POST ${BASE}/publish`, () =>
    json({ error: "invalid", diagnostics: [{ code: "connection.unknown", message: "That connection doesn't exist.", node: "x", field: null, fix: null, severity: "error" }] }, 422));
  await show();
  await confirmPublish(1);
  expect(await screen.findByRole("button", { name: "Problems · 1" })).toBeTruthy(); // current: revision 1, no edits
  expect(steps().dataset.problems).toBe("1");
  answers.set(`POST ${BASE}/validate`, () => json(valid(2)));
  await addTransform();
  expect(screen.getByRole("button", { name: "Not checked since your edits" })).toBeTruthy(); // pending: revision 1 still
  expect(steps().dataset.problems).toBe("0");
  expect(await screen.findByRole("button", { name: "No problems" }, { timeout: 3000 })).toBeTruthy();
  const panel = screen.getByRole("complementary", { name: "Problems" });
  expect(within(panel).getByRole("region", { name: "Found at publish" }).textContent).toContain("before your latest edits");
});

it("offers no Publish to a viewer", async () => {
  role = "viewer";
  await show();
  expect(screen.queryByRole("button", { name: /^Publish/ })).toBeNull();
});

/** a → b, c; b → d, e; c → d, f (the owner's review of revision 2): d is joined from b and from c. */
function joins(): GraphDoc {
  const at = { a: [0, 0], b: [0, 140], c: [300, 140], d: [0, 280], e: [300, 280], f: [600, 280] } as const;
  const keys = Object.keys(at) as (keyof typeof at)[];
  const link = (from: string, to: string) => ({ from: { node: `id-${from}`, port: "out" }, to: { node: `id-${to}` } });
  return {
    graph_format: 1,
    nodes: keys.map((key) => ({ id: `id-${key}`, key, type: "flow.transform@1", position: { x: at[key][0], y: at[key][1] } })),
    edges: [link("a", "b"), link("a", "c"), link("b", "d"), link("b", "e"), link("c", "d"), link("c", "f")],
  };
}

it.each(["a viewer", "an editor after a conflict", "a viewed version"])(
  "keeps to the branch the keys came by at a join, read only for %s",
  async (who) => {
    if (who === "a viewer") role = "viewer";
    if (who === "a viewed version") {
      answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
      answers.set(`GET ${BASE}/versions/v1`, () => json({ ...version(1, true), graph: joins(), expressions: [] }));
    } else {
      answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: joins() }));
    }
    if (who === "an editor after a conflict") answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict", draft_revision: 5 }, 409));
    await show();
    if (who === "an editor after a conflict") {
      await userEvent.click(screen.getByRole("button", { name: "after f" }));
      await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
      await screen.findByRole("alert", {}, { timeout: 3000 }); // changed elsewhere: read only now
    }
    if (who === "a viewed version") {
      await userEvent.click(screen.getByRole("button", { name: "Versions" }));
      await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
      await screen.findByRole("button", { name: "c" });
    }
    expect(steps().dataset.editable).toBe("false");
    screen.getByRole("button", { name: "c" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "d" }));
    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "f" })); // never b's e
    await userEvent.keyboard("{ArrowLeft}{ArrowUp}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "c" }));
  },
);
