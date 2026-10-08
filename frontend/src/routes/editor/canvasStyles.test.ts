// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { PAIRS } from "../../styles/tokenNames";
import css from "./canvas.css?raw";

/** The token a rule's `property` names (`var(--x)` gives "x"), in the first rule whose selector is exactly `selector`. */
function token(selector: string, property: string): string | undefined {
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule ${selector}`);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return new RegExp(`(?:^|[;\\s])${property}\\s*:\\s*var\\(--([\\w-]+)\\)`).exec(body)?.[1];
}

const pinnedAt3 = (fg: string | undefined, bg: string) => PAIRS.some(([f, b, min]) => f === fg && b === bg && min >= 3);

// What the canvas draws to carry meaning is a graphic WCAG 1.4.11 holds to 3:1; axe doesn't measure SVG strokes, so the
// tokens are checked here, against the pairs the contrast tests measure in both themes.
describe("the canvas's graphics", () => {
  it("draws its edges, which say which step follows which, in a token pinned at 3:1 on the canvas's ground", () => {
    expect(pinnedAt3(token(".react-flow__edge-path", "stroke"), "ground")).toBe(true);
  });

  it("draws the minimap's steps in a token pinned at 3:1 on the minimap's surface", () => {
    expect(pinnedAt3(token(".canvas-minimap-node", "fill"), "surface")).toBe(true);
  });
});
