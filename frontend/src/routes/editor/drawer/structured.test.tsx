// SPDX-License-Identifier: Apache-2.0
// What a list's item or a map's entry shows of itself (as JSON, "Required" once left, the mode chosen for an empty
// value) stays with what it was set on, never with its place (#73; ledger M55).
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { typeWith } from "../../../test/nodeTypes";
import { fakeApi, showFields } from "./harness";

beforeEach(() => {
  fakeApi({});
});
afterEach(() => {
  vi.restoreAllMocks();
});

const ROW = { type: "object", required: ["a"], properties: { a: { type: "string", title: "A" } } };
const ROWS = typeWith({ type: "object", properties: { rows: { type: "array", title: "Rows", items: ROW } } });
const BY_NAME = typeWith({ type: "object", properties: { by: { type: "object", title: "By", additionalProperties: ROW } } });

/** The values shown as JSON, in order. */
const shownAsJson = () => [...document.querySelectorAll("textarea")].map((t) => JSON.parse(t.value) as unknown);
/** The part's own "Edit as JSON", in its group. */
const jsonOf = (part: string) => within(screen.getByRole("group", { name: part })).getAllByRole("button", { name: "Edit as JSON" })[0]!;

it("starts a list's items afresh when one is removed: a JSON view never passes to the next item", async () => {
  const { config } = showFields(ROWS, { config: { rows: [{ a: "x" }, { a: "y" }, { a: "z" }] } });
  await userEvent.click(jsonOf("Rows, item 2"));
  expect(shownAsJson()).toEqual([{ a: "y" }]);
  await userEvent.click(screen.getByRole("button", { name: "Remove: Rows, item 1" }));
  expect(config().rows).toEqual([{ a: "y" }, { a: "z" }]);
  expect(shownAsJson()).toEqual([]);
});

it("starts a list's items afresh when one moves", async () => {
  const { config } = showFields(ROWS, { config: { rows: [{ a: "x" }, { a: "y" }, { a: "z" }] } });
  await userEvent.click(jsonOf("Rows, item 2"));
  await userEvent.click(screen.getByRole("button", { name: "Move up: Rows, item 2" }));
  expect(config().rows).toEqual([{ a: "y" }, { a: "x" }, { a: "z" }]);
  expect(shownAsJson()).toEqual([]);
});

it("starts a list's items afresh when an undo brings back the list before", async () => {
  const rows = [{ a: "x" }, { a: "y" }];
  const { replace } = showFields(ROWS, { config: { rows } });
  await userEvent.click(screen.getByRole("button", { name: "Remove: Rows, item 1" }));
  await userEvent.click(jsonOf("Rows, item 1")); // y's
  replace({ rows }); // the removal undone: x is back at the first place
  expect(shownAsJson()).toEqual([]);
});

it("keeps an item's JSON view through an edit in place beside it", async () => {
  const { config } = showFields(ROWS, { config: { rows: [{ a: "x" }, { a: "y" }] } });
  await userEvent.click(jsonOf("Rows, item 2"));
  await userEvent.type(within(screen.getByRole("group", { name: "Rows, item 1" })).getByLabelText("A"), "w");
  expect(config().rows).toEqual([{ a: "xw" }, { a: "y" }]);
  expect(shownAsJson()).toEqual([{ a: "y" }]);
});

it("never passes an item's Required to the next item after a removal", async () => {
  showFields(ROWS, { config: { rows: [{ a: "x" }, { a: "" }, { a: "" }] } });
  const second = within(screen.getByRole("group", { name: "Rows, item 2" })).getByLabelText("A");
  await userEvent.type(second, "q");
  await userEvent.clear(second); // written empty: "Required" once left
  expect(within(screen.getByRole("group", { name: "Rows, item 2" })).getByText("Required")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Remove: Rows, item 1" }));
  expect(within(screen.getByRole("group", { name: "Rows, item 2" })).queryByText("Required")).toBeNull(); // the third's place
});

it("keeps a map entry's JSON view with its name when an entry before it is removed", async () => {
  const { config } = showFields(BY_NAME, { config: { by: { p: { a: "x" }, q: { a: "y" }, r: { a: "z" } } } });
  await userEvent.click(jsonOf("q"));
  await userEvent.click(screen.getByRole("button", { name: "Remove: p" }));
  expect(config().by).toEqual({ q: { a: "y" }, r: { a: "z" } });
  expect(shownAsJson()).toEqual([{ a: "y" }]);
});

it("keeps focus in a map entry's name, and its JSON view, through a rename with Enter", async () => {
  const { config } = showFields(BY_NAME, { config: { by: { q: { a: "y" } } } });
  await userEvent.click(jsonOf("q"));
  const name = screen.getByLabelText("Name: q");
  await userEvent.clear(name);
  await userEvent.type(name, "s{Enter}");
  expect(config().by).toEqual({ s: { a: "y" } });
  expect(document.activeElement).toBe(screen.getByLabelText("Name: s"));
  expect(shownAsJson()).toEqual([{ a: "y" }]);
});

it("keeps focus where Tab took it inside a map entry renamed on the way", async () => {
  const { config } = showFields(BY_NAME, { config: { by: { q: { a: "y" } } } });
  await userEvent.click(jsonOf("q"));
  const name = screen.getByLabelText("Name: q");
  await userEvent.clear(name);
  await userEvent.type(name, "s");
  await userEvent.tab(); // into the entry's own controls: the rename applies as focus leaves the name
  expect(config().by).toEqual({ s: { a: "y" } });
  // One of the entry's own controls after its name: still there, never drawn afresh under the focus.
  const row = screen.getByLabelText("Name: s").closest("[data-name-pointer]")!.parentElement!;
  expect(within(row).getAllByRole("button")).toContain(document.activeElement);
  expect(shownAsJson()).toEqual([{ a: "y" }]);
});

it("gives each entry its own key after a rename, when the old name comes back beside the new one", async () => {
  const errors = vi.spyOn(console, "error");
  const { replace } = showFields(BY_NAME, { config: { by: { q: { a: "y" } } } });
  const name = screen.getByLabelText("Name: q");
  await userEvent.clear(name);
  await userEvent.type(name, "s{Enter}");
  replace({ by: { s: { a: "y" }, q: { a: "x" } } }); // a JSON edit writing both
  expect(screen.getByRole("group", { name: "q" })).toBeTruthy();
  expect(errors.mock.calls.flat().join(" ")).not.toContain("same key");
});

it("keeps a map entry's row through its own name typed again with a space, and lets the edit go (the review)", async () => {
  const { config, held } = showFields(BY_NAME, { config: { by: { q: { a: "y" } } } });
  await userEvent.click(screen.getByLabelText("Name: q"));
  await userEvent.keyboard("{End} ");
  await userEvent.tab(); // the same name, spaces aside: nothing to rename
  expect(held()).toEqual([]);
  const a = within(screen.getByRole("group", { name: "q" })).getByLabelText("A");
  await userEvent.type(a, "12");
  expect(config().by).toEqual({ q: { a: "y12" } }); // every key landed: the row was never drawn afresh
  expect(document.activeElement).toBe(a);
});

it("starts a list's items afresh when one is added, as for any change to the list's shape (the review)", async () => {
  showFields(ROWS, { config: { rows: [{ a: "x" }] } });
  await userEvent.click(jsonOf("Rows, item 1"));
  await userEvent.click(screen.getByRole("button", { name: "Add to Rows" }));
  expect(shownAsJson()).toEqual([]);
});
