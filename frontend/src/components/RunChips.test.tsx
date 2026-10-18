// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ModeChip, RunStatusChip } from "./RunChips";

it("says a run's status in words, its look only repeating them: dashed while it waits, the accent while it runs", () => {
  render(
    <p>
      <RunStatusChip status="queued" />
      <RunStatusChip status="running" />
      <RunStatusChip status="deadline_exceeded" />
    </p>,
  );
  expect(screen.getByText("Queued").className).toContain("border-dashed");
  expect(screen.getByText("Running").className).toContain("border-accent");
  expect(screen.getByText("Ran out of time").className).toContain("border-danger");
});

it("says what a run was: live in orange, a simulation hatched in slate, a draft's said so (D2, D3)", () => {
  render(
    <p>
      <ModeChip mode="live" draft={false} />
      <ModeChip mode="simulate" draft={false} />
      <ModeChip mode="simulate" draft />
    </p>,
  );
  expect(screen.getByText("Live").className).toContain("text-live");
  expect(screen.getByText("Simulated").className).toContain("hatch-sim");
  expect(screen.getByText("Draft simulation").className).toContain("hatch-sim");
});
