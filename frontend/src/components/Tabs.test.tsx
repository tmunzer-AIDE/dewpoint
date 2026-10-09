// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it } from "vitest";
import { Tabs } from "./Tabs";

function Two() {
  const [tab, setTab] = useState<"setup" | "options">("setup");
  return (
    <Tabs
      label="Settings"
      value={tab}
      onChange={setTab}
      tabs={[
        { value: "setup", label: "Setup", content: <p>required</p> },
        { value: "options", label: "Options · 1 problem", content: <p>the rest</p> },
      ]}
    />
  );
}

it("moves between tabs with the arrow keys, each panel named by its tab", async () => {
  render(<Two />);
  expect(screen.getByRole("tablist", { name: "Settings" })).toBeTruthy();
  screen.getByRole("tab", { name: "Setup" }).focus();
  await userEvent.keyboard("{ArrowRight}");
  const options = screen.getByRole("tab", { name: "Options · 1 problem" });
  expect(document.activeElement).toBe(options);
  expect(options.getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("tabpanel", { name: "Options · 1 problem" }).textContent).toBe("the rest");
  expect(screen.queryByText("required")).toBeNull(); // one panel at a time
});

it("says the chosen tab by its weight and its rule, never by colour alone", () => {
  render(<Two />);
  const chosen = screen.getByRole("tab", { name: "Setup" });
  expect(chosen.className).toContain("data-[state=active]:font-semibold");
  expect(chosen.className).toContain("data-[state=active]:border-accent");
});
