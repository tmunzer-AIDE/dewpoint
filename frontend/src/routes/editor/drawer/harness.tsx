// SPDX-License-Identifier: Apache-2.0
// A step's fields on their own, for tests (4c-1): a one-step draft each write changes as the editor would, checked
// against the graph's admission (ruling 7), with the edits typed but not applied held beside it (ruling 18), and
// every write kept with its mark. A test may change the draft from outside (an undo), remount the fields (a drawer
// reopened) or refuse writes (an editor gone read only). An edit that takes ports away is refused here: the editor
// asks (Task 7). Imported by tests only: the build never reaches it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { admission, setConfig, setOptions, valueAt, type Changed, type StepOptions } from "../../../lib/config";
import { fieldsOf, type Path } from "../../../lib/schemaForm";
import {
  applyAll, applyUnapplied, baseOf, droppedWhy, isStale, lineageOf, unappliedId, within, type Unapplied, type UnappliedKind,
} from "../../../lib/unapplied";  // prettier-ignore
import type { Diagnostic, Expression, GraphDoc, NodeType } from "../../../lib/workflows";
import { DrawerContext, type Drawer } from "./context";
import { FieldView } from "./FieldView";

export const NODE_ID = "00000000-0000-4000-8000-000000000001";
export type Edit = { path: Path; value: unknown; mark: string | undefined };

interface Options {
  config?: Record<string, unknown>;
  options?: StepOptions;
  problems?: Diagnostic[];
  expressions?: Expression[];
  editable?: boolean;
}

interface State {
  doc: GraphDoc;
  held: ReadonlyMap<string, Unapplied>;
  refusing: string | null; // every write's answer while set: an editor gone read only under the controls
  redraw: () => void;
  mounts: number; // a new value remounts the fields, as reopening the drawer does
}

function Harness({ type, options, edits, state, children }: {
  type: NodeType; options: Options; edits: Edit[]; state: State; children: ReactNode;
}) {  // prettier-ignore
  const [, setVersion] = useState(0); // the draft and what's held live in `state`, which tests read; this redraws
  state.redraw = () => setVersion((v) => v + 1);
  const id = (kind: UnappliedKind, pointer: string) => unappliedId(NODE_ID, kind, pointer);
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
  const write = ({ doc, dropped }: Changed, release: string[] = []): string | null => {
    if (state.refusing !== null) return state.refusing;
    const refused = admission(doc);
    if (refused !== null) return refused;
    if (dropped.length > 0) return droppedWhy(dropped, doc);
    state.doc = doc;
    drop(release);
    return null;
  };
  const restructure: Drawer["restructure"] = (pointer, change) => {
    const { doc, applied, left } = applyAll(state.doc, state.held.values(), () => type, within(NODE_ID, pointer));
    for (const u of left) keep(u);
    if (left.length > 0) return left[0]!.why;
    let changed: Changed = { doc, dropped: [] };
    if (change) {
      const current = valueAt(doc.nodes![0]!.config ?? {}, change.path);
      const made = change.make(current);
      if (made !== current) changed = setConfig(doc, NODE_ID, change.path, made, type);
    }
    return changed.doc === state.doc ? null : write(changed, applied.map((u) => u.id));
  };
  const drawer: Drawer = {
    node: state.doc.nodes![0]!,
    type,
    editable: options.editable ?? true,
    tenantId: "t1",
    workflowId: "w1",
    problems: options.problems ?? [],
    expressions: options.expressions ?? [],
    set: (path, value, mark) => {
      edits.push({ path, value, mark });
      return write(setConfig(state.doc, NODE_ID, path, value, type));
    },
    options: (next) => write(setOptions(state.doc, NODE_ID, next, type)),
    held: (kind, pointer) => state.held.get(id(kind, pointer)),
    hold: (kind, pointer, holding) => {
      // What it's typed over is recorded when the edit begins, and kept while it's typed (the editor's way too).
      const was = state.held.get(id(kind, pointer));
      const u = { ...holding, id: id(kind, pointer), node: NODE_ID, kind, pointer, base: "", lineage: [] };
      keep({ ...u, base: was?.base ?? baseOf(state.doc, u), lineage: was?.lineage ?? lineageOf(state.doc, u) });
    },
    release: (kind, pointer) => drop([id(kind, pointer)]),
    discard: (pointer) => drop([...state.held.values()].filter(within(NODE_ID, pointer)).map((u) => u.id)),
    stale: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      return u !== undefined && isStale(state.doc, u);
    },
    rebase: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      if (u) keep({ ...u, base: baseOf(state.doc, u), lineage: lineageOf(state.doc, u), why: null });
    },
    apply: (kind, pointer) => {
      // A name moves its entry: what's typed inside it is applied first, or the name waits (the editor's way too).
      if (kind === "name") return restructure(pointer);
      const u = state.held.get(id(kind, pointer));
      if (!u) return null;
      const result = applyUnapplied(state.doc, u, type);
      const why = "problem" in result ? result.problem : write(result, [u.id]);
      if (why !== null) keep({ ...u, why });
      return why;
    },
    restructure,
  };
  return (
    <DrawerContext.Provider value={drawer}>
      <div key={state.mounts}>{children}</div>
    </DrawerContext.Provider>
  );
}

/** The type's fields, or `children`, in a drawer of one step. `config()`, `node()` and `held()` read what the edits
 * made of it. `replace` changes the draft from outside, as an undo does; `remount` reopens the fields; `refuse`
 * makes every write answer `why`, or none with null. */
export function showFields(type: NodeType, options: Options = {}, children?: ReactNode) {
  const edits: Edit[] = [];
  const state: State = {
    doc: {
      graph_format: 1,
      nodes: [{ id: NODE_ID, key: "step", type: type.ref, config: options.config ?? {}, ...(options.options ? { options: options.options } : {}) }],
    },
    held: new Map(),
    refusing: null,
    redraw: () => undefined,
    mounts: 0,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness type={type} options={options} edits={edits} state={state}>
        {children ?? fieldsOf(type).map((f) => <FieldView key={f.pointer} spec={f} />)}
      </Harness>
    </QueryClientProvider>,
  );
  const redraw = () => act(() => state.redraw());
  return {
    edits,
    config: () => state.doc.nodes![0]!.config ?? {},
    node: () => state.doc.nodes![0]!,
    held: () => [...state.held.values()],
    replace: (config: Record<string, unknown>) => {
      state.doc = { ...state.doc, nodes: [{ ...state.doc.nodes![0]!, config }] };
      redraw();
    },
    remount: () => {
      state.mounts++;
      redraw();
    },
    refuse: (why: string | null) => {
      state.refusing = why;
    },
    client,
  };
}

/** A problem the server found at a field of the step. */
export const problem = (field: string, message: string): Diagnostic => ({
  code: "config.invalid", severity: "error", message, fix: null, node: NODE_ID, field,
});  // prettier-ignore
