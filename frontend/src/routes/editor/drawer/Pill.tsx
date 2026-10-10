// SPDX-License-Identifier: Apache-2.0
// A data pill (4c-2b; 1c's pill grammar, the 4c-2 mockups): what a reference reads, as a round mono button, dashed when
// its value may be missing (ruling 115), and what the saved draft's scope says of it (B6). Text with pills, a pill's
// details and the condition builder draw it.
import { useQuery, type QueryKey } from "@tanstack/react-query";
import type { KeyboardEvent } from "react";
import { DraftMoved, scopeQuery, type ScopeEntry } from "../../../lib/data";
import { pillText, type Pill } from "../../../lib/pills";
import { useDrawer } from "./context";

/** Whether two scope questions ask of the same value in the same field, whatever the revision (the key's fourth part). */
const samePlace = (a: QueryKey, b: QueryKey): boolean =>
  a.length === b.length && a.every((x, i) => i === 3 || JSON.stringify(x) === JSON.stringify(b[i]));

/** What a pill knows of its value from the saved draft's scope: nothing yet, an entry, or the problem reading it.
 * `entry` is this revision's answer, the facts the details and the builder say and use; `shown` draws the pill, and
 * keeps the previous revision's answer while the next is asked (`stale`), so the pill doesn't change at each save while
 * nothing says those facts are current (the review of the final checkpoint). */
export function usePillEntry(path: string, field: string): {
  entry: ScopeEntry | null; shown: ScopeEntry | null; stale: boolean; problem: string | null;
} {  // prettier-ignore
  const drawer = useDrawer();
  const live = drawer.revision !== null;
  const query = scopeQuery(
    { tenantId: drawer.tenantId, workflowId: drawer.workflowId, revision: drawer.revision ?? -1, node: drawer.node.id, field },
    { kind: "at", path },
  );  // prettier-ignore
  const answer = useQuery({
    ...query,
    enabled: live,
    // While the next saved revision's answer comes, the previous one stands in, for this same value only: the pill
    // never turns solid ("always there") for want of an answer (the final review). The next answer replaces it, and an
    // answer about another revision is still refused (DraftMoved). A version's view asks nothing, and shows nothing.
    placeholderData: (previous, previousQuery) =>
      live && previousQuery && samePlace(previousQuery.queryKey, query.queryKey) ? previous : undefined,
  });
  const data = answer.data;
  if (answer.error instanceof DraftMoved) return { entry: null, shown: null, stale: false, problem: answer.error.message };
  if (!data || data.state !== "ok") return { entry: null, shown: null, stale: false, problem: data?.reason ?? null };
  const found = data.entries[0] ?? null;
  if (answer.isPlaceholderData) return { entry: null, shown: found, stale: true, problem: null };
  return { entry: found, shown: found, stale: false, problem: data.problem?.message ?? null };
}

/** A pill: its visible text first in its name (WCAG 2.5.3), then its path and what may happen to its value. */
export function PillButton({ pill, entry, index, onKeyDown, onOpen, buttonRef, disabled }: {
  pill: Pill; entry: ScopeEntry | null; index: number; onKeyDown?: (e: KeyboardEvent<HTMLButtonElement>) => void;
  onOpen: () => void; buttonRef?: (el: HTMLButtonElement | null) => void; disabled?: boolean;
}) {  // prettier-ignore
  const missing = entry?.missing === true;
  const text = pillText(pill.ref);
  const said = [
    `${text}${missing ? " ?" : ""}`,
    pill.ref,
    missing ? "may be missing" : null,
    entry?.nullable ? "may be null" : null,
    missing || entry?.nullable ? ("default" in pill ? `if so: ${pill.default === null ? "null" : `"${pill.default}"`}` : "no default") : null,
  ].filter((s) => s !== null);
  return (
    <button
      ref={buttonRef} type="button" data-pill={index} aria-label={said.join(", ")} aria-haspopup="dialog"
      aria-disabled={disabled || undefined} onClick={onOpen} onKeyDown={onKeyDown}
      className={`inline-flex max-w-full items-center rounded-pill border px-2 font-mono text-small ${
        missing ? "border-dashed border-warn-line bg-warn-bg text-warn-ink" : "border-accent bg-accent-soft text-accent-ink"}`}
    >
      <span className="truncate">{text}</span>
      {missing && <span aria-hidden="true">&nbsp;?</span>}
    </button>
  );  // prettier-ignore
}
