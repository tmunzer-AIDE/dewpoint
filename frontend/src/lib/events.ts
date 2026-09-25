// SPDX-License-Identifier: Apache-2.0
/** Tiny app-wide signal: queries that fail with step_up_required raise it; the shell shows a banner. */
type Listener = () => void;
const listeners = new Set<Listener>();

export function onStepUpRequired(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function raiseStepUpRequired(): void {
  listeners.forEach((fn) => fn());
}
