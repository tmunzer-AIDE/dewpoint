// SPDX-License-Identifier: Apache-2.0
// A setting's parts, as an update's changes and a create's settings draw them (4f-2, the Mist step design §5.3): only
// the parts given (and those added, nothing given yet), each the drawer's own field, taken off with Remove (never
// Clear: only a top-level setting is cleared); "＋ Another setting of …" finds the rest. The same for each entry of a
// map (by key; a new one's key first) and each item of a list of objects (by number). A plain list or map, a union, a
// secret: the drawer's own control, whole. What's added and not given yet is remembered, never written.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { WORDS, showing, type Memory } from "../../../lib/changes";
import { isObject, offeredOf, entryOf, itemOf, pointerOf, type FieldSpec } from "../../../lib/schemaForm";
import { settingsOf, type Setting } from "../../../lib/settingsIndex";
import { useDrawer } from "./context";
import { FieldView, type Drawn } from "./FieldView";
import { FindSetting } from "./FindSetting";

const NARROW = "max-sm:min-h-[44px]";

/** What the parts share: the changes' memory, and how they're sent. */
export const PartsContext = createContext<{ memory: Memory; remember: (next: Partial<Memory>) => void; top: (pointer: string) => void; where: "Changes" | "Settings" } | null>(null);
const useParts = () => {
  const parts = useContext(PartsContext);
  if (parts === null) throw new Error("GivenParts outside the changes");
  return parts;
};

/** How a setting's value is drawn: an object, an entry or an item by its given parts, else the drawer's own control. */
export function partsOf(spec: FieldSpec): Drawn["parts"] | undefined {
  if (spec.sensitive || spec.cut) return undefined;
  if (spec.base === "group") return (s, value) => <GivenParts spec={s} value={value} />;
  if (spec.base === "map" && entryOf(spec, "*").base === "group") return (s, value) => <Entries spec={s} value={value} />;
  if (spec.base === "list" && itemOf(spec, 0).base === "group") return (s, value) => <Items spec={s} value={value} />;
  return undefined;
}

/** Its parts given, those added and not given yet, and the rest a search away. */
export function GivenParts({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const { memory, remember, top, where } = useParts();
  const given = isObject(value) ? value : {};
  const shown = memory.shown[spec.pointer] ?? [];
  const offered = offeredOf(spec);
  const parts = offered.filter((p) => p.name in given || shown.includes(p.name));
  const open = memory.open === spec.pointer;
  const find = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) find.current?.focus();
  }, [open]);
  const remove = (part: FieldSpec) => {
    drawer.discard(part.pointer);
    const why = drawer.restructure(part.pointer, { path: spec.path, make: (obj) => (isObject(obj) ? Object.fromEntries(Object.entries(obj).filter(([k]) => k !== part.name)) : obj) });
    if (why === null) {
      top(spec.pointer); // emptied, the setting's row stays, nothing given yet
      remember({ shown: { ...memory.shown, [spec.pointer]: shown.filter((n) => n !== part.name) } });
    }
  };
  const add = (s: Setting) => {
    const leaf = pointerOf([...spec.path, ...s.steps.map((step) => step.name)]);
    const next = opening(memory, spec, s);
    remember({ ...next, open: s.spec.base === "group" && next.adding == null ? leaf : null });
    if (next.adding == null) focusLater(leaf);
  };
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {parts.map((part) => (
        <FieldView
          key={part.name} spec={part}
          drawn={{
            hideClear: true, parts: partsOf(part),
            actions: drawer.editable && !(part.required && where === "Settings") ? (
              <Button size="sm" aria-label={`Remove ${part.label}`} className={NARROW} onMouseDown={(e) => e.preventDefault()} onClick={() => remove(part)}>Remove</Button>
            ) : undefined,
          }}
        />
      ))}
      {drawer.editable && offered.length > parts.length && (open ? (
        <FindSetting ref={find} settings={settingsOf(spec)} listed={new Set(parts.map((p) => p.name))} where={where} label={`Find a setting of ${spec.label}`} onAdd={add} />
      ) : (
        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => remember({ open: spec.pointer })}>
          ＋ Another setting of {spec.label}
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

/** What remembering `s`, found under `spec`, shows: each object on its way, a map's new entry (key first), a list's
 * new item is written by the caller. */
export function opening(memory: Memory, spec: FieldSpec, s: Setting): Partial<Memory> {
  let shown = memory.shown;
  let path = spec.path;
  for (let i = 0; i < s.steps.length; i++) {
    const step = s.steps[i]!;
    if (step.kind === "entry") {
      const rest = s.steps.slice(i + 1).filter((x) => x.kind === "setting").map((x) => x.name);
      return { shown, adding: { pointer: pointerOf(path), parts: rest.slice(0, 1) } };
    }
    if (step.kind === "item") return { shown };
    if (i < s.steps.length - 1 && s.steps[i + 1]!.kind === "setting") shown = showing(shown, pointerOf([...path, step.name]), [s.steps[i + 1]!.name]);
    path = [...path, step.name];
  }
  return { shown: showing(shown, pointerOf(spec.path), [s.steps[0]!.name]) };
}

/** Focus, once drawn, the control at `pointer`, else its nearest drawn holder's first. */
export function focusLater(pointer: string) {
  requestAnimationFrame(() => {
    for (let at = pointer; at !== ""; at = at.slice(0, at.lastIndexOf("/"))) {
      const holder = [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === at);
      if (!holder) continue;
      const label = holder.querySelector<HTMLLabelElement>("label[for]");
      const control = (label && document.getElementById(label.htmlFor)) ?? holder.querySelector<HTMLElement>("input, select, textarea, button");
      control?.focus();
      return;
    }
  });
}

/** A map's entries by key, each by its given parts; a new one's key first. */
function Entries({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const { memory, remember, top } = useParts();
  const given = isObject(value) ? Object.keys(value) : [];
  const opened = memory.entries[spec.pointer] ?? [];
  const keys = [...given, ...opened.filter((k) => !given.includes(k))];
  const adding = memory.adding?.pointer === spec.pointer;
  const [key, setKey] = useState("");
  const [why, setWhy] = useState<string | null>(null);
  const remove = (name: string) => {
    const pointer = pointerOf([...spec.path, name]);
    drawer.discard(pointer);
    const done = drawer.restructure(pointer, { path: spec.path, make: (map) => (isObject(map) ? Object.fromEntries(Object.entries(map).filter(([k]) => k !== name)) : map) });
    if (done === null) {
      top(spec.pointer);
      remember({ entries: { ...memory.entries, [spec.pointer]: opened.filter((k) => k !== name) } });
    }
  };
  const open = () => {
    const name = key.trim();
    if (name === "") return setWhy("Give the entry a name.");
    if (keys.includes(name)) return setWhy(`${spec.label} has an entry named ${name} already.`);
    const entry = pointerOf([...spec.path, name]);
    const parts = memory.adding?.parts ?? [];
    remember({
      adding: null, entries: { ...memory.entries, [spec.pointer]: [...opened, name] },
      shown: parts.length > 0 ? showing(memory.shown, entry, parts) : memory.shown, open: parts.length > 0 ? null : entry,
    });  // prettier-ignore
    setKey("");
    setWhy(null);
    if (parts.length > 0) focusLater(`${entry}/${parts[0]}`); // else its own list opens, focused (GivenParts)
  };
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {keys.map((name) => {
        const entry = { ...entryOf(spec, name), label: `${spec.label} › ${name}` };
        return (
          <FieldView
            key={name} spec={entry}
            drawn={{
              hideClear: true, parts: (s, v) => <GivenParts spec={s} value={v} />,
              actions: drawer.editable ? <Button size="sm" aria-label={`Remove ${entry.label}`} className={NARROW} onClick={() => remove(name)}>Remove</Button> : undefined,
            }}
          />
        );  // prettier-ignore
      })}
      {drawer.editable && (adding ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <label htmlFor={`${spec.pointer}-key`} className="text-small font-semibold">Name of the new entry</label>
          <input
            id={`${spec.pointer}-key`} autoFocus value={key} spellCheck={false} aria-invalid={why !== null} className={controlClass(why !== null)}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                open();
              } else if (e.key === "Escape") {
                e.stopPropagation();
                remember({ adding: null });
              }
            }}
          />
          {why && <p className="text-small text-danger">{why}</p>}
        </div>
      ) : (
        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => remember({ adding: { pointer: spec.pointer, parts: [] } })}>
          ＋ Add an entry
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

/** A list's items by number, each by its given parts; an item added is written, empty: its place is the person's. */
function Items({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const items = Array.isArray(value) ? (value as unknown[]) : [];
  const reshape = (make: (list: unknown[]) => unknown[]) =>
    drawer.restructure(spec.pointer, { path: spec.path, make: (list) => make(Array.isArray(list) ? [...(list as unknown[])] : []) });
  const button = (label: string, onClick: () => void, disabled = false): ReactNode => (
    <Button size="sm" aria-label={label} className={NARROW} disabled={disabled} onClick={onClick}>{label.split(":")[0]}</Button>
  );
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {items.map((_, i) => {
        const item = { ...itemOf(spec, i), label: `${spec.label} › item ${i + 1}` };
        return (
          <FieldView
            key={i} spec={item}
            drawn={{
              hideClear: true, parts: (s, v) => <GivenParts spec={s} value={v} />,
              actions: drawer.editable ? (
                <>
                  {button(`Move up: item ${i + 1}`, () => reshape((l) => [...l.slice(0, i - 1), l[i], l[i - 1], ...l.slice(i + 1)]), i === 0)}
                  {button(`Move down: item ${i + 1}`, () => reshape((l) => [...l.slice(0, i), l[i + 1], l[i], ...l.slice(i + 2)]), i === items.length - 1)}
                  {button(`Remove: item ${i + 1}`, () => reshape((l) => l.filter((__, j) => j !== i)))}
                </>
              ) : undefined,
            }}
          />
        );  // prettier-ignore
      })}
      {drawer.editable && (
        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => reshape((l) => [...l, {}])}>
          ＋ Add an item
        </button>
      )}
      <p className="text-small text-muted">{WORDS.wholeList}</p>
    </div>
  );  // prettier-ignore
}
