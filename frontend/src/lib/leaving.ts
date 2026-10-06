// SPDX-License-Identifier: Apache-2.0
// What an open editor says before something takes the person out of it without the router (4b ruling 22): sign-out,
// an ended session. Router navigations ask the editor through its own blocker; these ask through here, before they
// revoke anything or clear any cache.
export interface LeaveGuard {
  /** Whether it holds work the server hasn't got. */
  unsaved: () => boolean;
  /** Saves what it can; when it can't, asks the person. True: leaving may go on. */
  decide: () => Promise<boolean>;
  /** The exit it agreed to didn't happen (a sign-out that failed): its next decision asks afresh. */
  stayed?: () => void;
}

const guards = new Set<LeaveGuard>();

export function guardLeaving(guard: LeaveGuard): () => void {
  guards.add(guard);
  return () => void guards.delete(guard);
}

export const unsavedWork = (): boolean => [...guards].some((g) => g.unsaved());

/** Every open editor's say, in turn; the first "stay" ends it. */
export async function mayLeave(): Promise<boolean> {
  for (const g of [...guards]) if (!(await g.decide())) return false;
  return true;
}

/** The exit `mayLeave` was asked for didn't happen: no editor's "leave" stands for the next one. */
export function cancelLeaving(): void {
  for (const g of [...guards]) g.stayed?.();
}
