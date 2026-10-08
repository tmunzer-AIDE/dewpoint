// SPDX-License-Identifier: Apache-2.0
import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { announce } from "../lib/announce";
import { Announcer } from "./Announcer";

it("says each change politely, even the same words twice", () => {
  vi.useFakeTimers();
  render(<Announcer />);
  const region = screen.getByRole("status");
  expect(region.getAttribute("aria-live")).toBe("polite");
  act(() => announce("Added transform after get_device"));
  act(() => {
    vi.advanceTimersByTime(50);
  });
  expect(region.textContent).toBe("Added transform after get_device");
  act(() => announce("Added transform after get_device"));
  expect(region.textContent).toBe(""); // cleared first, so a screen reader hears it again
  act(() => {
    vi.advanceTimersByTime(50);
  });
  expect(region.textContent).toBe("Added transform after get_device");
  vi.useRealTimers();
});
