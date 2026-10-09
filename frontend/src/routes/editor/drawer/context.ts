// SPDX-License-Identifier: Apache-2.0
// What a step drawer's fields share (4c-1): the step, its type, whether it may be edited, the server's problems and
// formulas for it; what they may do to the draft, through the editor, which owns the document and the edits typed but
// not applied (ruling 18); which problems a field shows (D19); and focus sessions (ruling 8).
import { createContext, useContext, useRef, type FocusEvent } from "react";
import type { StepOptions } from "../../../lib/config";
import { pointerOf, type Path } from "../../../lib/schemaForm";
import type { Holding, Unapplied, UnappliedKind } from "../../../lib/unapplied";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";

/** What a drawer may do to its step. Each write answers why nothing was written, or null. */
export interface DrawerActions {
  /** Writes `value` at `path` in the step's config (undefined removes it); edits sharing a mark are one undo step. */
  set: (path: Path, value: unknown, mark?: string) => string | null;
  /** Writes the step's options: what a failure does, its attempts and its timeout. */
  options: (options: StepOptions, mark?: string) => string | null;
  /** What's typed for a field but not in the draft (ruling 18), by its kind and pointer. */
  held: (kind: UnappliedKind, pointer: string) => Unapplied | undefined;
  hold: (kind: UnappliedKind, pointer: string, holding: Holding) => void;
  release: (kind: UnappliedKind, pointer: string) => void;
  /** Drops every unapplied edit at `pointer` and below, on purpose: what Clear does. */
  discard: (pointer: string) => void;
  /** Applies what's typed for a field now: when focus leaves it, on Enter. */
  apply: (kind: UnappliedKind, pointer: string) => string | null;
  /** Whether what an edit was typed over has changed since (an undo, another edit): it's then never applied unasked. */
  stale: (kind: UnappliedKind, pointer: string) => boolean;
  /** "Apply here": the edit is taken as typed over what's there now. */
  rebase: (kind: UnappliedKind, pointer: string) => void;
  /** Applies every unapplied edit at `pointer` and below; then, with `change`, writes what `make` makes of the value
   * at `path`, as one undo step. An edit that can't be applied stops it, its control saying why. */
  restructure: (pointer: string, change?: { path: Path; make: (current: unknown) => unknown }) => string | null;
}

export interface Drawer extends DrawerActions {
  node: GraphNode;
  type: NodeType | undefined;
  editable: boolean;
  tenantId: string;
  workflowId: string;
  problems: Diagnostic[]; // the step's, from a current check
  expressions: Expression[]; // how its formulas run
}

export const DrawerContext = createContext<Drawer | null>(null);

export function useDrawer(): Drawer {
  const drawer = useContext(DrawerContext);
  if (!drawer) throw new Error("A step's field is shown only in its drawer");
  return drawer;
}

/** A name as one segment of a JSON pointer. */
export const segment = (name: string): string => pointerOf([name]).slice(1);

/** The problems a field shows: those at its pointer; those below it, when it shows nothing below (a scalar, a formula,
 * JSON: `shown` is null); or, for a group, a list or a map showing its parts, those below it in a part it doesn't
 * show. */
export function problemsAt(all: Diagnostic[], pointer: string, shown: ReadonlySet<string> | null): Diagnostic[] {
  return all.filter((d) => {
    if (d.field === null) return false;
    if (d.field === pointer) return true;
    if (!d.field.startsWith(`${pointer}/`)) return false;
    return shown === null || !shown.has(d.field.slice(pointer.length + 1).split("/")[0]!);
  });
}

let sessions = 0;

/** Focus entering an element starts a session: what's typed in it until focus leaves is one undo step (ruling 8). */
export function useSession(prefix: string): { mark: () => string; onFocus: (e: FocusEvent<HTMLElement>) => void } {
  const session = useRef(0);
  return {
    mark: () => `${prefix}#${session.current}`,
    onFocus: (e) => {
      if (!e.currentTarget.contains(e.relatedTarget)) session.current = ++sessions;
    },
  };
}
