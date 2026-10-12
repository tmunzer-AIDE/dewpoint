// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { mustReveal, type Rect } from "./reveal";

const rect = (left: number, top: number, right: number, bottom: number): Rect => ({ left, top, right, bottom });
const canvas = rect(0, 0, 800, 600);
const minimap = rect(600, 450, 790, 590);

describe("whether the view moves to the item focus landed on", () => {
  it("stays put for the keyboard when the item is wholly in the clear", () => {
    expect(mustReveal(rect(100, 100, 360, 156), canvas, [minimap], true)).toBe(false);
  });

  it("moves for the keyboard when the item crosses the canvas's edge or lies under what's laid over it", () => {
    expect(mustReveal(rect(700, 100, 960, 156), canvas, [], true)).toBe(true);
    expect(mustReveal(rect(560, 480, 820, 536), canvas, [minimap], true)).toBe(true);
  });

  it("stays put otherwise while any of the item shows: a pointer's press, or a step placed by a click near an edge", () => {
    expect(mustReveal(rect(700, 100, 960, 156), canvas, [], false)).toBe(false);
    expect(mustReveal(rect(500, 480, 760, 536), canvas, [minimap], false)).toBe(false);
  });

  it("moves whoever moved focus when the item is entirely hidden: off the canvas, or wholly under an overlay (WCAG 2.4.11)", () => {
    expect(mustReveal(rect(-900, 100, -640, 156), canvas, [], false)).toBe(true);
    expect(mustReveal(rect(100, 700, 360, 756), canvas, [], false)).toBe(true);
    expect(mustReveal(rect(620, 480, 780, 536), canvas, [minimap], false)).toBe(true);
    // Its visible part, under an overlay flush with the canvas's corner.
    expect(mustReveal(rect(700, 500, 960, 556), canvas, [rect(600, 450, 800, 600)], false)).toBe(true);
  });
});
