// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Run } from "../../lib/runs";
import { item } from "../../test/runs";
import { RunPage } from "./RunPage";

const RUN: Run = {
  ...item("4a2b17e0-3b2d-4e5f-9a1b-2c3d4e5f6a7b", "2026-10-16T09:41:12Z", { status: "failed", ended_at: "2026-10-16T09:41:50Z" }),
  draft_revision: null, outcomes_recorded: true, parent: null, csv: null,
};  // prettier-ignore

let answers: Map<string, () => Response>;

beforeEach(() => {
  answers = new Map();
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    const answer = answers.get(path);
    return Promise.resolve(answer ? answer() : new Response(JSON.stringify({ error: "not_found" }), { status: 404 }));
  });
});

const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status });

function show(runId = RUN.id) {
  const root = createRootRoute({ component: () => <RunPage tenantId="t1" runId={runId} /> });
  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs", component: () => <p>the Runs page</p> });
  const router = createRouter({ routeTree: root.addChildren([runs]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

it("names the run by its workflow and its short id, with the way back to Runs (§5.3)", async () => {
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
  const router = show();
  expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
  expect(screen.getByText("run 4a2b17e0")).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "← Runs" }));
  expect(router.state.location.pathname).toBe("/t/t1/runs");
});

it("says a run that isn't kept any more, or never was, is neither, with Back to Runs (§5.4; the RunOther board)", async () => {
  const router = show("0d4f9b2a-0000-4000-8000-000000000000");
  expect(await screen.findByRole("heading", { level: 1, name: "Run 0d4f9b2a" })).toBeTruthy();
  expect(screen.getByText("This run isn't kept any more, or it never existed here.")).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "Back to Runs" }));
  expect(router.state.location.pathname).toBe("/t/t1/runs");
});

it("says a run can't be read while its tenant is erased (§5.5)", async () => {
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json({ error: "key_unusable" }, 503));
  show();
  expect((await screen.findByRole("alert")).textContent).toBe("This run can't be read while the tenant is being erased.");
});

it("says the run couldn't be read, and reads it again when asked", async () => {
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json({ error: "internal_error" }, 500));
  show();
  expect((await screen.findByRole("alert")).textContent).toBe("The run couldn't be read.");
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
});
