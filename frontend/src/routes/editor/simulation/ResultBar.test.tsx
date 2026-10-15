// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ResultBar } from "./ResultBar";

const props = (over: Partial<Parameters<typeof ResultBar>[0]> = {}) => ({
  phase: "succeeded" as const, revision: 14, endedAt: "2026-10-15T10:42:19Z", notWaited: false, hidden: false, stale: null,
  onHide: vi.fn(), onShow: vi.fn(), onPanel: vi.fn(), onCancel: vi.fn(), ...over,
});  // prettier-ignore

describe("the canvas's bar for a simulation (§7.3; the ResultCanvas and Running boards)", () => {
  it("says while it runs that nothing is sent, and offers Cancel", async () => {
    const p = props({ phase: "running", endedAt: null });
    render(<ResultBar {...p} />);
    expect(screen.getByText("◌ Simulating · running · nothing is sent")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(p.onCancel).toHaveBeenCalled();
  });

  it("says once it ended that nothing was sent and what that doesn't prove, and when a timer wasn't waited", async () => {
    const p = props({ notWaited: true });
    render(<ResultBar {...p} />);
    expect(screen.getByRole("status").textContent).toContain("Simulated. Nothing was sent. Results don't prove the live call will succeed.");
    expect(screen.getByText("Flow delays and wait-until weren't waited; the simulation clock wasn't advanced.")).toBeTruthy();
    expect(screen.getByText(`revision 14 · ${new Date("2026-10-15T10:42:19Z").toLocaleTimeString("en-GB")}`)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Simulation" }));
    expect(p.onPanel).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Hide the result" }));
    expect(p.onHide).toHaveBeenCalled();
  });

  it("says a result is from before the person's edits (§7.7; the Stale board)", () => {
    render(<ResultBar {...props({ stale: { kind: "revision", from: 14, to: 16 } })} />);
    const note = screen.getByText("Before your edits:").parentElement!;
    expect(note.textContent).toBe("Before your edits: this result is for revision 14; the draft is at revision 16.");
    expect(note.className).toMatch(/border-warn-line/);
  });

  it("once hidden, is one bar that brings the result back", async () => {
    const p = props({ hidden: true });
    render(<ResultBar {...p} />);
    expect(screen.getByText("Simulation result hidden · Succeeded · revision 14")).toBeTruthy();
    expect(screen.queryByText(/Nothing was sent/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Show the result" }));
    expect(p.onShow).toHaveBeenCalled();
  });
});
