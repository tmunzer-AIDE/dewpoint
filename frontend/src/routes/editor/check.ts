// SPDX-License-Identifier: Apache-2.0
// What the editor may say of its problems (4b ruling 24). A check is of one saved revision, and is current only while
// that revision is the saved one and nothing was edited since. Before the first answer it says nothing reassuring; a
// failed check says so; edits since a check make it stale. Steps carry badges only while it's current.
import type { SyncState } from "../../lib/draftSync";
import type { Validation } from "../../lib/workflows";

export type Check =
  | { status: "unchecked" }
  | { status: "checking"; last: Validation | null }
  | { status: "failed"; last: Validation | null }
  | { status: "done"; last: Validation };

export type CheckState = "unchecked" | "checking" | "failed" | "stale" | "current";

export function checkState(check: Check, sync: Pick<SyncState, "revision" | "generation" | "savedGeneration">): CheckState {
  if (check.status !== "done") return check.status;
  const onScreen = sync.generation === sync.savedGeneration && check.last.draft_revision === sync.revision;
  return onScreen ? "current" : "stale";
}

/** The newest answer, whatever its state. */
export const lastOf = (check: Check): Validation | null => (check.status === "unchecked" ? null : check.last);

/** The toolbar's words for a check, with the problems it found. */
export function checkLabel(state: CheckState, count: number): string {
  if (state === "unchecked") return "Not checked";
  if (state === "checking") return "Checking…";
  if (state === "failed") return "Check failed";
  if (state === "stale") return count ? `Problems · ${count}, before your edits` : "Not checked since your edits";
  return count ? `Problems · ${count}` : "No problems";
}
