// SPDX-License-Identifier: Apache-2.0
// Find a setting (4f-2, the Mist step design §5.4): a combobox over a body's settings, top-level and nested, found by
// every word typed in a title, the raw path or the description. Its hits a listbox under it, Up and Down to move,
// Enter to add, Escape to close; each hit its path of titles, its raw path in the code face, its description on one
// line, the words matched bold and underlined (never coloured); one already listed says "· In Changes".
import { forwardRef, useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { controlClass } from "../../../components/Field";
import { MAX_SHOWN, findSettings, findWords, wordsOf, type Setting } from "../../../lib/settingsIndex";

/** `text` with each word found in it bold and underlined. */
function marked(text: string, words: string[]): ReactNode {
  if (words.length === 0) return text;
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(pattern).map((part, i) =>
    i % 2 === 1 ? <mark key={i} className="bg-transparent font-semibold text-ink underline underline-offset-2">{part}</mark> : part,
  );
}

export const FindSetting = forwardRef<HTMLInputElement, {
  settings: Setting[]; listed: ReadonlySet<string>; where: "Changes" | "Settings"; label?: string; onAdd: (setting: Setting) => void;
}>(function FindSetting({ settings, listed, where, label = "Find a setting", onAdd }, input) {  // prettier-ignore
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const { shown, total } = open ? findSettings(settings, query) : { shown: [], total: 0 };
  const words = wordsOf(query);
  const pick = (s: Setting | undefined) => {
    if (s === undefined) return;
    setOpen(false);
    setQuery("");
    onAdd(s);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const move = { ArrowDown: active + 1, ArrowUp: active - 1 }[e.key];
    if (move !== undefined) {
      setOpen(true);
      setActive(Math.max(0, Math.min(shown.length - 1, move)));
    } else if (e.key === "Enter" && open) pick(shown[active]);
    else if (e.key === "Escape" && open) setOpen(false);
    else return;
    e.preventDefault();
    e.stopPropagation(); // Escape closes the list, not the drawer
  };
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <input
        ref={input} type="search" role="combobox" aria-label={label} aria-expanded={open} aria-controls={open && shown.length > 0 ? `${id}-hits` : undefined}
        aria-activedescendant={open && shown.length > 0 ? `${id}-${active}` : undefined} aria-autocomplete="list"
        placeholder="Find a setting by its name or what it does" value={query} spellCheck={false}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={onKeyDown}
        className={controlClass(false)}
      />
      {open && (
        <>
          {shown.length > 0 && (
            <ul id={`${id}-hits`} role="listbox" aria-label={`${label}: settings found`} className="max-h-[320px] overflow-y-auto rounded-control border border-line p-1">
              {shown.slice(0, MAX_SHOWN).map((s, i) => (
                <li
                  key={s.raw} id={`${id}-${i}`} role="option" aria-selected={i === active}
                  onMouseDown={(e) => e.preventDefault()} onClick={() => pick(s)}
                  className="flex cursor-pointer flex-col gap-0.5 rounded-control px-2.5 py-1.5 aria-selected:bg-accent-soft"
                >
                  <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="text-body">
                      {marked(s.titles.join(" › "), words)}
                      {listed.has(s.steps[0]!.name) && <span className="text-small font-semibold text-accent-ink"> · In {where}</span>}
                    </span>
                    <span className="font-mono text-meta text-muted">{s.raw}</span>
                  </span>
                  {s.description && <span className="truncate text-small text-muted">{marked(s.description, words)}</span>}
                </li>
              ))}
            </ul>
          )}
          <p role="status" className="text-small text-muted">{findWords(query, shown.length, total)}</p>
        </>
      )}
    </div>
  );  // prettier-ignore
});
