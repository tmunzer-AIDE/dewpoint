// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BUTTON_STATES, type ButtonVariant } from "../styles/tokenNames";
import { Button } from "./Button";

const PREFIX = { default: "", hover: "enabled:hover:", pressed: "enabled:active:" } as const;

describe("Button", () => {
  it.each(Object.keys(BUTTON_STATES) as ButtonVariant[])("draws %s from BUTTON_STATES, state by state", (variant) => {
    render(<Button variant={variant}>Go</Button>);
    const classes = screen.getByRole("button").className.split(/\s+/);
    for (const [state, prefix] of Object.entries(PREFIX) as [keyof typeof PREFIX, string][]) {
      const { fg, bg, border } = BUTTON_STATES[variant][state];
      expect(classes).toEqual(expect.arrayContaining([`${prefix}text-${fg}`, `${prefix}bg-${bg}`, `${prefix}border-${border}`]));
    }
  });

  it("looks disabled through the disabled tokens, and only reacts while enabled", () => {
    render(<Button variant="primary" disabled>Go</Button>);
    const classes = screen.getByRole("button").className.split(/\s+/);
    expect(classes).toEqual(
      expect.arrayContaining(["disabled:bg-disabled-bg", "disabled:border-disabled-line", "disabled:text-disabled-ink"]),
    );
    expect(classes.filter((c) => /^(hover|active):/.test(c))).toEqual([]);
    expect(classes.some((c) => c.includes("opacity"))).toBe(false);
  });

  it("is a plain button unless told otherwise, so it never submits a form by accident", () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole("button").getAttribute("type")).toBe("button");
  });

  it("comes in the design's three heights", () => {
    const { rerender } = render(<Button size="sm">Go</Button>);
    expect(screen.getByRole("button").className).toContain("min-h-8");
    rerender(<Button size="md">Go</Button>);
    expect(screen.getByRole("button").className).toContain("min-h-9");
    rerender(<Button>Go</Button>);
    expect(screen.getByRole("button").className).toContain("min-h-11");
  });
});
