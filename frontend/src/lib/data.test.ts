// SPDX-License-Identifier: Apache-2.0
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DraftMoved, groupOf, previewAt, samplesQuery, scopeQuery, tagsOf, typeWords, whyMissing, type ScopeEntry } from "./data";

const entry = (over: Partial<ScopeEntry>): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: "name", nameable: true, nullable: false, parent: null, path: "steps.get_site.output.name", problem: null,
  root: "steps", sensitive: false, step: "00000000-0000-4000-8000-000000000002", types: ["string"], ...over,
});  // prettier-ignore

describe("the words for data", () => {
  it("says a type as the tree does", () => {
    expect(typeWords(entry({ types: ["string"] }))).toBe("text");
    expect(typeWords(entry({ types: ["string"], format: "date-time" }))).toBe("date and time");
    expect(typeWords(entry({ types: ["integer", "null"] }))).toBe("whole number");
    expect(typeWords(entry({ types: ["boolean"] }))).toBe("yes or no");
    expect(typeWords(entry({ types: ["array"] }))).toBe("list");
    expect(typeWords(entry({ types: [] }))).toBe("any value");
    expect(typeWords(entry({ types: ["null"] }))).toBe("always null");
    expect(typeWords(entry({ types: ["string", "integer"] }))).toBe("text or whole number");
  });

  it("tags what may be missing (dashed), what may be null and what's sensitive", () => {
    expect(tagsOf(entry({ missing: true, nullable: true, sensitive: true }))).toEqual([
      { text: "may be missing", conditional: true },
      { text: "may be null", conditional: false },
      { text: "sensitive", conditional: false },
    ]);
    expect(tagsOf(entry({}))).toEqual([]);
  });

  it("groups a step's data under its key and its type's title, and the rest by what they are", () => {
    const title = (k: string) => (k === "get_site" ? "Get a site" : null);
    expect(groupOf(entry({}), title)).toEqual({ key: "steps.get_site", title: "get_site", detail: "Get a site" });
    expect(groupOf(entry({ root: "trigger", path: "trigger.a" }), title).title).toBe("Trigger");
    expect(groupOf(entry({ root: "run", path: "run.now" }), title).title).toBe("This run");
    expect(groupOf(entry({ root: "loops", path: "loops.each.item" }), title)).toMatchObject({ key: "loops.each", title: "each" });
  });

  it("says why a value may be missing from its guards", () => {
    const e = entry({
      path: "steps.list.output.results[0].name",
      missing: true,
      formula: {
        guards: [
          { kind: "present", path: "steps.list.output", size: null },
          { kind: "min_size", path: "steps.list.output.results", size: 0 },
          { kind: "is_map", path: "steps.list.output.results[0]", size: null },
          { kind: "present", path: "steps.list.output.results[0].name", size: null },
        ],
        null_test: false,
        sensitive: false,
      },
    });
    expect(whyMissing(e)).toEqual([
      "list may not run",
      "steps.list.output.results may have fewer items",
      "steps.list.output.results[0] may be another kind of value",
      "it's optional in its data",
    ]);
    expect(whyMissing(entry({ root: "trigger", path: "trigger", types: [], missing: true, formula: null }))).toEqual([
      "the trigger's input isn't declared",
    ]);
  });
});

describe("a value in a sample's preview", () => {
  it("follows a path, and stops where the preview kept no value: redacted, truncated, kept apart, or absent", () => {
    const out = { results: [{ name: "ap-1" }, { $claim: "u1" }], token: "[redacted]", big: { $claim: "u2", pointer: "/x" } };
    expect(previewAt(out, ["results", 0, "name"])).toEqual({ value: "ap-1" });
    expect(previewAt(out, ["results", 1, "name"])).toEqual({ marker: "claimed" });
    expect(previewAt(out, ["big"])).toEqual({ marker: "claimed" });
    expect(previewAt(out, ["token"])).toEqual({ marker: "redacted" });
    expect(previewAt("[truncated]", ["results"])).toEqual({ marker: "truncated" });
    expect(previewAt(out, ["results", 5])).toEqual({ marker: "absent" });
    expect(previewAt(out, ["nope"])).toEqual({ marker: "absent" });
  });
});

describe("the questions asked of the saved draft", () => {
  it("asks each saved revision apart, so a newer revision asks again and never shows an older answer (D17)", () => {
    const where = { tenantId: "t", workflowId: "w", revision: 3, node: "n", field: "/message" };
    const top = scopeQuery(where, { kind: "top" }).queryKey;
    expect(scopeQuery({ ...where }, { kind: "top" }).queryKey).toEqual(top);
    expect(scopeQuery({ ...where, revision: 4 }, { kind: "top" }).queryKey).not.toEqual(top);
    expect(scopeQuery({ ...where, field: "/subject" }, { kind: "top" }).queryKey).not.toEqual(top);
    expect(scopeQuery(where, { kind: "at", path: "trigger.site" }).queryKey).not.toEqual(top);
    const step = { tenantId: "t", workflowId: "w", revision: 3, node: "n" };
    expect(samplesQuery({ ...step, revision: 4 }).queryKey).not.toEqual(samplesQuery(step).queryKey);
    expect(samplesQuery(step, "2").queryKey).not.toEqual(samplesQuery(step).queryKey);
  });
});

describe("the answers of the saved draft", () => {
  afterEach(() => vi.restoreAllMocks());
  const answering = (body: unknown) => vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body))));
  const where = { tenantId: "t", workflowId: "w", revision: 1, node: "n", field: "/message" };
  const step = { tenantId: "t", workflowId: "w", revision: 1, node: "n" };

  it("takes no answer about another revision than the one it asked of (the review of revision 1)", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const scope = { node: "n", field: "/message", state: "ok", reason: null, entries: [], more: false, problem: null };
    answering({ draft_revision: 2, ...scope });
    await expect(client.fetchQuery(scopeQuery(where, { kind: "top" }))).rejects.toBeInstanceOf(DraftMoved);
    answering({ draft_revision: 2, node: "n", sample: null, searched_runs: 0, search_limit: 200 });
    await expect(client.fetchQuery(samplesQuery(step))).rejects.toBeInstanceOf(DraftMoved);
    answering({ draft_revision: 1, ...scope });
    await expect(client.fetchQuery(scopeQuery(where, { kind: "top" }))).resolves.toMatchObject({ draft_revision: 1 });
  });
});
