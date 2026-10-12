// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { VersionsPanel } from "./VersionsPanel";

const v = (number: number, active: boolean, blocked: string[] = []) => ({
  id: `v${number}`, number, published_at: "2026-10-06T10:00:00Z", published_by: null, graph_hash: "h", version_hash: "h",
  cel_profile: "p", engine_abi: 6, node_refs: [], active, executable: blocked.length === 0, blocked_by: blocked,
});  // prettier-ignore

it("lists each version, the active one marked, what blocks one, and offers View and Make active", async () => {
  const onView = vi.fn();
  const onActivate = vi.fn();
  render(<VersionsPanel versions={[v(2, true), v(1, false, ["node:testkit.echo@1"])]} publisher onView={onView} onActivate={onActivate} onClose={vi.fn()} />);
  const items = screen.getAllByRole("listitem");
  expect(items[0]!.textContent).toContain("Version 2");
  expect(items[0]!.textContent).toContain("Active");
  expect(within(items[0]!).queryByRole("button", { name: "Make version 2 active" })).toBeNull();
  expect(items[1]!.textContent).toContain("Can't run: node:testkit.echo@1");
  await userEvent.click(within(items[1]!).getByRole("button", { name: "View version 1" }));
  expect(onView).toHaveBeenCalledWith(expect.objectContaining({ number: 1 }));
  await userEvent.click(within(items[1]!).getByRole("button", { name: "Make version 1 active" }));
  expect(onActivate).toHaveBeenCalledWith(expect.objectContaining({ number: 1 }));
});

it("offers a non-publisher only View", () => {
  render(<VersionsPanel versions={[v(2, true), v(1, false)]} publisher={false} onView={vi.fn()} onActivate={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByRole("button", { name: /Make version/ })).toBeNull();
});
