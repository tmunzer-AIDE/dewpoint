// SPDX-License-Identifier: Apache-2.0
// The Triggers panel on its own, for tests (4c-3b): a draft each write changes as the editor would (the graph's
// admission, a CSV declaration a save takes), the edits held beside it (ruling 113), every write kept with its mark and
// what it said, and a router for its links. The API is faked with the drawer harness's `fakeApi`. Imported by tests
// only: the build never reaches it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { admission } from "../../../lib/config";
import { csvProblem } from "../../../lib/csv";
import { applyAll, applyUnapplied, baseOf, isStale, lineageOf, TRIGGERS, unappliedId, within, type Unapplied, type UnappliedKind } from "../../../lib/unapplied";
import type { GraphDoc, Validation } from "../../../lib/workflows";
import type { PanelActions, Triggers } from "./context";
import { TriggersPanel } from "./TriggersPanel";

export type Write = { mark: string | undefined; said: string | null };

interface Options {
  doc?: GraphDoc;
  editable?: boolean;
  manage?: boolean;
  viewer?: boolean;
  activeNumber?: number | null;
  activeVersionId?: string | null;
  check?: Validation | null;
  focusAt?: { pointer: string; n: number } | null;
}

interface State {
  doc: GraphDoc;
  held: ReadonlyMap<string, Unapplied>;
  refusing: string | null;
  redraw: () => void;
}

function Harness({ options, state, writes }: { options: Options; state: State; writes: Write[] }) {
  const [, setVersion] = useState(0);
  state.redraw = () => setVersion((v) => v + 1);
  const id = (kind: UnappliedKind, pointer: string) => unappliedId(TRIGGERS, kind, pointer);
  const keep = (u: Unapplied) => {
    state.held = new Map(state.held).set(u.id, u);
    state.redraw();
  };
  const drop = (ids: string[]) => {
    const next = new Map(state.held);
    for (const each of ids) next.delete(each);
    state.held = next;
    state.redraw();
  };
  const write = (next: GraphDoc, release: string[] = []): string | null => {
    if (state.refusing !== null) return state.refusing;
    const refused = admission(next) ?? csvProblem(next.settings?.csv);
    if (refused !== null) return refused;
    state.doc = next;
    drop(release);
    return null;
  };
  const actions: PanelActions = {
    update: (make, said = null, mark) => {
      const next = make(state.doc);
      if (next === state.doc) return null;
      writes.push({ mark, said });
      return write(next);
    },
    held: (kind, pointer) => state.held.get(id(kind, pointer)),
    hold: (kind, pointer, holding) => {
      const was = state.held.get(id(kind, pointer));
      const u: Unapplied = { ...holding, id: id(kind, pointer), node: TRIGGERS, kind, pointer, base: "", lineage: [] };
      keep({ ...u, base: was?.base ?? baseOf(state.doc, u), lineage: was?.lineage ?? lineageOf(state.doc, u) });
    },
    release: (kind, pointer) => drop([id(kind, pointer)]),
    apply: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      if (!u) return null;
      if (kind === "name") {
        // What's typed inside the field is applied first, or the name waits (the editor's way too).
        const { doc, applied, left } = applyAll(state.doc, state.held.values(), () => undefined, within(TRIGGERS, pointer));
        for (const l of left) keep(l);
        if (left.length > 0) return left[0]!.why;
        return write(doc, applied.map((a) => a.id));
      }
      const result = applyUnapplied(state.doc, u, undefined);
      const why = "problem" in result ? result.problem : write(result.doc, [u.id]);
      if (why !== null) keep({ ...u, why });
      return why;
    },
    discard: (pointer) => drop([...state.held.values()].filter(within(TRIGGERS, pointer)).map((u) => u.id)),
    stale: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      return u !== undefined && isStale(state.doc, u);
    },
    rebase: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      if (u) keep({ ...u, base: baseOf(state.doc, u), lineage: lineageOf(state.doc, u), why: null });
    },
  };
  const editable = options.editable ?? true;
  const value: Triggers = {
    tenantId: "t1", workflowId: "w1", name: "AP report", doc: state.doc, editable, manage: options.manage ?? editable,
    viewer: options.viewer ?? false, activeNumber: options.activeNumber === undefined ? 3 : options.activeNumber,
    activeVersionId: options.activeVersionId === undefined ? "v3" : options.activeVersionId, check: options.check ?? null, actions,
  };  // prettier-ignore
  return <TriggersPanel value={value} focusAt={options.focusAt ?? null} onClose={() => undefined} />;
}

/** The Triggers panel over a draft, once drawn. `settings()` and `held()` read what the edits made of it; `replace` changes the
 * draft from outside, as an undo does; `refuse` makes every write answer `why`, or none with null. */
export async function showPanel(options: Options = {}) {
  const writes: Write[] = [];
  const state: State = { doc: options.doc ?? { graph_format: 1, nodes: [], edges: [] }, held: new Map(), refusing: null, redraw: () => undefined };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRootRoute();
  const page = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => (
      <QueryClientProvider client={client}>
        <Harness options={options} state={state} writes={writes} />
      </QueryClientProvider>
    ),
  });
  render(<RouterProvider router={createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ["/"] }) })} />);
  await screen.findByRole("heading", { name: "Triggers" }); // the router draws it a moment later
  return {
    writes,
    client,
    settings: () => state.doc.settings,
    held: () => [...state.held.values()],
    replace: (doc: GraphDoc) => {
      state.doc = doc;
      act(() => state.redraw());
    },
    refuse: (why: string | null) => {
      state.refusing = why;
    },
  };
}
