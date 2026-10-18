// SPDX-License-Identifier: Apache-2.0
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { item } from "../test/runs";
import {
  PAGE, canCancel, cancelRun, cursorOf, isEnded, listed, paramsOf, runsQuery, searchOf, validateRunsSearch, type RunItem,
} from "./runs";  // prettier-ignore

const at = (minute: number) => `2026-10-16T10:${String(minute).padStart(2, "0")}:00Z`;
/** A full first page, newest first: minutes 59 down. */
const firstPage = (from = 59) => Array.from({ length: PAGE }, (_, i) => item(`n${from - i}`, at(from - i)));

let sent: URL[];
beforeEach(() => {
  sent = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const request = input as Request;
    sent.push(new URL(request.url));
    const answer = request.method === "POST" ? { cancel: "requested", request: { id: "r1", status: "starting" } } : [];
    return Promise.resolve(new Response(JSON.stringify(answer)));
  });
});
afterEach(() => vi.restoreAllMocks());

describe("the Runs page's filters, in the address (the runs design §5.1, §5.2)", () => {
  it("reads each filter from the address, keeping only a value it allows", () => {
    expect(validateRunsSearch({ workflow: "w1", status: "failed", trigger: "rerun", mode: "drafts", started: "7d" })).toEqual({
      workflow: "w1", status: "failed", trigger: "rerun", mode: "drafts", started: "7d",
    });  // prettier-ignore
    expect(validateRunsSearch({ status: "awaiting_approval", trigger: "dev", mode: "all", started: "1y", workflow: 3 })).toEqual({});
  });

  it("writes only the filters that aren't their default, so the plain list has a plain address", () => {
    expect(searchOf({ mode: "both", started: "24h" })).toEqual({});
    expect(searchOf({ workflow: "w1", status: "running", mode: "live", started: "all" })).toEqual({
      workflow: "w1", status: "running", mode: "live", started: "all",
    });  // prettier-ignore
  });

  it("asks the API for what each filter means, the start of its window counted from now", () => {
    const now = Date.parse("2026-10-16T12:00:00Z");
    expect(paramsOf({}, now)).toEqual({ draft: "exclude", since: "2026-10-15T12:00:00.000Z" });
    expect(paramsOf({ mode: "live", started: "1h" }, now)).toEqual({ mode: "live", draft: "exclude", since: "2026-10-16T11:00:00.000Z" });
    expect(paramsOf({ mode: "simulated", started: "30d" }, now)).toEqual({ mode: "simulate", draft: "exclude", since: "2026-09-16T12:00:00.000Z" });
    expect(paramsOf({ mode: "drafts", started: "all", status: "didnt_start", trigger: "schedule", workflow: "w1" }, now)).toEqual({
      draft: "only", status: "didnt_start", source: "schedule", workflow_id: "w1",
    });  // prettier-ignore
    expect(paramsOf({ mode: "everything", started: "all" }, now)).toEqual({ draft: "include" });
  });
});

describe("reading the list (§5.2)", () => {
  it("reads a page of runs, newest first, after a cursor when one is given", async () => {
    await new QueryClient().query(runsQuery("t1", { status: "failed", started: "all" }, { before: at(1), before_id: "n1" }));
    const url = sent[0]!;
    expect(url.pathname).toBe("/api/v1/t/t1/runs");
    expect(Object.fromEntries(url.searchParams)).toEqual({ status: "failed", draft: "exclude", before: at(1), before_id: "n1", limit: String(PAGE) });
  });

  it("lists the first page alone when it holds every match: a run read earlier and gone from it no longer matches", () => {
    const first = [item("a", at(5)), item("b", at(4))];
    expect(listed(first, [item("c", at(3)), item("x", at(4), { status: "running" })]).map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("keeps the runs read earlier that sort after a full first page, each once, newest first", () => {
    const first = firstPage(); // n59 … n10
    const earlier = [item("n12", at(12), { status: "running" }), item("n9", at(9)), item("n8", at(8)), item("n9", at(9), { status: "failed" }), item("n7", at(7))];
    const shown = listed(first, earlier);
    expect(shown.map((i) => i.id)).toEqual([...first.map((i) => i.id), "n9", "n8", "n7"]);
    expect(shown.find((i) => i.id === "n12")!.status).toBe("succeeded"); // the first page's read wins
    expect(shown.find((i) => i.id === "n9")!.status).toBe("failed"); // the later of two earlier reads
  });

  it("drops a run read earlier that sorts within the first page and isn't on it any more", () => {
    const earlier = [item("gone", at(30), { status: "running" })];
    expect(listed(firstPage(), earlier).some((i) => i.id === "gone")).toBe(false);
  });

  it("pages on from the last run listed, and not past one with no queue time", () => {
    expect(cursorOf([item("a", at(5)), item("b", at(4))])).toEqual({ before: at(4), before_id: "b" });
    expect(cursorOf([item("a", at(5)), item("old", null)])).toBeNull();
    expect(cursorOf([])).toBeNull();
  });
});

describe("a run's end and its cancel (§5.3)", () => {
  it("knows an ended run from one still going", () => {
    expect(["queued", "starting", "running"].map((s) => isEnded(s as RunItem["status"]))).toEqual([false, false, false]);
    expect(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"].every((s) => isEnded(s as RunItem["status"]))).toBe(true);
  });

  it("cancels through the run's own route, answering what the server did", async () => {
    expect((await cancelRun("t1", "r1")).cancel).toBe("requested");
    expect(sent[0]!.pathname).toBe("/api/v1/t/t1/runs/r1/cancel");
  });

  it("shows Cancel to the roles that hold run.cancel: operators and up", () => {
    expect(["viewer", "operator", "editor", "admin", "owner", undefined].map(canCancel)).toEqual([false, true, true, true, true, false]);
  });
});
