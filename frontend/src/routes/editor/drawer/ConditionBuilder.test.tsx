// SPDX-License-Identifier: Apache-2.0
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { write, type Condition, type Op } from "../../../lib/builder";
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
  entry(`${OUT}.any`, { types: [] }), // any value: the step doesn't describe it (#85)
  entry(`${OUT}.mixed`, { types: ["integer", "string"] }),
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

describe("a value of no known type (#85)", () => {
  const A = `${OUT}.any`;
  const value = () => screen.getByRole("textbox", { name: "Value, Condition 1" });
  const pressed = () =>
    within(screen.getByRole("group", { name: "Compare as, Condition 1" })).getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent);
  async function anyIs() {
    const f = showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("any");
    await screen.findByRole("textbox", { name: "Value, Condition 1" });
    return f;
  }

  it("compares with a number when a number is typed, with text otherwise, and says which", async () => {
    const f = await anyIs();
    await userEvent.type(value(), "3");
    expect(f.config()).toEqual({ condition: formula(`(${A} == 3)`) });
    expect(pressed()).toEqual(["as number"]);
    await userEvent.type(value(), "a");
    expect(f.config()).toEqual({ condition: formula(`(${A} == "3a")`) });
    expect(pressed()).toEqual(["as text"]);
  });

  it("compares as text once the person says so, whatever is typed, and as a number again when asked", async () => {
    const f = await anyIs();
    await userEvent.type(value(), "3");
    await userEvent.click(screen.getByRole("button", { name: "as text" }));
    expect(f.config()).toEqual({ condition: formula(`(${A} == "3")`) });
    await userEvent.type(value(), "4");
    expect(f.config()).toEqual({ condition: formula(`(${A} == "34")`) });
    await userEvent.click(screen.getByRole("button", { name: "as number" }));
    expect(f.config()).toEqual({ condition: formula(`(${A} == 34)`) });
  });

  it("keeps a comparison read back as text as text, typing more", async () => {
    const f = showFields(IF, { steps, config: { condition: formula(`(${A} == "3")`) } });
    await waitFor(() => expect(pressed()).toEqual(["as text"]));
    await userEvent.type(value(), "4");
    expect(f.config()).toEqual({ condition: formula(`(${A} == "34")`) });
  });

  it("does the same for \"is not\"", async () => {
    const f = await anyIs();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Comparison, Condition 1" }), "is_not");
    await userEvent.type(value(), "3");
    expect(f.config()).toEqual({ condition: formula(`(${A} != 3)`) });
  });

  it("offers the choice for a number among other types, never for a value of one type", async () => {
    showFields(IF, { steps });
    for (const name of ["mixed", "name", "count"]) {
      await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
      await pick(name);
    }
    await screen.findByRole("textbox", { name: "Value, Condition 3" });
    expect(screen.getByRole("group", { name: "Compare as, Condition 1" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Compare as, Condition 2" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Compare as, Condition 3" })).toBeNull();
  });

  it("compares text for \"contains\", and follows what's typed again back on \"is\"", async () => {
    const f = await anyIs();
    await userEvent.type(value(), "3");
    const op = screen.getByRole("combobox", { name: "Comparison, Condition 1" });
    await userEvent.selectOptions(op, "contains");
    expect(f.config()).toEqual({ condition: formula(`(type(${A}) == type("") && ${A}.contains("3"))`) });
    expect(screen.queryByRole("group", { name: "Compare as, Condition 1" })).toBeNull();
    await userEvent.selectOptions(op, "is");
    expect(f.config()).toEqual({ condition: formula(`(${A} == 3)`) });
  });
});

describe("a comparison's pill (#85)", () => {
  const N = `${OUT}.name`;
  const built = (items: Condition["items"]) => formula(write({ match: "all", items })!);
  const nameIs = (text: string, op: Op = "is") => ({ path: N, op, value: { kind: "text" as const, text }, guards: [], nullTest: false });
  const pillOf = (label: string) => within(screen.getByRole("group", { name: label })).getByRole("button", { name: /^get_site › name/ });

  it("opens its details, what it is and when it runs, without a default; Escape gives focus back to the pill", async () => {
    showFields(IF, { steps, config: { condition: built([nameIs("HQ")]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    const details = await screen.findByRole("dialog", { name: N });
    expect(details.textContent).toContain("Type");
    expect(within(details).queryByRole("button", { name: "Add a default…" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: N })).toBeNull();
    expect(document.activeElement).toBe(pillOf("Condition 1"));
  });

  it("offers no default for a value that may be missing: the comparison's guards decide what missing data does", async () => {
    const tz = `${OUT}.tz`;
    const guards = [{ kind: "present" as const, path: tz, size: null }];
    showFields(IF, { steps, config: { condition: built([{ path: tz, op: "is", value: { kind: "text", text: "UTC" }, guards, nullTest: false }]) } });
    await userEvent.click(await waitFor(() => within(screen.getByRole("group", { name: "Condition 1" })).getByRole("button", { name: /^get_site › tz/ })));
    const details = await screen.findByRole("dialog", { name: tz });
    expect(details.textContent).toContain("may be missing");
    expect(within(details).queryByRole("button", { name: "Add a default…" })).toBeNull();
  });

  it("replaces its value, keeping its operator and value when the new value takes them; focus on its operator", async () => {
    const f = showFields(IF, { steps, config: { condition: built([nameIs("HQ")]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    await userEvent.click(within(await screen.findByRole("dialog", { name: N })).getByRole("button", { name: "Replace…" }));
    await pick("tz");
    const tz = `${OUT}.tz`;
    expect(f.config()).toEqual({ condition: formula(`(has(${tz}) && ${tz} == "HQ")`) });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("combobox", { name: "Comparison, Condition 1" })));
  });

  it("starts the comparison again on a new value that doesn't take its operator", async () => {
    showFields(IF, { steps, config: { condition: built([nameIs("HQ", "starts_with")]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    await userEvent.click(within(await screen.findByRole("dialog", { name: N })).getByRole("button", { name: "Replace…" }));
    await pick("count");
    expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "Comparison, Condition 1" }).value).toBe("is");
    expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Value, Condition 1" }).value).toBe("");
  });

  it("keeps a comparison's kind on a new value that may be either", async () => {
    const A = `${OUT}.any`;
    const M = `${OUT}.mixed`;
    const anyIs = (kind: "text" | "number") => ({ path: A, op: "is" as Op, value: { kind, text: "3" }, guards: [], nullTest: false });
    const anyPill = () => within(screen.getByRole("group", { name: "Condition 1" })).getByRole("button", { name: /^get_site › any/ });
    for (const [kind, written] of [["text", `(${M} == "3")`], ["number", `(${M} == 3)`]] as const) {
      const f = showFields(IF, { steps, config: { condition: built([anyIs(kind)]) } });
      await userEvent.click(await waitFor(() => anyPill()));
      await userEvent.click(within(await screen.findByRole("dialog", { name: A })).getByRole("button", { name: "Replace…" }));
      await pick("mixed");
      expect(f.config()).toEqual({ condition: formula(written) });
      cleanup();
    }
  });

  it("replaces a comparison in a group in its place", async () => {
    const f = showFields(IF, { steps, config: { condition: built([{ match: "any", rows: [nameIs("a"), nameIs("b")] }]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1.2")));
    await userEvent.click(within(await screen.findByRole("dialog", { name: N })).getByRole("button", { name: "Replace…" }));
    await pick("tz");
    const tz = `${OUT}.tz`;
    expect(f.config()).toEqual({ condition: formula(`((${N} == "a") || (has(${tz}) && ${tz} == "b"))`) });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("combobox", { name: "Comparison, Condition 1.2" })));
  });

  it("removes the comparison from its details, as its ×", async () => {
    const f = showFields(IF, { steps, config: { condition: built([nameIs("HQ")]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    await userEvent.click(within(await screen.findByRole("dialog", { name: N })).getByRole("button", { name: "Remove" }));
    expect(f.config()).toEqual({});
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "＋ Condition" })));
  });

  it("shows a viewer its details, with nothing to change", async () => {
    showFields(IF, { steps, editable: false, config: { condition: built([nameIs("HQ")]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    const details = await screen.findByRole("dialog", { name: N });
    expect(within(details).queryByRole("button", { name: "Replace…" })).toBeNull();
    expect(within(details).queryByRole("button", { name: "Remove" })).toBeNull();
  });
});

describe("the review of the build (#85)", () => {
  const A = `${OUT}.any`;
  const N = `${OUT}.name`;
  const built = (items: Condition["items"]) => formula(write({ match: "all", items })!);
  const nameIs = (text: string) => ({ path: N, op: "is" as Op, value: { kind: "text" as const, text }, guards: [], nullTest: false });
  const value = () => screen.getByRole("textbox", { name: "Value, Condition 1" });
  const pressed = () =>
    within(screen.getByRole("group", { name: "Compare as, Condition 1" })).getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent);
  const pillOf = (label: string, name = /^get_site › name/) => within(screen.getByRole("group", { name: label })).getByRole("button", { name });
  async function anyIs() {
    const f = showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("any");
    await waitFor(() => expect(pressed()).toEqual(["as text"]));
    return f;
  }
  /** The scope's answers; `hold` keeps those it names until `release`. */
  function serveHeld() {
    let revision = 1;
    let hold: ((at: string) => boolean) | null = null;
    const waiting: (() => void)[] = [];
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
        const at = q.get("at");
        const entries = at !== null ? ENTRIES.filter((e) => e.path === at) : ENTRIES;
        const answer = json({ draft_revision: revision, node: NODE_ID, field: "/condition", state: "ok", reason: null, entries, more: false, problem: null });
        return at !== null && hold?.(at) ? new Promise<Response>((done) => waiting.push(() => done(answer))) : answer;
      },
    });
    return {
      hold: (h: ((at: string) => boolean) | null) => void (hold = h),
      revise: (n: number) => void (revision = n),
      release: () => waiting.splice(0).forEach((go) => go()),
      waiting: () => waiting.length,
    };
  }

  it("closes a comparison's details when it's removed: the next one's never open in its place", async () => {
    showFields(IF, { steps, config: { condition: built([nameIs("a"), { ...nameIs("b"), path: `${OUT}.tz`, guards: [{ kind: "present", path: `${OUT}.tz`, size: null }] }]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    await userEvent.click(within(await screen.findByRole("dialog", { name: N })).getByRole("button", { name: "Remove" }));
    expect(screen.queryAllByRole("dialog")).toEqual([]);
  });

  it("closes a comparison's Replace tree when it's removed by its ×: a pick never replaces another", async () => {
    const f = showFields(IF, { steps, config: { condition: built([nameIs("a"), nameIs("b")]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    await userEvent.click(within(await screen.findByRole("dialog", { name: N })).getByRole("button", { name: "Replace…" }));
    await screen.findByRole("tree");
    await userEvent.click(screen.getByRole("button", { name: "Remove condition 1" }));
    expect(screen.queryAllByRole("tree")).toEqual([]);
    expect(f.config()).toEqual({ condition: built([nameIs("b")]) });
  });

  it("opens one tree at a time: ＋ Condition closes a Replace tree", async () => {
    showFields(IF, { steps, config: { condition: built([nameIs("a")]) } });
    await userEvent.click(await waitFor(() => pillOf("Condition 1")));
    await userEvent.click(within(await screen.findByRole("dialog", { name: N })).getByRole("button", { name: "Replace…" }));
    await screen.findByRole("tree");
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    expect(screen.getAllByRole("tree")).toHaveLength(1);
  });

  it("keeps \"as text / as number\", and the focus on it, while a save's answer comes; what's typed still follows", async () => {
    const api = serveHeld();
    const options = { steps, config: {} as Record<string, unknown>, revision: 1 };
    const f = showFields(IF, options);
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("any");
    await waitFor(() => expect(pressed()).toEqual(["as text"]));
    await userEvent.type(value(), "3");
    await userEvent.click(screen.getByRole("button", { name: "as number" })); // focus on it: the person's own pick
    api.revise(2);
    api.hold(() => true);
    options.revision = 2; // the save returns: the next revision's facts are asked
    f.replace(f.config());
    await waitFor(() => expect(api.waiting()).toBeGreaterThan(0));
    expect(screen.getByRole("group", { name: "Compare as, Condition 1" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "as number" }));
    api.release();
  });

  it("follows what's typed while a save's answer comes", async () => {
    const api = serveHeld();
    const options = { steps, config: {} as Record<string, unknown>, revision: 1 };
    const f = showFields(IF, options);
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("any");
    await waitFor(() => expect(pressed()).toEqual(["as text"]));
    await userEvent.type(value(), "3");
    api.revise(2);
    api.hold(() => true);
    options.revision = 2;
    f.replace(f.config());
    await waitFor(() => expect(api.waiting()).toBeGreaterThan(0));
    await userEvent.type(value(), "a");
    expect(f.config()).toEqual({ condition: formula(`(${A} == "3a")`) });
    expect(f.held()).toEqual([]);
    api.release();
  });

  it("follows what's typed once a new comparison's facts come, whatever was typed before them", async () => {
    const api = serveHeld();
    api.hold((at) => at === A);
    const f = showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("any");
    await screen.findByRole("textbox", { name: "Value, Condition 1" });
    await userEvent.type(value(), "4");
    api.hold(null);
    api.release();
    await waitFor(() => expect(screen.getByRole("group", { name: "Compare as, Condition 1" })).toBeTruthy());
    await userEvent.type(value(), "2");
    expect(f.config()).toEqual({ condition: formula(`(${A} == 42)`) });
  });

  it("keeps every space typed: a number followed by more text is text", async () => {
    const f = await anyIs();
    await userEvent.type(value(), "3 apples");
    expect(f.config()).toEqual({ condition: formula(`(${A} == "3 apples")`) });
    expect(value()).toHaveProperty("value", "3 apples");
  });

  it("keeps the kind the person picked through any typing", async () => {
    const f = await anyIs();
    await userEvent.type(value(), "3");
    await userEvent.click(screen.getByRole("button", { name: "as text" }));
    await userEvent.type(value(), "{Backspace}5");
    expect(f.config()).toEqual({ condition: formula(`(${A} == "5")`) });
  });

  it("keeps the kind between \"is\" and \"is not\"", async () => {
    const f = await anyIs();
    await userEvent.type(value(), "3");
    await userEvent.click(screen.getByRole("button", { name: "as text" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Comparison, Condition 1" }), "is_not");
    expect(f.config()).toEqual({ condition: formula(`(${A} != "3")`) });
  });

  it("keeps the kind written in a comparison read back, the value cleared and typed again", async () => {
    const f = showFields(IF, { steps, config: { condition: formula(`(${A} == "3")`) } });
    await waitFor(() => expect(pressed()).toEqual(["as text"]));
    await userEvent.clear(value());
    await userEvent.type(value(), "5");
    expect(f.config()).toEqual({ condition: formula(`(${A} == "5")`) });
  });
});
