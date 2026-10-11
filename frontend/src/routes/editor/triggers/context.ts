// SPDX-License-Identifier: Apache-2.0
// What the Triggers panel's parts share (4c-3b): the draft (or a version on view) and what may change. The input is the
// draft's, written through the editor's `change`, so it gets undo, saving, conflicts and the leave guard as a step's
// fields do; what's typed but can't be written yet is held by the editor (ruling 113). Schedules and webhooks are live
// rows the API writes at once, outside undo: `manage` is whether this person may (trigger.manage, editor and above).
import { createContext, useContext } from "react";
import type { Holding, Unapplied, UnappliedKind } from "../../../lib/unapplied";
import type { GraphDoc, Validation } from "../../../lib/workflows";

export interface PanelActions {
  /** Writes what `make` makes of the editor's latest draft (edits sharing a `mark` are one undo step); why it wasn't
   * written, or null. */
  update: (make: (draft: GraphDoc) => GraphDoc, said?: string | null, mark?: string) => string | null;
  held: (kind: UnappliedKind, pointer: string) => Unapplied | undefined;
  hold: (kind: UnappliedKind, pointer: string, holding: Holding) => void;
  release: (kind: UnappliedKind, pointer: string) => void;
  /** Applies what's held at `pointer` now: why it stays held, or null. */
  apply: (kind: UnappliedKind, pointer: string) => string | null;
  /** Whether what's held at `pointer` was typed over what has since changed (an undo, another edit): it's then never
   * written as it's typed, only by Apply here (ruling 18; the review of revision 1). */
  stale: (kind: UnappliedKind, pointer: string) => boolean;
  /** Takes what's at `pointer` now as what the held edit is typed over: Apply here, before it's applied. */
  rebase: (kind: UnappliedKind, pointer: string) => void;
  /** Discards what's held at `pointer` and below. */
  discard: (pointer: string) => void;
}

export interface Triggers {
  tenantId: string;
  workflowId: string;
  name: string;
  doc: GraphDoc; // the draft, or the version on view
  editable: boolean; // the draft's input can change now
  manage: boolean; // schedules and webhooks can change: the role may, and no version is on view
  viewer: boolean; // the role can't change triggers at all: said once, at the top
  activeNumber: number | null;
  activeVersionId: string | null;
  check: Validation | null; // the current check of the saved draft, or null: its problems show at their fields
  actions: PanelActions;
}

const CANT = "Not written: the draft can't be changed now.";

/** A version's view, or a role that can't edit: nothing is written, nothing held. */
export const READ_ONLY: PanelActions = {
  update: () => CANT,
  held: () => undefined,
  hold: () => undefined,
  release: () => undefined,
  apply: () => CANT,
  discard: () => undefined,
  stale: () => false,
  rebase: () => undefined,
};

export const TriggersContext = createContext<Triggers | null>(null);

export function useTriggers(): Triggers {
  const t = useContext(TriggersContext);
  if (!t) throw new Error("useTriggers is used outside the Triggers panel");
  return t;
}
