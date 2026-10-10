// SPDX-License-Identifier: Apache-2.0
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { write, type Condition } from "../../../lib/builder";
import { formula } from "../../../lib/config";
import type { ScopeEntry } from "../../../lib/data";
import { IF } from "../../../test/nodeTypes";
import { fakeApi, json, NODE_ID, showFields } from "./harness";

const SITE = "00000000-0000-4000-8000-000000000002";
const steps = [
  { id: NODE_ID, key: "check", title: "If" },
  { id: SITE, key: "get_site", title: "Get a site" },
];
const OUT = "steps.get_site.output";
const entry = (path: string, over: Partial<ScopeEntry> = {}): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: path.split(".").at(-1)!, nameable: true, nullable: false, parent: OUT, path, problem: null, root: "steps",
  sensitive: false, step: SITE, types: ["string"], ...over,
});  // prettier-ignore
const ENTRIES = [
  entry(OUT, { name: "output", parent: null, types: ["object"], children: true }),
  entry(`${OUT}.name`),
  entry(`${OUT}.tz`, { missing: true, formula: { guards: [{ kind: "present", path: `${OUT}.tz`, size: null }], null_test: false, sensitive: false } }),
  entry(`${OUT}.count`, { types: ["integer", "null"], nullable: true, formula: { guards: [], null_test: true, sensitive: false } }),
];

beforeEach(() => {
  fakeApi({
    "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
      const at = q.get("at");
      const entries = at !== null ? ENTRIES.filter((e) => e.path === at) : ENTRIES;
      return json({ draft_revision: 1, node: NODE_ID, field: "/condition", state: "ok", reason: null, entries, more: false, problem: null });
    },
  });
});
afterEach(() => vi.restoreAllMocks());

async function pick(name: string) {
  const tree = await screen.findByRole("tree");
  await userEvent.click(within(tree).getByText(name));
}

describe("the condition builder", () => {
  it("builds a condition from data picked in the tree, and writes the formula", async () => {
    const f = showFields(IF, { steps });
    expect(screen.getByRole("button", { name: "Builder" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("name");
    await userEvent.type(await screen.findByRole("textbox", { name: "Value, Condition 1" }), "HQ");
    expect(f.config()).toEqual({ condition: formula(`(${OUT}.name == "HQ")`) });
  });

  it("offers the operators a value's type takes, and a number only as one", async () => {
    const f = showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("count");
    const op = await screen.findByRole("combobox", { name: "Comparison, Condition 1" });
    expect(within(op).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "is", "is not", "is more than", "is less than", "is at least", "is at most", "is there", "is missing",
    ]);  // prettier-ignore
    await userEvent.selectOptions(op, "more");
    await userEvent.type(screen.getByRole("textbox", { name: "Value, Condition 1" }), "3x");
    expect(f.held()).toMatchObject([{ kind: "condition", why: "Write a number, like 3, -2 or 0.5." }]);
    await userEvent.type(screen.getByRole("textbox", { name: "Value, Condition 1" }), "{Backspace}");
    const c = `${OUT}.count`;
    expect(f.config()).toEqual({ condition: formula(`(${c} != null && (type(${c}) == type(0) || type(${c}) == type(0.0)) && ${c} > 3)`) });
    expect(f.held()).toEqual([]);
  });

  it("opens a formula it wrote as comparisons, and shows the same formula in Formula mode", async () => {
    const built: Condition = {
      match: "any",
      items: [
        { path: `${OUT}.name`, op: "starts_with", value: { kind: "text", text: "HQ-" }, guards: [], nullTest: false },
        { path: `${OUT}.tz`, op: "is_missing", value: null, guards: [{ kind: "present", path: `${OUT}.tz`, size: null }], nullTest: false },
      ],
    };
    const text = write(built)!;
    const f = showFields(IF, { steps, config: { condition: formula(text) } });
    expect(await screen.findByRole("group", { name: "Condition 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "any of these" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: "Formula" }));
    expect(screen.getByLabelText<HTMLTextAreaElement>("Condition").value).toBe(text);
    await userEvent.click(screen.getByRole("button", { name: "Builder" }));
    expect(screen.getByRole("group", { name: "Condition 1" })).toBeTruthy();
    expect(f.config()).toEqual({ condition: formula(text) }); // switching never rewrote it
  });

  it("keeps a formula it didn't write a formula, and says why", () => {
    showFields(IF, { steps, config: { condition: formula("size(steps.get_site.output.name) > 2") } });
    const builder = screen.getByRole("button", { name: "Builder" });
    expect((builder as HTMLButtonElement).disabled).toBe(true);
    expect(document.getElementById(builder.getAttribute("aria-describedby")!)?.textContent).toMatch(/wasn't made with the builder/);
  });

  it("keeps a formula holding text JSON doesn't read a formula, and still shows the field (the review of revision 1)", () => {
    showFields(IF, { steps, config: { condition: formula('(steps.get_site.output.name == "\\x41")') } });
    const builder = screen.getByRole("button", { name: "Builder" });
    expect((builder as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Condition" }).value).toBe('(steps.get_site.output.name == "\\x41")');
  });

  it("reopens \"is there\" for a list's first item as that item, so a later edit compares it (the review of revision 2)", async () => {
    const LABELS = `${OUT}.labels`;
    const guards: ScopeEntry["formula"] extends infer F ? (F extends { guards: infer G } ? G : never) : never = [
      { kind: "is_list", path: LABELS, size: null },
      { kind: "min_size", path: LABELS, size: 0 },
    ];
    const more = [
      entry(LABELS, { types: ["array", "string"] }),
      entry(`${LABELS}[0]`, { parent: LABELS, name: "[0]", missing: true, formula: { guards, null_test: false, sensitive: false } }),
    ];
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
        const at = q.get("at");
        const entries = [...ENTRIES, ...more].filter((e) => at === null || e.path === at);
        return json({ draft_revision: 1, node: NODE_ID, field: "/condition", state: "ok", reason: null, entries, more: false, problem: null });
      },
    });
    const there = write({ match: "all", items: [{ path: `${LABELS}[0]`, op: "is_there", value: null, guards, nullTest: false }] })!;
    const f = showFields(IF, { steps, config: { condition: formula(there) } });
    const op = await screen.findByRole("combobox", { name: "Comparison, Condition 1" });
    await within(op).findByRole("option", { name: "is" }); // once the value's type is known
    await userEvent.selectOptions(op, "is");
    await userEvent.type(await screen.findByRole("textbox", { name: "Value, Condition 1" }), "alpha");
    expect(f.config()).toEqual({ condition: formula(`(type(${LABELS}) == type([]) && size(${LABELS}) > 0 && ${LABELS}[0] == "alpha")`) });
  });

  it("gives focus back to ＋ Condition when the tree closes with Escape (the final review)", async () => {
    showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await screen.findByRole("tree");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "＋ Condition" })));
  });

  it("puts focus on a picked comparison's operator, and on ＋ Condition once it's removed (the final review)", async () => {
    showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("name");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("combobox", { name: "Comparison, Condition 1" })));
    await userEvent.click(screen.getByRole("button", { name: "Remove condition 1" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "＋ Condition" })));
  });

  it("puts focus on ＋ Condition when a group's only comparison is removed, the group gone with it (the review of the final checkpoint)", async () => {
    showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Group" }));
    await pick("name");
    await userEvent.click(await screen.findByRole("button", { name: "Remove condition 1.1" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "＋ Condition" })));
  });

  it("offers a comparison's operators from this revision's answer only, never the previous one's (the review of the final checkpoint)", async () => {
    let revision = 1;
    let pending = false;
    let release = () => {};
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
        const at = q.get("at");
        const answer = json({ draft_revision: revision, node: NODE_ID, field: "/condition", state: "ok", reason: null, entries: ENTRIES.filter((e) => at === null || e.path === at), more: false, problem: null });
        if (revision === 1) return answer;
        pending = true;
        return new Promise<Response>((done) => (release = () => done(answer)));
      },
    });
    const options = { steps, config: { condition: formula(`(${OUT}.name == "HQ")`) }, revision: 1 };
    const f = showFields(IF, options);
    const op = await screen.findByRole("combobox", { name: "Comparison, Condition 1" });
    await waitFor(() => expect(within(op).getAllByRole("option")).toHaveLength(5));
    revision = 2;
    options.revision = 2;
    f.replace(options.config);
    await waitFor(() => expect(pending).toBe(true));
    expect(within(op).getAllByRole("option").map((o) => o.textContent)).toEqual(["is"]); // the comparison as it is, no more
    release();
    await waitFor(() => expect(within(op).getAllByRole("option")).toHaveLength(5));
  });

  it("describes a comparison's value by its problem (the final review)", async () => {
    showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("count");
    const value = await screen.findByRole("textbox", { name: "Value, Condition 1" });
    await userEvent.type(value, "abc");
    const by = value.getAttribute("aria-describedby");
    expect(by && document.getElementById(by)?.textContent).toBe("Write a number, like 3, -2 or 0.5.");
  });

  it("groups comparisons one level deep, each group matching all or any", async () => {
    const f = showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("name");
    await userEvent.type(await screen.findByRole("textbox", { name: "Value, Condition 1" }), "a");
    await userEvent.click(screen.getByRole("button", { name: "＋ Group" })); // its first comparison is picked with it
    await pick("tz");
    const group = await screen.findByRole("group", { name: "Group 2" });
    await userEvent.click(within(group).getByRole("button", { name: "＋ Condition" }));
    await pick("name");
    await waitFor(() => expect(within(screen.getByRole("group", { name: "Group 2" })).getAllByRole("group", { name: /^Condition 2\./ })).toHaveLength(2));
    expect(f.config()).toEqual({
      condition: formula(`(${OUT}.name == "a")\n&& ((has(${OUT}.tz) && ${OUT}.tz == "") || (${OUT}.name == ""))`),
    });
  });

  it("says a fixed true is always true, until a condition replaces it", () => {
    showFields(IF, { steps, config: { condition: true } });
    expect(screen.getByText(/Always true\./)).toBeTruthy();
  });
});
