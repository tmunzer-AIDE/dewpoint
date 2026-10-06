// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConflictError, DraftSync, SaveError, type Saved, type SyncState } from "./draftSync";
import type { GraphDoc } from "./workflows";

const doc = (n: number): GraphDoc => ({ graph_format: 1, nodes: [{ id: `n${n}`, key: `k${n}`, type: "flow.transform@1" }], edges: [] });
type Answer = () => Promise<Saved>;

let calls: { doc: GraphDoc; revision: number }[];
let inFlight: number;
let maxInFlight: number;
let answers: Answer[];
let states: SyncState["status"][];
let settled: number[];

/** A save's answer, as the API gives it: the next revision, its hash, and the version it was compared with. */
const saved = (revision: number, active: number | null = null): Saved => ({
  draft_revision: revision, unpublished_changes: true, graph_hash: `h${revision}`, active_version_id: active ? `v${active}` : null,
  active_version_number: active,
});  // prettier-ignore

function make() {
  return new DraftSync({
    revision: 1,
    unpublished: true,
    savedHash: "h1",
    activeNumber: null,
    delayMs: 1000,
    save: async (d, revision) => {
      calls.push({ doc: d, revision });
      inFlight++;
      maxInFlight = Math.max(maxInFlight, inFlight);
      try {
        return await (answers.shift() ?? (() => Promise.resolve(saved(revision + 1))))();
      } finally {
        inFlight--;
      }
    },
    onChange: (s) => states.push(s.status),
    onSettled: (r) => settled.push(r),
  });
}

/** A save that answers when the test says. */
function held(): () => void {
  let release!: () => void;
  answers.push(() => new Promise((r) => (release = () => r(saved(2)))));
  return () => release();
}

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  inFlight = 0;
  maxInFlight = 0;
  answers = [];
  states = [];
  settled = [];
});
afterEach(() => vi.useRealTimers());

it("saves a second after the last change, with the revision the last save returned", async () => {
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(500);
  sync.change(doc(2)); // within the second: coalesced
  await vi.advanceTimersByTimeAsync(999);
  expect(calls).toEqual([]);
  await vi.advanceTimersByTimeAsync(1);
  expect(calls).toEqual([{ doc: doc(2), revision: 1 }]);
  expect(sync.current).toEqual({
    status: "saved", revision: 2, unpublished: true, generation: 2, savedGeneration: 2, savedHash: "h2", activeNumber: null,
  });  // prettier-ignore
  expect(settled).toEqual([2]);
});

it("takes the active version and the hash from each save's answer", async () => {
  answers.push(() => Promise.resolve(saved(2, 3))); // version 3 became active elsewhere before this save landed
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect([sync.current.activeNumber, sync.current.savedHash]).toEqual([3, "h2"]);
});

it("edits during a save coalesce into exactly one next save, never two at once", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  sync.change(doc(2));
  sync.change(doc(3));
  await vi.advanceTimersByTimeAsync(5000);
  expect(calls.length).toBe(1); // still in flight: nothing else goes
  release();
  await vi.advanceTimersByTimeAsync(1000);
  expect(calls.map((c) => [c.doc, c.revision])).toEqual([[doc(1), 1], [doc(3), 2]]);
  expect(maxInFlight).toBe(1);
  expect(settled).toEqual([3]); // settled once, when nothing was left to save
});

it("counts each change, and says which one the server holds", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  expect([sync.current.generation, sync.current.savedGeneration, sync.unsaved]).toEqual([1, 0, true]);
  await vi.advanceTimersByTimeAsync(1000); // generation 1 goes
  sync.change(doc(2));
  release();
  await vi.advanceTimersByTimeAsync(0);
  expect([sync.current.generation, sync.current.savedGeneration, sync.unsaved]).toEqual([2, 1, true]);
  await vi.advanceTimersByTimeAsync(1000);
  expect([sync.current.generation, sync.current.savedGeneration, sync.unsaved]).toEqual([2, 2, false]);
});

it("a 409 stops every save and keeps the document", async () => {
  answers.push(() => Promise.reject(new ConflictError()));
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect(sync.current.status).toBe("conflict");
  expect(sync.unsaved).toBe(true); // what leaving would lose
  sync.change(doc(2));
  await vi.advanceTimersByTimeAsync(5000);
  expect(calls.length).toBe(1);
  await expect(sync.flush()).rejects.toBeInstanceOf(ConflictError);
});

it("a conflict declared during a save stays a conflict when that save answers", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  sync.change(doc(2));
  sync.conflict(); // a publish's 409
  release();
  await vi.advanceTimersByTimeAsync(5000);
  expect(sync.current.status).toBe("conflict");
  expect(calls.length).toBe(1);
});

it("a failed save keeps the document for the next change or a retry, at the same revision", async () => {
  answers.push(() => Promise.reject(new Error("network")));
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect(sync.current.status).toBe("error");
  sync.retry();
  await vi.advanceTimersByTimeAsync(0);
  expect(calls.map((c) => [c.doc, c.revision])).toEqual([[doc(1), 1], [doc(1), 1]]);
  expect(sync.current.status).toBe("saved");
});

it("flush saves now what's pending, and answers the revision publish must name", async () => {
  const sync = make();
  sync.change(doc(1));
  const flushed = sync.flush();
  await vi.advanceTimersByTimeAsync(0);
  await expect(flushed).resolves.toBe(2);
  expect(calls.length).toBe(1);
  await expect(sync.flush()).resolves.toBe(2); // nothing pending: no save
  expect(calls.length).toBe(1);
});

it("flush says when the draft couldn't be saved, after trying once more", async () => {
  answers.push(() => Promise.reject(new Error("network")), () => Promise.reject(new Error("network")));
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  const flushed = expect(sync.flush()).rejects.toBeInstanceOf(SaveError);
  await vi.advanceTimersByTimeAsync(0);
  await flushed;
  expect(calls.length).toBe(2);
});

it("once closed, a save in flight that answers sends nothing more and says nothing", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  sync.change(doc(2)); // waits for the save in flight
  sync.dispose();
  const said = states.length;
  release();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(calls.length).toBe(1);
  expect(states.length).toBe(said);
  expect(settled).toEqual([]);
  await expect(sync.flush()).rejects.toBeInstanceOf(SaveError);
});

it("takes publish's word only for the revision it published", async () => {
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000); // revision 2
  sync.published(1, 4); // not the revision saved now: version 4 is active, the comparison isn't known
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([4, null]);
  sync.published(2, 5);
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([5, false]);
});

it("takes a read's active version, and its comparison only for the revision it read", () => {
  const sync = make();
  sync.compared({ draft_revision: 1, unpublished_changes: false, active_version_number: 2 });
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([2, false]);
  sync.compared({ draft_revision: 9, unpublished_changes: false, active_version_number: 3 }); // another revision's
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([3, null]);
});

it("says what it doesn't know after an activation or a lost answer", () => {
  const sync = make();
  sync.activated(2);
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([2, null]);
  sync.lostTrack();
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual(["unknown", null]);
});
