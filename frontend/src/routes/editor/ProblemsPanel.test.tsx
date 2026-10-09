// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { CheckState } from "./check";
import { ProblemsPanel } from "./ProblemsPanel";

const d = (code: string, node: string | null, severity: "error" | "warning", message = code) =>
  ({ code, message, node, field: node ? "/fields" : null, fix: `fix ${code}`, severity });
const VALIDATION = {
  draft_revision: 4, valid: false, taint: { sites: [], declassified: [] },
  diagnostics: [d("config.invalid", "n1", "error", "fields needs at least one entry"), d("vars.unassigned", null, "warning")],
  expressions: [
    { node: "n1", field: "/fields/a", mode: "activity" as const, reason: "builds a message" },
    { node: "n1", field: "/fields/b", mode: "local" as const, reason: null },
  ],
};  // prettier-ignore
const CLEAN = { ...VALIDATION, valid: true, diagnostics: [], expressions: [] };
const keyOf = (id: string) => ({ n1: "transform" })[id] ?? id;

function panel(state: CheckState, validation: typeof VALIDATION | null, more: Partial<Parameters<typeof ProblemsPanel>[0]> = {}) {
  return render(
    <ProblemsPanel state={state} validation={validation} publishProblems={null} publishCurrent={false} keyOf={keyOf} onJump={vi.fn()} onCheck={vi.fn()} onClose={vi.fn()} {...more} />,
  );
}

it("lists errors before warnings, each with its fix and code, a step's going to the step", async () => {
  const onJump = vi.fn();
  panel("current", VALIDATION, { onJump });
  const items = within(screen.getByRole("complementary", { name: "Problems" })).getAllByRole("listitem");
  expect(items[0]!.textContent).toContain("fields needs at least one entry");
  expect(items[0]!.textContent).toContain("fix config.invalid");
  expect(items[1]!.textContent).toContain("vars.unassigned");
  await userEvent.click(within(items[0]!).getByRole("button", { name: "Go to transform" }));
  expect(onJump).toHaveBeenCalledWith("n1", "/fields");
});

it("says how each expression runs (engine-core §5.10)", () => {
  panel("current", VALIDATION);
  expect(screen.getByText(/Runs as a separate step: builds a message/)).toBeTruthy();
  expect(screen.getByText("1 expression runs inline.")).toBeTruthy();
});

it("shows what only publish checks apart, and says when edits came since", () => {
  const found = { revision: 3, generation: 2, diagnostics: [d("connection.unknown", "n1", "error", "That connection doesn't exist.")] };
  panel("current", VALIDATION, { publishProblems: found, publishCurrent: false });
  const section = screen.getByRole("region", { name: "Found at publish" });
  expect(section.textContent).toContain("That connection doesn't exist.");
  expect(section.textContent).toContain("before your latest edits");
});

it("calls the saved draft clean only when the check is current", () => {
  const { unmount } = panel("current", CLEAN);
  expect(screen.getByText(/None found in the saved draft/)).toBeTruthy();
  unmount();
  panel("stale", CLEAN);
  expect(screen.queryByText(/None found/)).toBeNull();
  expect(screen.getByText(/before your latest edits/)).toBeTruthy();
});

it("says a failed check failed, and checks again when asked", async () => {
  const onCheck = vi.fn();
  panel("failed", CLEAN, { onCheck });
  expect(screen.getByText(/The check failed/)).toBeTruthy();
  expect(screen.queryByText(/None found/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Check again" }));
  expect(onCheck).toHaveBeenCalled();
});
