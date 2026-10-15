// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { GraphDoc } from "../../../lib/workflows";
import { changesOf, staleOf, staleWords } from "./stale";

const literal = (value: unknown) => ({ kind: "literal", value });
// The snapshot as the server stores it: canonical ids, every option written out (engine/graph/model.py).
const SNAPSHOT = {
  graph_format: 1,
  nodes: [
    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e01", key: "get_site", type: "mist.sites.get@1", config: { site: literal("HQ") }, position: { x: 0, y: 0 }, options: { timeout_s: null, max_attempts: null, on_error: "fail" } },
    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e02", key: "old_lookup", type: "flow.transform@1", config: {}, position: { x: 0, y: 80 }, options: { timeout_s: null, max_attempts: null, on_error: "fail" } },
    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e03", key: "notify", type: "slack.post@1", config: { text: literal("hi") }, position: { x: 0, y: 160 }, options: { timeout_s: null, max_attempts: 3, on_error: "fail" } },
    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e05", key: "report", type: "flow.transform@1", config: {}, position: { x: 0, y: 240 }, options: { timeout_s: null, max_attempts: null, on_error: "fail" } },
  ],
  edges: [],
} as unknown as GraphDoc;  // prettier-ignore
// The draft as the editor holds it: another spelling of an id, a step moved, options left out, one step's text changed,
// one step renamed, one removed, one added.
const DRAFT = {
  graph_format: 1,
  nodes: [
    { id: "{0B9F3C2E-1A2B-4C3D-8E4F-5A6B7C8D9E01}", key: "get_site", type: "mist.sites.get@1", config: { site: literal("HQ") }, position: { x: 300, y: 0 } },
    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e03", key: "notify", type: "slack.post@1", config: { text: literal("hello") }, options: { max_attempts: 3 } },
    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e05", key: "summary", type: "flow.transform@1", config: {} },
    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e04", key: "get_site_v2", type: "mist.sites.get@1", config: {} },
  ],
  edges: [],
} as unknown as GraphDoc;  // prettier-ignore
const id = (n: number) => `0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e0${n}`;

describe("a result before the person's edits (§7.7; the Stale board)", () => {
  it("is current while the draft is still the revision it ran, nothing unsaved", () => {
    expect(staleOf(14, { revision: 14, generation: 3, savedGeneration: 3 })).toBeNull();
  });

  it("is for an older revision once the draft moved on, and before unsaved edits as soon as there's one", () => {
    expect(staleOf(14, { revision: 16, generation: 5, savedGeneration: 5 })).toEqual({ kind: "revision", from: 14, to: 16 });
    expect(staleOf(14, { revision: 14, generation: 4, savedGeneration: 3 })).toEqual({ kind: "local" });
  });

  it("says so in the board's words, the panel adding what to do", () => {
    expect(staleWords({ kind: "revision", from: 14, to: 16 }, false)).toBe("this result is for revision 14; the draft is at revision 16.");
    expect(staleWords({ kind: "revision", from: 14, to: 16 }, true)).toBe("this result is for revision 14; the draft is at revision 16. Simulate again to see the draft as it is.");
    expect(staleWords({ kind: "local" }, false)).toBe("you've changed the draft since this result, and those changes aren't saved yet.");
  });

  it("finds the steps changed since, new since and gone, by identity, never by a move or an option's default", () => {
    const c = changesOf(SNAPSHOT, DRAFT);
    expect([...c.changed]).toEqual([id(3), id(5)]); // notify's text; report renamed summary
    expect([...c.added]).toEqual([id(4)]);
    expect([...c.gone]).toEqual([id(2)]);
  });
});
