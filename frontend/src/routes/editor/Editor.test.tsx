// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
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
          data-editable={String(props.editable)}
          data-problems={String(props.problems.size)}
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
  screen.getByRole("button", { name: "transform" }).focus();
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
