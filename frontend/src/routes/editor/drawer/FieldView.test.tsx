// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { formula, literal } from "../../../lib/config";
import { FILTER, IF, REMOTE, SWITCH, TRANSFORM, typeWith } from "../../../test/nodeTypes";
import { STALE } from "../../../lib/unapplied";
import { NODE_ID, problem, showFields } from "./harness";

/** A step of every plain shape: a required text, numbers, a choice, a yes or no, JSON and a group. */
const PLAIN = typeWith({
  type: "object", required: ["name"],
  properties: {
    name: { type: "string", title: "Name", description: "Shown to people." },
    count: { type: "integer", title: "Count", default: 3 },
    ratio: { type: "number", title: "Ratio" },
    mode: { type: "string", enum: ["fast", "safe"], title: "Mode" },
    on: { type: "boolean", title: "On" },
    extra: { type: "array", items: {}, title: "Extra" },
    query: { type: "object", title: "Query", properties: { limit: { type: "integer", title: "Limit" } } },
  },
});  // prettier-ignore

/** A group holding a secret, with a default that holds one too. */
const HOLDER = typeWith({
  type: "object",
  properties: {
    auth: {
      type: "object", title: "Auth", default: { key: "d3fault-s3cr3t" },
      properties: { key: { type: "string", title: "Key", "x-sensitive": true } },
    },
  },
});  // prettier-ignore

const typedValues = () => [...document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea")].map((f) => f.value);

it("labels a field by its title, its hint and the server's problems described by it", () => {
  showFields(PLAIN, { problems: [problem("/name", "Too short.")] });
  const name = screen.getByLabelText("Name");
  const described = name.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(described).toEqual(["Shown to people.", "Too short."]);
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(name.getAttribute("aria-required")).toBe("true");
});

it("writes a number as typed, and holds what isn't one, with why", async () => {
  const { config, held } = showFields(PLAIN);
  await userEvent.type(screen.getByLabelText("Count"), "12");
  expect(config()).toEqual({ count: 12 });
  await userEvent.type(screen.getByLabelText("Count"), ".5");
  expect(screen.getByText("A whole number, like 42.")).toBeTruthy();
  expect(config()).toEqual({ count: 12 });
  expect(held().map((u) => [u.kind, u.text])).toEqual([["number", "12.5"]]);
  await userEvent.type(screen.getByLabelText("Ratio"), "2.");
  expect(screen.getByLabelText<HTMLInputElement>("Ratio").value).toBe("2."); // as typed, while it means 2
  expect(config()).toEqual({ count: 12, ratio: 2 });
});

it("discards an edit not applied, on purpose", async () => {
  const { held } = showFields(PLAIN, { config: { count: 4 } });
  await userEvent.type(screen.getByLabelText("Count"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Discard the edit to Count" }));
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("4");
  expect(held()).toEqual([]);
});

it("removes an emptied field, so its default applies, and says a required one is needed", async () => {
  const { config } = showFields(PLAIN, { config: { name: "a", count: 5 } });
  await userEvent.clear(screen.getByLabelText("Count"));
  await userEvent.clear(screen.getByLabelText("Name"));
  expect(config()).toEqual({});
  expect(screen.getByText("Required")).toBeTruthy();
});

it("makes one mark of a field's typing while it keeps focus", async () => {
  const { edits } = showFields(PLAIN);
  await userEvent.type(screen.getByLabelText("Name"), "ab");
  await userEvent.tab();
  await userEvent.type(screen.getByLabelText("Name"), "c");
  const marks = edits.map((e) => e.mark);
  expect(marks).toHaveLength(3);
  expect(marks[1]).toBe(marks[0]);
  expect(marks[2]).not.toBe(marks[1]);
  expect(marks[0]).toMatch(new RegExp(`^${NODE_ID}/name#\\d+$`));
});

it("makes each choice of a select or a checkbox an undo step of its own", async () => {
  const { config, edits } = showFields(PLAIN);
  await userEvent.selectOptions(screen.getByLabelText("Mode"), "fast");
  await userEvent.click(screen.getByLabelText("On"));
  expect(config()).toEqual({ mode: "fast", on: true });
  expect(edits.map((e) => e.mark)).toEqual([undefined, undefined]);
  await userEvent.selectOptions(screen.getByLabelText("Mode"), "Not set");
  expect(config()).toEqual({ on: true });
});

it("shows a group's parts, and a problem in a part it doesn't show at the group", () => {
  showFields(PLAIN, { config: { query: { limit: 5, other: 1 } }, problems: [problem("/query/other", "Not one of its fields.")] });
  const group = screen.getByRole("group", { name: "Query" });
  expect(within(group).getByLabelText<HTMLInputElement>("Limit").value).toBe("5");
  expect(within(group).getByText("Not one of its fields.")).toBeTruthy();
});

it("edits a group as JSON, the engine's reading, applied when focus leaves", async () => {
  const { config, held } = showFields(PLAIN, { config: { query: { limit: 5 } } });
  await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
  const json = screen.getByLabelText<HTMLTextAreaElement>("Query");
  expect(JSON.parse(json.value)).toEqual({ limit: 5 });
  await userEvent.clear(json);
  await userEvent.paste('{"limit": {"$value": {"kind": "ref", "path": "trigger.n"}}}');
  expect(config()).toEqual({ query: { limit: 5 } }); // held while it's typed
  expect(held()).toHaveLength(1);
  await userEvent.tab();
  expect(config()).toEqual({ query: { limit: { $value: { kind: "ref", path: "trigger.n" } } } }); // never wrapped
  expect(held()).toEqual([]);
});

it("keeps unapplied JSON through a change of view, applying what's valid first", async () => {
  const { config, held } = showFields(PLAIN, { config: { query: { limit: 5 } } });
  const toggle = () => screen.getByRole("button", { name: "Edit as JSON" });
  await userEvent.click(toggle());
  await userEvent.clear(screen.getByLabelText("Query"));
  await userEvent.paste('{"limit": ');
  await userEvent.click(toggle()); // focus leaves (applied: refused), then the toggle waits for it
  expect(screen.getByText("This isn't valid JSON, so it isn't saved.")).toBeTruthy();
  expect(screen.getByLabelText<HTMLTextAreaElement>("Query").value).toBe('{"limit": '); // kept, still shown
  expect(held()).toHaveLength(1);
  await userEvent.click(screen.getByLabelText("Query"));
  await userEvent.paste("7}");
  await userEvent.click(toggle()); // valid now: applied, then the form
  expect(config()).toEqual({ query: { limit: 7 } });
  expect(within(screen.getByRole("group", { name: "Query" })).getByLabelText<HTMLInputElement>("Limit").value).toBe("7");
  expect(held()).toEqual([]);
});

it("says a JSON number too large to keep, and keeps it out of the draft", async () => {
  const { config } = showFields(PLAIN);
  await userEvent.click(within(screen.getByRole("group", { name: "How Extra is set" })).getByRole("button", { name: "Fixed" }));
  await userEvent.click(screen.getByLabelText("Extra"));
  await userEvent.paste("[1e400]");
  await userEvent.tab();
  expect(screen.getByText("A number here is too large to keep, so it isn't saved.")).toBeTruthy();
  for (const n of ["9007199254740993", "9007199254740993.0", "9007199254740993e0"]) {
    await userEvent.clear(screen.getByLabelText("Extra"));
    await userEvent.paste(`[${n}]`);
    await userEvent.tab();
    expect(screen.getByText("A whole number here is too large to keep exactly, so it isn't saved.")).toBeTruthy();
  }
  expect(config()).toEqual({});
});

it("takes no whole number past 2^53 in a number field, in any notation", async () => {
  const { config } = showFields(PLAIN);
  for (const n of ["9007199254740993", "9007199254740993.0", "9007199254740993e0"]) {
    await userEvent.clear(screen.getByLabelText("Ratio"));
    await userEvent.paste(n); // at once: what's typed on the way may be a smaller, valid number
    expect(screen.getByText("A whole number this large can't be kept exactly.")).toBeTruthy();
  }
  expect(config()).toEqual({});
});

it("keeps a held number shown when the value under it changes, as an undo does", async () => {
  const { held, replace } = showFields(PLAIN, { config: { count: 5 } });
  await userEvent.type(screen.getByLabelText("Count"), "x");
  replace({ count: 7 });
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("5x");
  expect(held()).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Discard the edit to Count" }));
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("7");
});

it("shows a held JSON edit, and its reason, when the drawer reopens", async () => {
  const { remount } = showFields(PLAIN, { config: { query: { limit: 5 } } });
  await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
  await userEvent.clear(screen.getByLabelText("Query"));
  await userEvent.paste('{"limit": ');
  await userEvent.tab(); // refused: kept, with why
  remount();
  expect(screen.getByLabelText<HTMLTextAreaElement>("Query").value).toBe('{"limit": ');
  expect(screen.getByText("This isn't valid JSON, so it isn't saved.")).toBeTruthy();
});

it("keeps what a refused write turned away, with its reason", async () => {
  const { config, held, refuse } = showFields(PLAIN, { config: { count: 5 } });
  refuse("Not written: the draft can't be changed now.");
  await userEvent.type(screen.getByLabelText("Name"), "ab");
  await userEvent.clear(screen.getByLabelText("Count"));
  await userEvent.type(screen.getByLabelText("Count"), "7");
  expect(screen.getByLabelText<HTMLInputElement>("Name").value).toBe("ab");
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("7");
  expect(config()).toEqual({ count: 5 });
  expect(held().map((u) => [u.kind, u.text])).toEqual([["text", "ab"], ["number", "7"]]);
  expect(screen.getAllByText("Not written: the draft can't be changed now.")).toHaveLength(2);
});

it("keeps held text visible when an undo brings back a reference under it", async () => {
  const { replace } = showFields(PLAIN, { config: { count: 5 } });
  await userEvent.type(screen.getByLabelText("Count"), "x");
  replace({ count: { $value: { kind: "ref", path: "trigger.n" } } });
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("5x"); // still there, not behind the reference
  expect(screen.getByText(STALE)).toBeTruthy();
});

it("keeps a pending literal edit a literal, and asks before applying it over what changed", async () => {
  const data = { limit: { $value: { kind: "ref", path: "trigger.n" } } };
  const { config, replace } = showFields(PLAIN, { config: { query: literal(data) } });
  await userEvent.clear(screen.getByLabelText("Query"));
  await userEvent.paste('{"limit": {"$value": {"kind": "ref", "path": "trigger.m"}}'); // not finished
  replace({ query: { limit: 1 } }); // an undo: data, no longer a literal
  await userEvent.click(screen.getByLabelText("Query"));
  await userEvent.paste("}");
  await userEvent.tab();
  expect(config()).toEqual({ query: { limit: 1 } }); // never applied over what changed unasked
  expect(screen.getByText(STALE)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Apply here: Query" }));
  expect(config()).toEqual({ query: literal({ limit: { $value: { kind: "ref", path: "trigger.m" } } }) }); // data still
});

it("discards a JSON edit without applying it, by pointer or by keyboard", async () => {
  const { config } = showFields(PLAIN, { config: { query: { limit: 5 } } });
  await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
  await userEvent.clear(screen.getByLabelText("Query"));
  await userEvent.paste('{"limit": 2}'); // valid: leaving the field would apply it
  await userEvent.click(screen.getByRole("button", { name: "Discard the edit to Query" }));
  expect(config()).toEqual({ query: { limit: 5 } });
  await userEvent.clear(screen.getByLabelText("Query")); // still JSON: the view is the person's
  await userEvent.paste('{"limit": 3}');
  const discard = screen.getByRole("button", { name: "Discard the edit to Query" });
  while (document.activeElement !== discard) await userEvent.tab({ shift: true }); // back through the field's actions
  await userEvent.keyboard("{Enter}");
  expect(config()).toEqual({ query: { limit: 5 } });
});

it("writes nothing by showing a field", () => {
  const { edits, held } = showFields(PLAIN, {
    config: { ratio: 1e300, name: literal("x"), count: { $value: { kind: "ref", path: "trigger.n" } } },
  });
  expect(edits).toEqual([]); // a value the drawer would refuse as typed is still never rewritten by opening it
  expect(held()).toEqual([]);
});

it("edits a literal as its payload, and keeps it a literal", async () => {
  const data = { limit: { $value: { kind: "ref", path: "trigger.n" } } }; // data, not a reference
  const { config } = showFields(PLAIN, { config: { name: literal("hi"), query: literal(data) } });
  await userEvent.type(screen.getByLabelText("Name"), "!");
  const json = screen.getByLabelText<HTMLTextAreaElement>("Query"); // a literal's parts are its payload's: JSON
  expect(JSON.parse(json.value)).toEqual(data);
  expect(screen.getAllByText(/Written as a literal: kept as data/)).toHaveLength(2); // the name's hint and the JSON's
  await userEvent.clear(json);
  await userEvent.paste('{"limit": {"$value": {"kind": "ref", "path": "trigger.m"}}}');
  await userEvent.tab();
  expect(config()).toEqual({
    name: literal("hi!"),
    query: literal({ limit: { $value: { kind: "ref", path: "trigger.m" } } }),
  });
});

it("keeps a formula, says how it runs, and turns a fixed value into the formula that gives it", async () => {
  const { config } = showFields(IF, {
    config: { condition: formula("trigger.n > 1") },
    expressions: [{ node: NODE_ID, field: "/condition", mode: "activity", reason: "it reads a large value" }],
  });
  expect(screen.getByLabelText<HTMLTextAreaElement>("Condition").value).toBe("trigger.n > 1");
  expect(screen.getByText("Runs as a separate step: it reads a large value")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Fixed" }));
  expect(config()).toEqual({});
  await userEvent.click(screen.getByLabelText("Condition")); // a checkbox now
  await userEvent.click(screen.getByRole("button", { name: "Formula" }));
  expect(config()).toEqual({ condition: formula("true") });
});

it("offers no fixed value where the engine takes only a formula", () => {
  showFields(FILTER);
  expect(screen.queryByRole("group", { name: "How Predicate is set" })).toBeNull();
  expect(screen.getByLabelText("Predicate").tagName).toBe("TEXTAREA");
});

it("offers neither a fixed value nor a formula where the engine takes only references", () => {
  const refs = typeWith({ type: "object", properties: { source: { type: "string", title: "Source", "x-dewpoint-kinds": ["ref"] } } });
  showFields(refs, { config: { source: { $value: { kind: "ref", path: "trigger.site" } } } });
  expect(screen.getByLabelText("Source").textContent).toBe("trigger.site");
  expect(screen.getByText(/takes only references or text with references, which can't be set in this drawer/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Fixed|Formula|Replace/ })).toBeNull();
  expect(screen.queryByRole("textbox")).toBeNull();
});

it("shows a reference read only, and keeps it until it's replaced", async () => {
  const ref = { $value: { kind: "ref", path: "steps.fetch.output.name" } };
  const { config, edits } = showFields(PLAIN, { config: { name: ref } });
  expect(screen.getByLabelText("Name").textContent).toBe("steps.fetch.output.name");
  expect(edits).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
  expect(config()).toEqual({ name: formula("steps.fetch.output.name") });
});

it("never shows a sensitive field's fixed value", async () => {
  const { config } = showFields(REMOTE, { config: { token: "s3cr3t-value" } });
  expect(document.body.textContent).not.toContain("s3cr3t");
  expect(typedValues().some((v) => v.includes("s3cr3t"))).toBe(false);
  expect(screen.getByLabelText("Token").textContent).toBe("A fixed value is written here, which a sensitive field can't keep.");
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
  expect(config()).toEqual({});
  expect(screen.getByLabelText("Token").tagName).toBe("TEXTAREA");
});

it("never shows a sensitive part as JSON, a default or a formula", async () => {
  const { config } = showFields(HOLDER, { config: { auth: { key: "s3cr3t-value" } } });
  expect(screen.getByRole("group", { name: "Auth" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Edit as JSON" })).toBeNull();
  await userEvent.click(within(screen.getByRole("group", { name: "How Auth is set" })).getByRole("button", { name: "Formula" }));
  expect(config()).toEqual({}); // the formula starts empty: nothing copied out of the hidden value
  expect(screen.getByLabelText<HTMLTextAreaElement>("Auth").value).toBe("");
  expect(document.body.textContent).not.toMatch(/s3cr3t/);
  expect(typedValues().some((v) => v.includes("s3cr3t"))).toBe(false);
});

it("disables every control for a person who can't edit", () => {
  showFields(PLAIN, { config: { name: "a", count: 2 }, editable: false });
  expect(screen.getByLabelText<HTMLInputElement>("Name").disabled).toBe(true);
  expect(screen.getByLabelText<HTMLSelectElement>("Mode").disabled).toBe(true);
  expect(screen.queryByRole("button", { name: /^Clear/ })).toBeNull();
});

it("adds, moves and removes a list's items", async () => {
  const { config } = showFields(REMOTE);
  await userEvent.click(screen.getByRole("button", { name: "Add to Tags" }));
  await userEvent.type(screen.getByLabelText("Tags, item 1"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Add to Tags" }));
  await userEvent.type(screen.getByLabelText("Tags, item 2"), "y");
  expect(config().tags).toEqual(["x", "y"]);
  await userEvent.click(screen.getByRole("button", { name: "Move up: Tags, item 2" }));
  expect(config().tags).toEqual(["y", "x"]);
  await userEvent.click(screen.getByRole("button", { name: "Remove: Tags, item 1" }));
  expect(config().tags).toEqual(["x"]);
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add to Tags" })));
});

it("moves an item only once the edits inside it are applied", async () => {
  const sizes = typeWith({ type: "object", properties: { sizes: { type: "array", title: "Sizes", items: { type: "integer" } } } });
  const { config } = showFields(sizes, { config: { sizes: [1, 2] } });
  await userEvent.type(screen.getByLabelText("Sizes, item 2"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Move up: Sizes, item 2" }));
  expect(config()).toEqual({ sizes: [1, 2] }); // it waits: "2x" can't be applied
  expect(screen.getByText("A whole number, like 42.")).toBeTruthy();
  await userEvent.clear(screen.getByLabelText("Sizes, item 2"));
  await userEvent.type(screen.getByLabelText("Sizes, item 2"), "5");
  await userEvent.click(screen.getByRole("button", { name: "Move up: Sizes, item 2" }));
  expect(config()).toEqual({ sizes: [5, 1] });
});

it("never writes a held edit over another item after an undo moves it", async () => {
  const sizes = typeWith({ type: "object", properties: { sizes: { type: "array", title: "Sizes", items: { type: "integer" } } } });
  const { config, replace } = showFields(sizes, { config: { sizes: [5, 7] } });
  await userEvent.click(screen.getByRole("button", { name: "Move up: Sizes, item 2" })); // [7, 5]
  await userEvent.type(screen.getByLabelText("Sizes, item 2"), "x"); // "5x", over the 5
  replace({ sizes: [5, 7] }); // the move undone: the second item is the 7 now
  await userEvent.type(screen.getByLabelText("Sizes, item 2"), "{Backspace}0"); // "50": a number, typed over the 5
  expect(config()).toEqual({ sizes: [5, 7] }); // never [5, 50] unasked
  expect(screen.getByText(STALE)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Apply here: Sizes, item 2" })); // the person's choice
  expect(config()).toEqual({ sizes: [5, 50] });
});

it("adds a case with the first free port name", async () => {
  const { config } = showFields(SWITCH);
  await userEvent.click(screen.getByRole("button", { name: "Add to Cases" }));
  expect(config()).toEqual({ cases: [{ port: "case_1" }] });
  const item = screen.getByRole("group", { name: "Cases, item 1" });
  expect(within(item).getByLabelText<HTMLInputElement>("Port").value).toBe("case_1");
  expect(within(item).getByLabelText("When").tagName).toBe("TEXTAREA");
});

it("sets a map's entries, renamed in place, never as $value", async () => {
  const { config, held } = showFields(TRANSFORM);
  await userEvent.click(screen.getByRole("button", { name: "Add to Fields" }));
  await userEvent.type(screen.getByLabelText("field_1"), "1 + 1"); // an entry starts as a formula
  const name = screen.getByLabelText("Name: field_1");
  await userEvent.clear(name);
  await userEvent.type(name, "total");
  expect(held().map((u) => [u.kind, u.text])).toEqual([["name", "total"]]); // held while it's typed
  await userEvent.tab();
  expect(config()).toEqual({ fields: { total: formula("1 + 1") } });
  const renamed = screen.getByLabelText("Name: total");
  await userEvent.clear(renamed);
  await userEvent.type(renamed, "$value");
  await userEvent.tab();
  expect(screen.getByText("A name can't be $value: the engine would read the whole value as computed.")).toBeTruthy();
  expect(config()).toEqual({ fields: { total: formula("1 + 1") } });
});

it("discards a new name without renaming the entry", async () => {
  const { config } = showFields(TRANSFORM, { config: { fields: { old: 1 } } });
  const name = screen.getByLabelText("Name: old");
  await userEvent.clear(name);
  await userEvent.type(name, "new");
  await userEvent.click(screen.getByRole("button", { name: "Discard the new name for old" }));
  expect(config()).toEqual({ fields: { old: 1 } });
  expect(screen.getByLabelText<HTMLInputElement>("Name: old").value).toBe("old");
});

it("never writes a held edit into the other of two equal items after an undo moves them", async () => {
  const items = typeWith({
    type: "object",
    properties: {
      lines: {
        type: "array", title: "Lines",
        items: { type: "object", properties: { label: { type: "string", title: "Label" }, amount: { type: "integer", title: "Amount" } } },
      },
    },
  });  // prettier-ignore
  const before = { lines: [{ label: "A", amount: 5 }, { label: "B", amount: 5 }] };
  const { config, replace } = showFields(items, { config: before });
  await userEvent.click(screen.getByRole("button", { name: "Move up: Lines, item 2" })); // [B, A]
  const second = () => within(screen.getByRole("group", { name: "Lines, item 2" })).getByLabelText("Amount");
  await userEvent.type(second(), "x"); // "5x": A's amount
  replace(before); // the move undone: B, its amount an equal 5, is the second item now
  await userEvent.type(second(), "{Backspace}0"); // "50"
  expect(config()).toEqual(before); // B's amount is never written
  expect(screen.getByText(STALE)).toBeTruthy();
});

it("renames an entry only once the edit inside it is applied", async () => {
  const sizes = typeWith({ type: "object", properties: { sizes: { type: "object", title: "Sizes", additionalProperties: { type: "integer" } } } });
  const { config } = showFields(sizes, { config: { sizes: { old: 2 } } });
  await userEvent.type(screen.getByLabelText("old"), "x"); // "2x": held under the entry's name
  const name = screen.getByLabelText("Name: old");
  await userEvent.clear(name);
  await userEvent.type(name, "new");
  await userEvent.tab();
  expect(screen.getByText("Not applied: an edit inside it isn't applied yet.")).toBeTruthy();
  expect(config()).toEqual({ sizes: { old: 2 } }); // the held "2x" never points at a name that's gone
  await userEvent.clear(screen.getByLabelText("old"));
  await userEvent.type(screen.getByLabelText("old"), "1");
  await userEvent.click(screen.getByLabelText("Name: old"));
  await userEvent.tab();
  expect(config()).toEqual({ sizes: { new: 1 } });
});

it("clears the field on purpose, even when what was typed in it is stale", async () => {
  const { config, held, replace } = showFields(PLAIN, { config: { count: 5 } });
  await userEvent.type(screen.getByLabelText("Count"), "x"); // "5x", held
  replace({ count: 7 }); // an undo under it: the held edit is stale now
  await userEvent.click(screen.getByRole("button", { name: "Clear Count" }));
  expect(held()).toEqual([]); // what was typed is discarded
  expect(config()).toEqual({}); // and the field is cleared, as asked
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("");
});

it("clears nothing when the editor refuses the write, and says why", async () => {
  const { config, refuse } = showFields(PLAIN, { config: { count: 5 } });
  refuse("Not written: the draft can't be changed now.");
  await userEvent.click(screen.getByRole("button", { name: "Clear Count" }));
  expect(config()).toEqual({ count: 5 }); // the editor's guards still hold
  expect(screen.getByText("Not written: the draft can't be changed now.")).toBeTruthy();
});
