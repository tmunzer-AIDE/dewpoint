// SPDX-License-Identifier: Apache-2.0
// What changed, said to assistive technology through the shell's one polite live region (D16).
type Listener = (message: string) => void;
const listeners = new Set<Listener>();

export function announce(message: string): void {
  for (const listener of listeners) listener(message);
}

export function onAnnounce(listener: Listener): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
