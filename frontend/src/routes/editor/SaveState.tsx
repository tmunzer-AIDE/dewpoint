// SPDX-License-Identifier: Apache-2.0
// The draft's state, in words, beside the workflow's name (1c's "Saved"): never a colour alone, and never a claim
// the editor can't back. The active version and the comparison come from one state, so from one answer: `unpublished`
// is null when the comparison isn't known, `activeNumber` "unknown" when the active version isn't.
import type { SyncState } from "../../lib/draftSync";

export function SaveState({ state }: { state: SyncState }) {
  const active = state.activeNumber;
  const text =
    state.status === "pending" ? "Unsaved changes"
    : state.status === "saving" ? "Saving…"
    : state.status === "error" ? "Not saved"
    : state.status === "conflict" ? "Changed elsewhere"
    : active === "unknown" ? "Saved · the active version isn't known"
    : active === null ? "Saved · not published"
    : state.unpublished === null ? `Saved · v${active} is active`
    : state.unpublished ? `Saved · unpublished changes since v${active}`
    : `Saved · published as v${active}`;  // prettier-ignore
  const tone = state.status === "error" || state.status === "conflict" ? "text-danger" : state.status === "saved" ? "text-ok" : "text-muted";
  return <span className={`text-small ${tone}`}>{text}</span>;
}
