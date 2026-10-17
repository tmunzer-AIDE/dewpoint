// SPDX-License-Identifier: Apache-2.0
// The canvas's keyboard (D16; 4b ruling 15): one roving tab stop, and the arrow keys walking the graph's items along
// the path they came by (canvasNav.ts). The editor's and a run's page's (editor 4e-1; the runs design §5.3): the tab
// stop's item, a focus request the canvas carries out once it has drawn it, and the walk.
import { useCallback, useMemo, useState } from "react";
import { START } from "../../lib/graph";
import type { GraphDoc } from "../../lib/workflows";
import { isPath, navModel, pathTo, step, type NavKey } from "./canvasNav";

/** `portsOf` (a step's ports, by its id) is kept stable by the caller: the model is built again when it changes. */
export function useCanvasNav(doc: GraphDoc, portsOf: (nodeId: string) => string[], editable: boolean) {
  const [focusId, setFocusId] = useState<string>(START);
  const [focusRequest, setFocusRequest] = useState<{ id: string; n: number } | null>(null);
  const [trail, setTrail] = useState<string[] | null>(null); // the path the keys came by to the focused item
  const nav = useMemo(() => navModel(doc, portsOf, editable), [doc, portsOf, editable]);
  const shown = nav.order.includes(focusId) ? focusId : START; // a deleted item's tab stop falls back to the start card

  /** Focus moves to `id`, by `path` when the keys took it there. */
  const focus = useCallback((id: string, path: string[] | null = null) => {
    setFocusId(id);
    setTrail(path);
    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
  }, []);

  /** The item that took focus, by a click, Tab or a key, becomes the tab stop; the keys' path holds while it ends there. */
  const onFocusItem = useCallback((id: string) => {
    setFocusId(id);
    setTrail((t) => (t?.at(-1) === id ? t : null));
  }, []);

  /** A key's move from the tab stop's item: from the item focus is meant to be on, as a key moves focus a frame later
   * (the canvas draws it first), and a key pressed before then starts where the last one left it. The path the keys
   * came by while it still holds (at a join, the branch taken); else the walk's own path. */
  function walk(key: NavKey) {
    const path = trail && trail.at(-1) === shown && isPath(nav, trail) ? trail : pathTo(nav, shown);
    const next = step(nav, path, key);
    if (next.at(-1) !== shown) focus(next.at(-1)!, next);
  }

  return { nav, focusId, shown, focusRequest, trail, focus, onFocusItem, walk };
}
