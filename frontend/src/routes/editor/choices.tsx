// SPDX-License-Identifier: Apache-2.0
// A field's choices, read on request (4c-1, ruling 14): the list under the field, and the era each answer belongs to
// (ruling 109). Shared by the step drawer's options fields (4f-2a) and the start forms' pickers (the 4f-3 design
// §5.1): each says its own words and reads through its own route; nothing here reads the drawer.
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { Schemas } from "../../lib/client";

export type Option = Schemas["OptionOut"];
export type Choices =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "done"; options: Option[]; query: string }
  | { status: "failed"; why: string };

/** A choice's id, shortened when it's long: its name says the rest. */
export const idStart = (value: string) => (value.length > 12 ? `${value.slice(0, 8)}…` : value);

/** Choices read on request, at most 200 characters of query as the API takes, each answer for its era only: each
 * change of `scope` is a new era, never to be returned to (choices from A, then B, then A again are A's first era's,
 * and stay gone: the review of revision 2). */
export function useScopedChoices(scope: string, read: (query: string) => Promise<Option[]>, why: (e: unknown) => string) {
  const [seen, setSeen] = useState(scope);
  const [era, setEra] = useState(0);
  if (seen !== scope) {
    setSeen(scope);
    setEra((e) => e + 1);
  }
  const eraNow = useRef(era);
  eraNow.current = era;
  const [choices, setChoices] = useState<{ era: number; state: Choices }>({ era, state: { status: "idle" } });
  const shown: Choices = choices.era === era && seen === scope ? choices.state : { status: "idle" };
  async function load(typed: string) {
    const asked = era;
    const query = typed.slice(0, 200);
    setChoices({ era: asked, state: { status: "loading" } });
    try {
      const options = await read(query);
      if (eraNow.current === asked) setChoices({ era: asked, state: { status: "done", options, query } });
    } catch (e) {
      if (eraNow.current === asked) setChoices({ era: asked, state: { status: "failed", why: why(e) } });
    }
  }
  const close = () => setChoices({ era, state: { status: "idle" } });
  return { shown, load, close };
}

/** The choices, as a list under the field: Up and Down move, Enter picks, Escape closes; it scrolls past ten. The
 * drawer's takes focus when shown (ruling 338); a start form's waits for Down in its field, and its rows are 44 px
 * below 640 px, the name over the id (the 4f-3 design §5.1). */
export function ChoiceList({ label, options, onPick, onClose, id, focusOnShow = true, tall = false }: {
  label: string; options: Option[]; onPick: (o: Option) => void; onClose: () => void; id?: string; focusOnShow?: boolean; tall?: boolean;
}) {  // prettier-ignore
  const own = useId();
  const list = useRef<HTMLUListElement>(null);
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (focusOnShow) list.current?.focus();
  }, [focusOnShow]);
  useEffect(() => document.getElementById(`${own}-${active}`)?.scrollIntoView?.({ block: "nearest" }), [active, own]);
  const onKeyDown = (e: KeyboardEvent) => {
    const move = { ArrowDown: active + 1, ArrowUp: active - 1, Home: 0, End: options.length - 1 }[e.key];
    if (move !== undefined) setActive(Math.max(0, Math.min(options.length - 1, move)));
    else if (e.key === "Enter") onPick(options[active]!);
    else if (e.key === "Escape") onClose();
    else return;
    e.preventDefault();
    e.stopPropagation(); // Escape closes the list, not the drawer or the form
  };
  const row = tall ? " max-sm:min-h-[44px] max-sm:flex-col max-sm:items-start max-sm:justify-center max-sm:gap-0" : "";
  return (
    <ul
      ref={list} id={id} role="listbox" tabIndex={0} aria-label={`Choices for ${label}`} aria-activedescendant={`${own}-${active}`} onKeyDown={onKeyDown}
      className="max-h-[320px] overflow-y-auto rounded-control border border-line p-1"
    >
      {options.map((o, i) => (
        <li
          key={`${i}:${o.value}`} id={`${own}-${i}`} role="option" aria-selected={i === active}
          onMouseDown={(e) => e.preventDefault()} onClick={() => onPick(o)}
          className={`flex min-h-[32px] cursor-pointer items-center justify-between gap-3 rounded-control px-2.5 text-body aria-selected:bg-accent-soft${row}`}
        >
          <span className={`min-w-0 truncate${tall ? " max-sm:max-w-full" : ""}`}>{o.label}</span>
          {o.label !== o.value && <span className="shrink-0 font-mono text-meta text-muted">{idStart(o.value)}</span>}
        </li>
      ))}
    </ul>
  );  // prettier-ignore
}
