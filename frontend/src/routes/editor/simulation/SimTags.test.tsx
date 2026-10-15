// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { SimTags } from "./SimTags";

it("lists a step's result beside its card, in words, each tag drawn as what it is (§7.3, §7.4)", () => {
  render(
    <SimTags
      label="notify"
      tags={[
        { text: "succeeded", kind: "ok" },
        { text: "attempt 2 of 3", kind: "note" },
        { text: "fixture · not sent", kind: "fixture" },
        { text: "input", kind: "given" },
        { text: "evaluated", kind: "evaluated" },
        { text: "didn't run", kind: "absent" },
        { text: "failed", kind: "fail" },
      ]}
    />,
  );
  const list = screen.getByRole("list", { name: "notify: simulated result" });
  const tag = (text: string) => within(list).getByText(text).className;
  expect(list.className).toMatch(/\bleft-full\b/); // beside the card…
  expect(list.className).toMatch(/@max-3xl:top-full/); // …under it at narrow widths
  expect(tag("succeeded")).toMatch(/border-ok/);
  expect(tag("failed")).toMatch(/border-danger/);
  expect(tag("fixture · not sent")).toMatch(/hatch-sim/);
  expect(tag("fixture · not sent")).toMatch(/text-sim/); // the hatch only behind slate text
  expect(tag("input")).toMatch(/border-sim/);
  expect(tag("evaluated")).toMatch(/border-line-strong/);
  expect(tag("didn't run")).toMatch(/border-dashed/);
  expect(tag("attempt 2 of 3")).not.toMatch(/\bborder\b/);
});

it("draws nothing without a result", () => {
  const { container } = render(<SimTags label="notify" tags={[]} />);
  expect(container.textContent).toBe("");
});

it("goes under its card on one line, cut short, where another card is beside it; one line under it at narrow widths", () => {
  render(<SimTags label="long" place="under" tags={[{ text: "12 instances: 1 succeeded · 2 failed · 9 skipped", kind: "status" }, { text: "fixture · not sent", kind: "fixture" }]} />);
  const list = screen.getByRole("list", { name: "long: simulated result" });
  expect(list.className).toMatch(/\btop-full\b/);
  expect(list.className).not.toMatch(/\bleft-full\b/);
  expect(list.className).toMatch(/\btruncate\b/);
  expect(within(list).getByText("fixture · not sent")).toBeTruthy(); // every word still read out
  render(<SimTags label="notify" tags={[{ text: "succeeded", kind: "ok" }]} />);
  expect(screen.getByRole("list", { name: "notify: simulated result" }).className).toMatch(/@max-3xl:truncate/);
});

