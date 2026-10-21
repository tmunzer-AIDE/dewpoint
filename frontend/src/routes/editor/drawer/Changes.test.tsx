// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WORDS } from "../../../lib/changes";
import { formula } from "../../../lib/config";
import { CREATE, UPDATE } from "../../../test/nodeTypes";
import { fakeApi, json, problem, showDrawer } from "./harness";

beforeEach(() => {
  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
});
afterEach(() => {
  vi.restoreAllMocks();
});

const changes = () => screen.getByRole("group", { name: "Changes" });
/** The rows, in order: each one's pointer under the body. */
const rows = (group: HTMLElement) =>
  [...group.querySelectorAll<HTMLElement>("[data-pointer^='/body/']")].map((e) => e.dataset.pointer!).filter((p) => p.split("/").length === 3);

it("draws an update's changes: how they're sent, a row per setting set or cleared, by title, and how many change", () => {
  showDrawer(UPDATE, { config: { mode: "merge", body: { rogue: { enabled: true }, name: "hq" }, clear: ["tags"] } });
  const group = changes();
  expect(within(group).getByRole("radio", { name: WORDS.merge })).toHaveProperty("checked", true);
  expect(within(group).getByText(WORDS.mergeSays)).toBeTruthy();
  expect(rows(group)).toEqual(["/body/name", "/body/rogue", "/body/tags"]);
  const name = group.querySelector<HTMLElement>('[data-pointer="/body/name"]')!;
  expect(within(name).getByText("name").className).toContain("font-mono");
  expect(within(name).getByRole("group", { name: "What happens to Name" })).toBeTruthy();
  expect(within(group.querySelector<HTMLElement>('[data-pointer="/body/tags"]')!).getByText(WORDS.cleared)).toBeTruthy();
  expect(within(group).getByText("3 of 10 settings change; the others stay as they are.")).toBeTruthy();
});

it("says replace's warning when replace is chosen", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq" } } });
  await userEvent.click(within(changes()).getByRole("radio", { name: WORDS.replace }));
  expect(config().mode).toBe("replace");
  expect(within(changes()).getByText(WORDS.replaceSays)).toBeTruthy();
  expect(within(changes()).queryByText(WORDS.mergeSays)).toBeNull();
});

it("clears a setting and sets it back with the value it had, body and clear together", async () => {
  const { config } = showDrawer(UPDATE, { config: { mode: "merge", body: { name: "hq", enabled: true } } });
  const name = () => within(changes()).getByRole("group", { name: "What happens to Name" });
  await userEvent.click(within(name()).getByRole("button", { name: "Clear" }));
  expect(config()).toEqual({ mode: "merge", body: { enabled: true }, clear: ["name"] });
  expect(within(name()).getByRole("button", { name: "Clear" }).getAttribute("aria-pressed")).toBe("true");
  await userEvent.click(within(name()).getByRole("button", { name: "Set" }));
  expect(config()).toEqual({ mode: "merge", body: { enabled: true, name: "hq" } });
});

it("keeps a setting as it is: its row goes, and the count with it", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq", rogue: { enabled: true } }, clear: ["tags"] } });
  await userEvent.click(within(changes()).getByRole("button", { name: "Keep Rogue as it is" }));
  await userEvent.click(within(changes()).getByRole("button", { name: "Keep Tags as it is" }));
  expect(config()).toEqual({ body: { name: "hq" } });
  expect(rows(changes())).toEqual(["/body/name"]);
  expect(within(changes()).getByText("1 of 10 settings change; the others stay as they are.")).toBeTruthy();
});

it("says there's nothing to change, as a warning, when nothing is set or cleared", () => {
  showDrawer(UPDATE, { config: { mode: "merge" } });
  expect(within(changes()).getByText(WORDS.nothing).className).toContain("text-warn-ink");
  expect(within(changes()).getByText("0 of 10 settings change; the others stay as they are.")).toBeTruthy();
});

it("says a setting both set and cleared, and settles it with Set or Clear", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq" }, clear: ["name"] } });
  expect(within(changes()).getByText(WORDS.both)).toBeTruthy();
  await userEvent.click(within(within(changes()).getByRole("group", { name: "What happens to Name" })).getByRole("button", { name: "Set" }));
  expect(config()).toEqual({ body: { name: "hq" } });
});

it("draws a body a formula gives as a formula, its cleared settings still listed", () => {
  showDrawer(UPDATE, { config: { body: formula("steps.build.output"), clear: ["tags"] } });
  expect(within(screen.getByRole("group", { name: "How Changes is set" })).getByRole("button", { name: "Formula" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByText(WORDS.formulaUpdate)).toBeTruthy();
  expect(screen.getByText(WORDS.cleared)).toBeTruthy();
  expect(screen.getByRole("radiogroup", { name: "How the changes are sent" })).toBeTruthy();
});

it("leaves a `clear` naming what the list doesn't offer to today's control, unchanged", () => {
  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq" }, clear: ["id"] } });
  expect(screen.getByRole("group", { name: "Fields to clear" })).toBeTruthy();
  expect(rows(changes())).toEqual(["/body/name"]);
  expect(config().clear).toEqual(["id"]); // opening never rewrites (ledger 102)
});

it("sets a setting of several shapes as JSON in its row", () => {
  showDrawer(UPDATE, { config: { body: { vlan_id: 10 } } });
  const row = changes().querySelector<HTMLElement>('[data-pointer="/body/vlan_id"]')!;
  expect(within(row).getByRole("textbox", { name: "VLAN ID" })).toHaveProperty("value", "10");
  expect(within(row).getByText(/As JSON: Mist takes it in more than one shape\./)).toBeTruthy(); // before the JSON field's own note
});

it("leaves how they're sent, held as a formula, to its formula, its switch named for it", () => {
  showDrawer(UPDATE, { config: { mode: formula('"replace"'), body: { name: "hq" } } });
  const switcher = screen.getByRole("group", { name: "How the way they're sent is set" });
  expect(within(switcher).getByRole("button", { name: "Formula" }).getAttribute("aria-pressed")).toBe("true");
});

it("keeps a problem at a setting the list doesn't draw on the changes", () => {
  showDrawer(UPDATE, { config: { body: { id: "x", name: "hq" } }, problems: [problem("/body/id", "Mist sets it.")] });
  expect(within(changes()).getByText("Mist sets it.")).toBeTruthy();
});

it("sums up the changes in a read-only view, with nothing to press", () => {
  showDrawer(UPDATE, { editable: false, config: { mode: "merge", body: { name: "hq", rogue: { enabled: true, min_rogue_rssi: -80 } }, clear: ["tags"] } });
  const group = changes();
  expect(within(group).getByText("Merge with the current settings · 3 changes")).toBeTruthy();
  expect(within(group).getByText("set: Enabled yes, Min rogue RSSI -80")).toBeTruthy();
  expect(within(group).getByText("cleared")).toBeTruthy();
  expect(within(group).queryByRole("button", { name: /^Keep/ })).toBeNull();
});

it("draws a create's settings: a row per setting given, Remove unless it's required, how many are given", async () => {
  const { config } = showDrawer(CREATE, { config: { body: { name: "n", enabled: true } } });
  const group = screen.getByRole("group", { name: "Settings" });
  expect(within(group).queryByRole("group", { name: /^What happens to/ })).toBeNull();
  expect(within(group).queryByRole("button", { name: "Remove Name" })).toBeNull(); // required
  expect(within(group).getByText("2 of 10 settings given; Mist uses its defaults for the others.")).toBeTruthy();
  await userEvent.click(within(group).getByRole("button", { name: "Remove Enabled" }));
  expect(config()).toEqual({ body: { name: "n" } });
});

it("shows a problem at `clear` with the rows that hold it", () => {
  showDrawer(UPDATE, { config: { clear: ["name"] }, problems: [problem("/clear", "Not a list of names.")] });
  expect(within(changes().querySelector<HTMLElement>('[data-pointer="/clear"]')!).getByText("Not a list of names.")).toBeTruthy();
});

// Find a setting (§5.4).
const finder = () => within(changes()).getByRole("combobox", { name: "Find a setting" });

it("finds a setting and adds it, Set with nothing given until a value is, focus on it", async () => {
  const { config } = showDrawer(UPDATE, { config: { mode: "merge" } });
  await userEvent.type(finder(), "name");
  await userEvent.click(within(changes()).getByRole("option", { name: /^Name/ }));
  const row = changes().querySelector<HTMLElement>('[data-pointer="/body/name"]')!;
  expect(within(row).getByText(WORDS.pending)).toBeTruthy();
  expect(config()).toEqual({ mode: "merge" }); // nothing given, nothing sent
  await vi.waitFor(() => expect(document.activeElement).toBe(within(row).getByLabelText("Name")));
  await userEvent.type(within(row).getByLabelText("Name"), "hq");
  expect(config()).toEqual({ mode: "merge", body: { name: "hq" } });
  expect(within(row).queryByText(WORDS.pending)).toBeNull();
});

it("marks a setting already listed, and says when nothing matches", async () => {
  showDrawer(UPDATE, { config: { body: { name: "hq" } } });
  await userEvent.type(finder(), "name");
  expect(within(changes()).getByRole("option", { name: /^Name/ }).textContent).toContain("· In Changes");
  await userEvent.clear(finder());
  await userEvent.type(finder(), "firewall");
  expect(within(changes()).getByText('No setting matches "firewall", by name or description.')).toBeTruthy();
});

it("lists the top-level settings from ＋ Add a setting, and adds the one Enter picks", async () => {
  showDrawer(UPDATE, { config: {} });
  await userEvent.click(within(changes()).getByRole("button", { name: "＋ Add a setting" }));
  expect(within(changes()).getByText("10 settings; the list scrolls.")).toBeTruthy();
  expect(within(changes()).getAllByRole("option")).toHaveLength(10);
  await userEvent.keyboard("{ArrowDown}{Enter}"); // the second: Auto upgrade
  expect(changes().querySelector('[data-pointer="/body/auto_upgrade"]')).not.toBeNull();
});
