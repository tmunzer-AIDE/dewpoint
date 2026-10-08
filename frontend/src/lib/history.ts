// SPDX-License-Identifier: Apache-2.0
// Undo and redo stay local (D17; 4b ruling 21): documents in memory, never sent, gone when the editor closes.
export interface History<T> {
  past: T[];
  present: T;
  future: T[];
}

export const LIMIT = 100;

export const begin = <T>(present: T): History<T> => ({ past: [], present, future: [] });

export function record<T>(h: History<T>, next: T): History<T> {
  if (next === h.present) return h;
  return { past: [...h.past, h.present].slice(-LIMIT), present: next, future: [] };
}

export function undo<T>(h: History<T>): History<T> {
  if (h.past.length === 0) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1]!, future: [h.present, ...h.future] };
}

export function redo<T>(h: History<T>): History<T> {
  if (h.future.length === 0) return h;
  return { past: [...h.past, h.present], present: h.future[0]!, future: h.future.slice(1) };
}
