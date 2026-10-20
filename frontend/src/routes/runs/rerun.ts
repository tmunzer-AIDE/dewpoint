// SPDX-License-Identifier: Apache-2.0
// A re-run's input (editor 4e-2b; the run form design §5.4; the Rerun board): the original's, read back redacted. What
// the server kept of it (a protected value) is never shown here: untouched, the re-run sends no input and the server
// rebuilds the original whole; changed, the input goes whole, those values entered again, the marker never sent.
import type { StartForm } from "../../lib/runForm";
import { shownOf } from "../editor/startInput";

/** What the read-back writes where the original held a protected value (a claim: sensitive, undeclared, too large, or
 * nested in a sensitive property). */
export const REDACTED = "[redacted]";

/** Whether a value read back is, or holds, the marker. */
export function holdsMarker(v: unknown): boolean {
  if (v === REDACTED) return true;
  if (Array.isArray(v)) return v.some(holdsMarker);
  return v !== null && typeof v === "object" && Object.values(v).some(holdsMarker);
}

/** The original's input on a form: each field's value as its control shows it, and the fields the server kept (marked
 * sensitive, or read back holding the marker), shown as kept and entered again once the input changes. */
export function prefill(form: StartForm, input: Record<string, unknown> | null): { values: Map<string, string>; kept: Set<string> } {
  const values = new Map<string, string>();
  const kept = new Set<string>();
  for (const f of form.fields) {
    if (input === null || !Object.hasOwn(input, f.name)) continue;
    const v = input[f.name];
    if (f.sensitive || holdsMarker(v)) kept.add(f.name);
    else {
      const shown = shownOf(f, v);
      if (shown !== null) values.set(f.name, shown);
    }
  }
  return { values, kept };
}

/** The version a re-run runs, beside the one its run ran (§5.4). */
export const versionWords = (form: StartForm, ran: { id: string | null; number: number | null }, short: string) =>
  ran.id === form.version_id
    ? `It runs version ${form.version_number}, the same version as run ${short}.`
    : `It runs version ${form.version_number}, the one published now.${ran.number === null ? "" : ` Run ${short} ran version ${ran.number}.`}`;

export const MARKER_WORDS = `It holds ${REDACTED}, a protected value the original kept: enter that value again.`;
export const AGAIN = "Enter it again: a changed input is sent whole, and the original's protected values never reach this form.";
