// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
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
