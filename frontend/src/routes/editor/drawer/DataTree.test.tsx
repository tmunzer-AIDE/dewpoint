// SPDX-License-Identifier: Apache-2.0
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ScopeEntry } from "../../../lib/data";
import { typeWith } from "../../../test/nodeTypes";
import { DataTree } from "./DataTree";
import { fakeApi, json, NODE_ID, showFields } from "./harness";

const NOTE = typeWith({ type: "object", properties: { message: { type: "string" } } }, { ref: "acme.note@1", type: "acme.note", title: "Post a note" });
const SITE = "00000000-0000-4000-8000-000000000002";
const steps = [
  { id: NODE_ID, key: "step", title: "Post a note" },
  { id: SITE, key: "list", title: "List devices" },
];

const entry = (path: string, over: Partial<ScopeEntry> = {}): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: path.split(".").at(-1)!, nameable: true, nullable: false, parent: null, path, problem: null, root: "steps",
  sensitive: false, step: SITE, types: ["string"], ...over,
});  // prettier-ignore

const OUT = "steps.list.output";
const ENTRIES = [
  entry("trigger", { root: "trigger", step: null, types: ["object"], sensitive: true }), // undeclared: nothing to browse
  entry(OUT, { name: "output", types: ["object"], children: true }),
  entry(`${OUT}.results`, { parent: OUT, types: ["array"], children: true }),
  entry(`${OUT}.results[0]`, { parent: `${OUT}.results`, name: "[0]", types: ["string"], missing: true }), // text: an object can't go into text
  entry(`${OUT}.total`, { parent: OUT, types: ["integer", "null"], nullable: true }),
  entry(`${OUT}.dash-key`, { parent: OUT, nameable: false }),
  entry("run.now", { root: "run", step: null, name: "now", format: "date-time" }),
];

function answer(entries: ScopeEntry[], more = false) {
  return json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries, more, problem: null });
}

function serve(over: Record<string, (q: URLSearchParams) => Response> = {}) {
  return fakeApi({
    "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
      const under = q.get("under");
      const find = q.get("find");
      const at = q.get("at");
      if (at !== null) {
        return at === "trigger.events[0].ap"
          ? answer([entry(at, { root: "trigger", step: null, types: [], missing: true, sensitive: true })])
          : json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [], more: false, problem: { code: "ref.unknown_field", severity: "error", message: "No such field.", fix: null, node: NODE_ID, field: "/message" } });
      }
      if (under !== null) return answer(ENTRIES.filter((e) => e.parent === under));
      if (find !== null) return answer(ENTRIES.filter((e) => e.name.includes(find)));
      return answer(ENTRIES.filter((e) => e.parent === null || e.parent === OUT));
    },
    ...over,
  });
}

afterEach(() => vi.restoreAllMocks());

function tree(onPick = vi.fn(), onClose = vi.fn(), purpose: "text" | "condition" = "text") {
  showFields(NOTE, { steps }, <DataTree field="/message" purpose={purpose} onPick={onPick} onClose={onClose} />);
  return { onPick, onClose };
}

describe("the data tree", () => {
  it("groups the data by where it comes from, each value with its tags and type", async () => {
    serve();
    tree();
    const t = await screen.findByRole("tree", { name: "Data available here" });
    const groups = within(t).getAllByRole("treeitem").filter((g) => g.getAttribute("aria-level") === "1");
    expect(groups.map((g) => g.firstChild?.textContent)).toEqual(["Trigger", "list · List devices", "This run"]);
    expect(within(t).getByText("total").closest("li")?.textContent).toContain("may be null");
    expect(within(t).getByText("total").closest("li")?.textContent).toContain("whole number");
  });

  it("moves with the arrows, opens a value's children with →, and inserts with Enter", async () => {
    serve();
    const { onPick } = tree();
    await screen.findByRole("tree");
    await userEvent.keyboard("{ArrowDown}"); // from the search, into the tree
    expect(document.activeElement?.textContent?.startsWith("Trigger")).toBe(true);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}"); // the trigger's path, list, results
    expect((document.activeElement as HTMLElement).dataset.path).toBe(`${OUT}.results`);
    await userEvent.keyboard("{ArrowRight}");
    await screen.findByText("[0]");
    await userEvent.keyboard("{ArrowRight}");
    expect((document.activeElement as HTMLElement).dataset.path).toBe(`${OUT}.results[0]`);
    await userEvent.keyboard("{Enter}");
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ path: `${OUT}.results[0]` }));
  });

  it("opens an object that's always there in a condition, but never picks it: it has nothing to compare (the review of revision 1)", async () => {
    const SITE_OBJ = `${OUT}.site`;
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) =>
        q.get("under") === SITE_OBJ
          ? answer([entry(`${SITE_OBJ}.name`, { parent: SITE_OBJ })])
          : answer([entry(OUT, { name: "output", types: ["object"], children: true }), entry(SITE_OBJ, { parent: OUT, types: ["object"], children: true })]),
    });
    const { onPick } = tree(vi.fn(), vi.fn(), "condition");
    const row = (await screen.findByText("site")).closest("li")!;
    expect(row.getAttribute("aria-disabled")).toBe("true");
    expect(row.textContent).toContain("It's always there, so there's nothing to compare: open it and pick one of its values.");
    await userEvent.click(row);
    expect(onPick).not.toHaveBeenCalled();
    expect(row.getAttribute("aria-expanded")).toBe("true");
  });

  it("says so when the draft was saved again while its data was asked for, and shows none of it (the review of revision 1)", async () => {
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 2, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: ENTRIES, more: false, problem: null }),
    });
    tree();
    expect(await screen.findByText("The draft was saved again while its data was asked for. Close this and open it again.")).toBeTruthy();
    expect(screen.queryByText("total")).toBeNull();
  });

  it("says so when an opened value's answer is about a newer revision, and shows none of it (the review of revision 2)", async () => {
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
        const under = q.get("under");
        if (under === null) return answer(ENTRIES.filter((e) => e.parent === null || e.parent === OUT));
        return json({ draft_revision: 2, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: ENTRIES.filter((e) => e.parent === under), more: false, problem: null });
      },
    });
    tree();
    const results = (await screen.findByText("results")).closest("li")!;
    await userEvent.click(results); // a list can't go into text: it opens
    expect(await within(results).findByText("The draft was saved again while its data was asked for. Close this and open it again.")).toBeTruthy();
    expect(within(results).queryByText("[0]")).toBeNull();
  });

  it("shows a key a reference can't name, disabled, and never inserts it", async () => {
    serve();
    const { onPick } = tree();
    const row = (await screen.findByText("dash-key")).closest("li")!;
    expect(row.getAttribute("aria-disabled")).toBe("true");
    expect(row.textContent).toContain("A reference can't name this key.");
    await userEvent.click(row);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("finds values by name", async () => {
    const sent = serve();
    tree();
    await userEvent.type(await screen.findByRole("searchbox", { name: "Find data" }), "tot");
    await waitFor(() => expect(screen.queryByText("run")).toBeNull());
    expect(screen.getByText("total")).toBeTruthy();
    expect(sent.some((r) => r.path.endsWith("/draft/scope"))).toBe(true);
  });

  it("takes a typed path in a trigger whose input isn't declared, once the server finds it", async () => {
    serve();
    const { onPick } = tree();
    const path = await screen.findByRole("textbox", { name: "A path in the trigger" });
    await userEvent.clear(path);
    await userEvent.type(path, "trigger.nope");
    await userEvent.click(screen.getByRole("button", { name: "Insert" }));
    expect(await screen.findByText("No such field.")).toBeTruthy();
    await userEvent.clear(path);
    await userEvent.type(path, "trigger.events[[0].ap"); // "[[" types "[" (user-event's keys)
    await userEvent.click(screen.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ path: "trigger.events[0].ap" })));
  });

  it("says why there's no data when the saved draft can't give any", async () => {
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "unavailable", reason: "This step isn't in the saved draft yet.", entries: [], more: false, problem: null }),
    });
    tree();
    expect(await screen.findByText("This step isn't in the saved draft yet.")).toBeTruthy();
  });

  it("closes with Escape without closing the drawer", async () => {
    serve();
    const { onClose } = tree();
    const outer = vi.fn();
    document.addEventListener("keydown", outer);
    await screen.findByRole("tree");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
    expect(outer).not.toHaveBeenCalled();
    document.removeEventListener("keydown", outer);
  });

  it("shows a root's fields in its group, and a root without any by the last part of its path (as the API names them)", async () => {
    const roots = [
      entry("trigger", { root: "trigger", step: null, name: "trigger", types: ["object"], sensitive: true, children: true }),
      entry("trigger.site", { root: "trigger", step: null, name: "site", parent: "trigger" }),
      entry("run.now", { root: "run", step: null, name: "run.now", format: "date-time" }),
    ];
    serve({ "GET /api/v1/t/t1/workflows/w1/draft/scope": () => answer(roots) });
    tree();
    const t = await screen.findByRole("tree");
    const rows = within(t).getAllByRole("treeitem").filter((r) => r.getAttribute("aria-level") === "2");
    expect(rows.map((r) => r.querySelector(".font-mono")?.textContent)).toEqual(["site", "now"]);
    expect(screen.queryByRole("textbox", { name: "A path in the trigger" })).toBeNull(); // declared: browsed, not typed
  });
});
