// SPDX-License-Identifier: Apache-2.0
// The viewport's width where a layout changes with it, not only its look (the runs design §5.6: a table's rows become
// a list below 640 px, Tailwind's `sm`): followed as it changes.
import { useSyncExternalStore } from "react";

const NARROW = "(width < 40rem)";

function subscribe(changed: () => void) {
  const query = window.matchMedia(NARROW);
  query.addEventListener("change", changed);
  return () => query.removeEventListener("change", changed);
}

/** Whether the viewport is narrower than 640 px. */
export const useNarrow = () => useSyncExternalStore(subscribe, () => window.matchMedia(NARROW).matches);
