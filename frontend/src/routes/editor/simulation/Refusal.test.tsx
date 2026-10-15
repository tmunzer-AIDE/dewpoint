// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/client";
import type { GraphDoc } from "../../../lib/workflows";
import { Refusal } from "./Refusal";

const node = (key: string, type: string) => ({ id: `id-${key}`, key, type, config: {} });
const DOC = { graph_format: 1, nodes: [node("get_site", "mist.legacy.sites@1"), node("notify", "slack.post@1"), node("has_aps", "flow.if@1")], edges: [] } as unknown as GraphDoc;
const diagnostic = (node: string | null, message: string, code = "ref.unknown", severity: "error" | "warning" = "error") => ({ code, message, node, field: null, fix: null, severity });

function show(status: number, body: Record<string, unknown>) {
  const handlers = { onGoTo: vi.fn(), onShowProblems: vi.fn(), onTryAgain: vi.fn() };
  render(<Refusal error={new ApiError(status, body.error as string, body)} doc={DOC} {...handlers} />);
  return handlers;
}

describe("a refused simulation, in the server's words (§7.7; the Refusals board)", () => {
  it("asks for a draft's problems to be fixed first, each with Go to, and shows them", async () => {
    const h = show(422, { error: "invalid", diagnostics: [
      diagnostic("id-notify", "A reference to get_sit, which isn't a step."),
      diagnostic("id-has_aps", "The condition reads sensitive data that isn't declassified.", "taint.undeclassified"),
      diagnostic(null, "Nothing follows the loop.", "graph.unused", "warning"),
    ] });  // prettier-ignore
    expect(screen.getByText("Not simulated")).toBeTruthy();
    expect(screen.getByText("Fix 2 problems first: a draft with problems isn't simulated.")).toBeTruthy();
    const items = within(screen.getByRole("list", { name: "Problems" })).getAllByRole("listitem");
    expect(items).toHaveLength(2); // its errors; a warning never refuses
    expect(within(items[0]!).getByText("A reference to get_sit, which isn't a step.")).toBeTruthy();
    await userEvent.click(within(items[0]!).getByRole("button", { name: "Go to notify" }));
    expect(h.onGoTo).toHaveBeenCalledWith("id-notify");
    await userEvent.click(screen.getByRole("button", { name: "Show the problems" }));
    expect(h.onShowProblems).toHaveBeenCalled();
  });

  it("says one problem in the singular", () => {
    show(422, { error: "invalid", diagnostics: [diagnostic("id-notify", "A reference to get_sit, which isn't a step.")] });
    expect(screen.getByText("Fix 1 problem first: a draft with problems isn't simulated.")).toBeTruthy();
  });

  it("says a declassifying draft needs the permission, in the server's words alone", () => {
    const words = "Simulating a draft that declassifies sensitive data needs the workflow.declassify permission (tenant admins and owners).";
    show(422, { error: "invalid", diagnostics: [diagnostic(null, words, "declassify.forbidden")] });
    expect(screen.getByText(words)).toBeTruthy();
    expect(screen.queryByText(/^Fix /)).toBeNull();
    expect(screen.queryByRole("button", { name: "Show the problems" })).toBeNull();
  });

  it("says why the deployment refused it", () => {
    const words = "Production runs are off in this deployment: no run starts in a production deployment until its gate lifts (engine 2b spec §2).";
    show(503, { error: "production_runs_disabled", messages: [words] });
    expect(screen.getByText(words)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("goes to each step of a retired type", async () => {
    const h = show(409, { error: "node_type_retired", messages: ["mist.legacy.sites@1 has been retired."] });
    expect(screen.getByText("mist.legacy.sites@1 has been retired.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Go to get_site" }));
    expect(h.onGoTo).toHaveBeenCalledWith("id-get_site");
  });

  it("tries again when no current build was recorded", async () => {
    const h = show(503, { error: "no_current_build", messages: ["No current build has been recorded lately, so this run's engine ABI can't be checked: the dispatcher records it while it runs."] });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(h.onTryAgain).toHaveBeenCalled();
  });

  it("lists a step test's refused values by their pointer", () => {
    show(422, { error: "seed_missing", problems: [{ code: "seed_missing", pointer: "/steps/get_site/output/name", message: "A value is required here." }] });
    expect(screen.getByText("/steps/get_site/output/name: A value is required here.")).toBeTruthy();
  });

  it("says when the draft was changed elsewhere", () => {
    show(409, { error: "draft_conflict", draft_revision: 17 });
    expect(screen.getByText("The draft was changed elsewhere, so it wasn't simulated.")).toBeTruthy();
  });

  it("names a refusal it has no words for by the server's code", () => {
    show(403, { error: "forbidden" });
    expect(screen.getByText("The server refused it: forbidden.")).toBeTruthy();
  });
});
