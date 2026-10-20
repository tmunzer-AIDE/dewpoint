// SPDX-License-Identifier: Apache-2.0
import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, useParams } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { useLand, useLanded } from "./landing";
import { RUN_TITLE } from "./useCancel";

function Starter() {
  const land = useLand("t1");
  return <button onClick={() => land("r1")}>Start</button>;
}
function Page() {
  const runId = useParams({ strict: false }).runId ?? "";
  useLanded(runId, true);
  return <h1 id={RUN_TITLE} tabIndex={-1}>{`Run ${runId}`}</h1>;
}

function show() {
  const root = createRootRoute({ component: Outlet });
  const home = createRoute({ getParentRoute: () => root, path: "/", component: Starter });
  const run = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs/$runId", component: Page });
  const router = createRouter({ routeTree: root.addChildren([home, run]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(<RouterProvider router={router} />);
  return router;
}

describe("landing on a run just started (the run form design §5.2)", () => {
  it("opens the run's page, its heading focused, once", async () => {
    const router = show();
    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    const heading = await screen.findByRole("heading", { name: "Run r1" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(router.state.location.pathname).toBe("/t/t1/runs/r1");
    heading.blur();
    await router.navigate({ to: "/" });
    await router.navigate({ to: "/t/$tenantId/runs/$runId", params: { tenantId: "t1", runId: "r1" } });
    await screen.findByRole("heading", { name: "Run r1" });
    expect(document.activeElement).toBe(document.body); // opened another way: the browser's focus, as any page
  });
});
