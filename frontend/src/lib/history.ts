// SPDX-License-Identifier: Apache-2.0
// Undo and redo stay local (D17; 4b ruling 21): documents in memory, never sent, gone when the editor closes.
export interface History<T> {
  past: T[];
  present: T;
  future: T[];
  mark?: string; // what made the present: a field's focus session, whose next edit replaces it (4c-1 ruling 8)
}

export const LIMIT = 100;

export const begin = <T>(present: T): History<T> => ({ past: [], present, future: [] });

/** `next` as the present. An edit with the mark that made the present replaces it: one field's typing while it keeps
 * focus is one step (4c-1 ruling 8). Any other edit is a step of its own. */
export function record<T>(h: History<T>, next: T, mark?: string): History<T> {
  if (next === h.present) return h;
  if (mark !== undefined && h.mark === mark) return { past: h.past, present: next, future: [], mark };
  return { past: [...h.past, h.present].slice(-LIMIT), present: next, future: [], mark };
}

export function undo<T>(h: History<T>): History<T> {
  if (h.past.length === 0) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1]!, future: [h.present, ...h.future] };
}

export function redo<T>(h: History<T>): History<T> {
  if (h.future.length === 0) return h;
  return { past: [...h.past, h.present], present: h.future[0]!, future: h.future.slice(1) };
}
