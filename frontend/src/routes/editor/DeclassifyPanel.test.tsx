// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IF, SWITCH } from "../../test/nodeTypes";
import type { GraphDoc, Validation } from "../../lib/workflows";
import { DeclassifyPanel } from "./DeclassifyPanel";

const CHECK = "00000000-0000-4000-8000-00000000000c";
const ROUTE = "00000000-0000-4000-8000-00000000000d";
const types = new Map([["flow.if@1", IF], ["flow.switch@1", SWITCH]]);
const doc = (declassify: { node: string; field: string }[] = []): GraphDoc => ({
  graph_format: 1,
  nodes: [
    { id: CHECK, key: "check_status", type: "flow.if@1", config: {} },
    { id: ROUTE, key: "route", type: "flow.switch@1", config: {} },
  ],
  settings: { declassify },
});
const check = (over: Partial<Validation> = {}): Validation => ({
  valid: false, draft_revision: 1, expressions: [], conditional_steps: [], taint: { sites: [], declassified: [] },
  diagnostics: [], ...over,
});  // prettier-ignore
const undecided = {
  code: "taint.undeclassified", severity: "error" as const, node: CHECK, field: "/condition",
  message: "This decision reads sensitive data, so the branch taken becomes visible.",
  fix: "List it in the workflow's declassify settings, or decide on data that isn't sensitive.",
};  // prettier-ignore

function show(d: GraphDoc, c: Validation | null, editable = true) {
  const props = { onDeclassify: vi.fn(), onRemove: vi.fn(), onGo: vi.fn(), onClose: vi.fn() };
  render(<DeclassifyPanel doc={d} types={types} check={c} editable={editable} {...props} />);
  return props;
}

describe("Declassify", () => {
  it("says what a decision reveals, as the server does, and declassifies it only once that's confirmed", async () => {
    const p = show(doc(), check({ diagnostics: [undecided] }));
    const site = screen.getByRole("group", { name: "check_status · Condition" });
    expect(within(site).getByText(undecided.message)).toBeTruthy();
    const go = within(site).getByRole("button", { name: "Declassify this decision" });
    expect((go as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(within(site).getByLabelText(/may be visible in run history/));
    await userEvent.click(go);
    expect(p.onDeclassify).toHaveBeenCalledWith({ node: CHECK, field: "/condition" });
    await userEvent.click(within(site).getByRole("button", { name: "Go to the step" }));
    expect(p.onGo).toHaveBeenCalledWith(expect.objectContaining({ node: CHECK, field: "/condition" }));
  });

  it("lists the entries with what each reveals, or why it declassifies nothing, each removable", async () => {
    const entries = [{ node: ROUTE, field: "/cases/1/when" }, { node: CHECK, field: "/condition" }];
    const p = show(doc(entries), check({
      taint: { sites: [], declassified: [{ node: ROUTE, field: "/cases/1/when", reveals: "the port taken" }] },
      diagnostics: [{ code: "taint.stale_declassify", severity: "error", node: null, field: "/settings/declassify/1", message: "This entry declassifies nothing: it isn't a decision that reads sensitive data.", fix: "Remove it." }],
    }));  // prettier-ignore
    expect(screen.getByText("Declassified · 2")).toBeTruthy();
    expect(screen.getByText("route · Cases, item 2 › Condition")).toBeTruthy();
    expect(screen.getByText("Reveals the port taken.")).toBeTruthy();
    expect(screen.getByText(/declassifies nothing/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Remove check_status · Condition" }));
    expect(p.onRemove).toHaveBeenCalledWith(1);
  });

  it("offers no change where the draft can't be changed, and says decisions show once checked", () => {
    show(doc([{ node: CHECK, field: "/condition" }]), null, false);
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    expect(screen.getByText(/show once the draft is checked/)).toBeTruthy();
  });
});
