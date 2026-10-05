// SPDX-License-Identifier: Apache-2.0
import { render, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { BUTTON_STATE_NAMES, BUTTON_STATES, COLOURS, PAIRS } from "../styles/tokenNames";
import { Specimen } from "./Specimen";

it("shows every colour token and every contrast floor, in a light and a dark panel", () => {
  const { container } = render(<Specimen />);
  const panels = [...container.querySelectorAll<HTMLElement>("section[data-theme]")];
  expect(panels.map((p) => p.dataset.theme)).toEqual(["light", "dark"]);
  for (const panel of panels) {
    const swatches = [...panel.querySelectorAll<HTMLElement>("[data-token]")].map((e) => e.dataset.token);
    expect(swatches).toEqual(COLOURS);
    expect(within(panel).getAllByTestId("pair")).toHaveLength(PAIRS.length);
  }
});

it("draws every button variant's states from BUTTON_STATES", () => {
  const { container } = render(<Specimen />);
  const light = container.querySelector<HTMLElement>('section[data-theme="light"]')!;
  const drawn = [...light.querySelectorAll<HTMLElement>("[data-variant]")].map((e) => `${e.dataset.variant}/${e.dataset.state}`);
  const wanted = Object.keys(BUTTON_STATES).flatMap((v) => [...BUTTON_STATE_NAMES, "focus", "disabled"].map((s) => `${v}/${s}`));
  expect(drawn).toEqual(wanted);
});

