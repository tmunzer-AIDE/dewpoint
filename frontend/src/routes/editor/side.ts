// SPDX-License-Identifier: Apache-2.0
/** The editor's side panels (a step's, Problems, Versions). Beside the canvas while the editor is at least 48rem wide;
 * below it on a narrower one (at 320 px, beside it would leave the canvas nothing), at most half the height, so the
 * canvas always keeps room for what focus is sent to and what a click places (the owner's review of 6d7766e). The
 * editor's root is the container these sizes measure. */
export const SIDE =
  "flex w-full shrink-0 flex-col overflow-y-auto border-line bg-surface p-5 @3xl:max-w-[440px] @3xl:border-l @max-3xl:max-h-[50%] @max-3xl:border-t";
