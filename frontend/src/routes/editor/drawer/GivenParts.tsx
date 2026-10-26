// SPDX-License-Identifier: Apache-2.0
// A setting's parts, as an update's changes and a create's settings draw them (4f-2, the Mist step design §5.3): only
// the parts given (and those added, nothing given yet), each the drawer's own field, taken off with Remove (never
// Clear: only a top-level setting is cleared); "＋ Another setting of …" finds the rest. The same for each entry of a
// map (by key; a new one's key first) and each item of a list of objects (by number). A plain list or map, a union, a
// secret: the drawer's own control, whole. What's added and not given yet is remembered, never written.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { WORDS, drawnAt, reindexed, showing, type Memory } from "../../../lib/changes";
import { ENVELOPE, ENVELOPE_NAME, valueAt } from "../../../lib/config";
import { isObject, offeredOf, entryOf, itemOf, pointerOf, type FieldSpec } from "../../../lib/schemaForm";
import { settingsOf, type Setting } from "../../../lib/settingsIndex";
import { EmptiedContext, ITEM_EMPTIED, useDrawer } from "./context";
import { FieldView, type Drawn } from "./FieldView";
import { FindSetting } from "./FindSetting";
import { focusAfterRemove, lineageKey } from "./structured";

const NARROW = "max-sm:min-h-[44px]";

/** What the parts share: the changes' memory, and how they're sent. */
export const PartsContext = createContext<{
  memory: Memory; remember: (next: Partial<Memory> | ((now: Memory) => Partial<Memory>)) => void; where: "Changes" | "Settings";
} | null>(null);  // prettier-ignore
const useParts = () => {
  const parts = useContext(PartsContext);
  if (parts === null) throw new Error("GivenParts outside the changes");
  return parts;
};

/** Whether `held` holds `name` and nothing else: taking it out empties it. */
const onlyHolds = (held: unknown, name: string): boolean => isObject(held) && Object.keys(held).length === 1 && Object.hasOwn(held, name);

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
  const { memory, remember, where } = useParts();
  const emptied = useContext(EmptiedContext);
  const given = isObject(value) ? value : {};
  const shown = memory.shown[spec.pointer] ?? [];
  const offered = offeredOf(spec);
  const parts = offered.filter((p) => Object.hasOwn(given, p.name) || shown.includes(p.name));
  const open = memory.open === spec.pointer;
  const find = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) find.current?.focus();
  }, [open]);
  const remove = (part: FieldSpec, index: number) => {
    drawer.discard(part.pointer);
    const why = drawer.restructure(part.pointer, { path: spec.path, make: (obj) => (isObject(obj) ? Object.fromEntries(Object.entries(obj).filter(([k]) => k !== part.name)) : obj) });
    if (why === null) {
      remember({ shown: { ...memory.shown, [spec.pointer]: shown.filter((n) => n !== part.name) } });
      if (onlyHolds(value, part.name)) emptied?.(); // taken out, it stays drawn, nothing given yet
      focusAfterRemove(spec.pointer, index);
    }
  };
  const add = (s: Setting) => {
    const done = found(drawer, drawer.node.config ?? {}, memory, spec, s);
    if (done === null) return;
    remember(done.next);
    if (done.focus !== null) focusLater(done.focus);
  };
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {parts.map((part, i) => (
        <EmptiedContext.Provider
          key={part.name}
          value={() => {
            remember((now) => ({ shown: showing(now.shown, spec.pointer, [part.name]) }));
            if (onlyHolds(value, part.name)) emptied?.();
          }}
        >
        <FieldView
          spec={part}
          drawn={{
            hideClear: true, parts: partsOf(part), shown: drawnNames(part, valueAt(drawer.node.config ?? {}, part.path), memory), rowOf: spec.pointer,
            actions: drawer.editable && !(part.required && where === "Settings") ? (
              <Button
                size="sm" data-remove-of={spec.pointer} aria-label={`Remove ${spec.label} › ${part.label}`} className={NARROW}
                onMouseDown={(e) => e.preventDefault()} onClick={() => remove(part, i)}
              >
                Remove
              </Button>
            ) : undefined,
            below: drawer.editable && !Object.hasOwn(given, part.name) && !(part.required && where === "Settings") ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
          }}
        />
        </EmptiedContext.Provider>
      ))}
      {drawer.editable && offered.length > parts.length && (open ? (
        <FindSetting ref={find} settings={settingsOf(spec)} drawn={(s) => drawnAt(s.steps, value, spec.path, memory.shown)} where={where} label={`Find a setting of ${spec.label}`} onAdd={add} />
      ) : (
        <button type="button" data-add-for={spec.pointer} className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => remember({ open: spec.pointer })}>
          ＋ Another setting of {spec.label}
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

/** Adding `s`, found under `spec` (§5.4): each object on its way shown, its first step in `spec` too; a list on its way
 * gets a new item (written: its place is the person's); a map on its way asks its new entry's key first, then shows
 * the part. What to remember, and where focus goes (none while a key is asked); null when the item couldn't be
 * written. One path for the changes' Find and each object's own (the final review). */
export function found(
  drawer: ReturnType<typeof useDrawer>, config: unknown, memory: Memory, spec: FieldSpec, s: Setting,
): { next: Partial<Memory>; focus: string | null } | null {  // prettier-ignore
  let shown = showing(memory.shown, spec.pointer, [s.steps[0]!.name]);
  let path: (string | number)[] = spec.path;
  for (let i = 0; i < s.steps.length; i++) {
    const step = s.steps[i]!;
    const after = s.steps[i + 1];
    if (step.kind === "entry") {
      return { next: { shown, open: null, adding: { pointer: pointerOf(path), parts: after ? [after.name] : [] } }, focus: null };
    }
    if (step.kind === "item") {
      const held = valueAt(config, path);
      const index = Array.isArray(held) ? held.length : 0;
      if (drawer.restructure(pointerOf(path), { path, make: (l) => [...(Array.isArray(l) ? (l as unknown[]) : []), {}] }) !== null) return null;
      path = [...path, index];
      if (after) shown = showing(shown, pointerOf(path), [after.name]);
      continue;
    }
    if (after?.kind === "setting") shown = showing(shown, pointerOf([...path, step.name]), [after.name]);
    path = [...path, step.name];
  }
  const leaf = pointerOf(path);
  return { next: { shown, open: s.spec.base === "group" ? leaf : null, adding: null }, focus: leaf };
}

/** An object's parts drawn (given or added), for its problems: one at a part not drawn stays on it (the final review). */
export function drawnNames(spec: FieldSpec, value: unknown, memory: Memory): string[] | undefined {
  if (spec.base !== "group" || spec.sensitive || spec.cut) return undefined;
  const given = isObject(value) ? value : {};
  const shown = memory.shown[spec.pointer] ?? [];
  return offeredOf(spec).filter((p) => Object.hasOwn(given, p.name) || shown.includes(p.name)).map((p) => p.name);
}

/** Focus, once drawn, the control at `pointer` (else its nearest drawn holder's first); or its "＋ …" button (`add`),
 * or its pressed choice (`pressed`): after a row's action, focus stays where the person is (WCAG 2.4.3). */
export function focusLater(pointer: string, prefer?: "add" | "pressed") {
  requestAnimationFrame(() => {
    if (prefer === "add") {
      [...document.querySelectorAll<HTMLElement>("[data-add-for]")].find((e) => e.dataset.addFor === pointer)?.focus();
      return;
    }
    for (let at = pointer; at !== ""; at = at.slice(0, at.lastIndexOf("/"))) {
      const holder = [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === at);
      if (!holder) continue;
      const pressed = prefer === "pressed" ? holder.querySelector<HTMLElement>('[aria-pressed="true"]') : null;
      if (pressed) {
        pressed.focus();
        return;
      }
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
  const { memory, remember } = useParts();
  const emptied = useContext(EmptiedContext);
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
      remember({ entries: { ...memory.entries, [spec.pointer]: opened.filter((k) => k !== name) } });
      if (onlyHolds(value, name)) emptied?.();
      focusAfterRemove(spec.pointer, keys.indexOf(name));
    }
  };
  const open = () => {
    const name = key.trim();
    if (name === "") return setWhy("Give the entry a name.");
    if (name === ENVELOPE) return setWhy(ENVELOPE_NAME);
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
          <EmptiedContext.Provider
            key={name}
            value={() => {
              remember((now) => ({ entries: showing(now.entries, spec.pointer, [name]) }));
              if (onlyHolds(value, name)) emptied?.();
            }}
          >
          <FieldView
            spec={entry}
            drawn={{
              hideClear: true, parts: (s, v) => <GivenParts spec={s} value={v} />, rowOf: spec.pointer,
              shown: drawnNames(entry, isObject(value) ? value[name] : undefined, memory),
              actions: drawer.editable ? (
                <Button size="sm" data-remove-of={spec.pointer} aria-label={`Remove ${entry.label}`} className={NARROW} onClick={() => remove(name)}>Remove</Button>
              ) : undefined,
              below: drawer.editable && !(isObject(value) && Object.hasOwn(value, name)) ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
            }}
          />
          </EmptiedContext.Provider>
        );  // prettier-ignore
      })}
      {drawer.editable && (adding ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <label htmlFor={`${spec.pointer}-key`} className="text-small font-semibold">Name of the new entry</label>
          <input
            id={`${spec.pointer}-key`} autoFocus value={key} spellCheck={false} aria-invalid={why !== null} className={controlClass(why !== null)}
            aria-describedby={why !== null ? `${spec.pointer}-key-why` : undefined}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                open();
              } else if (e.key === "Escape") {
                // Forgotten, what's typed and why it's refused, focus back where the person was (F5).
                e.stopPropagation();
                remember({ adding: null });
                setKey("");
                setWhy(null);
                focusLater(spec.pointer, "add");
              }
            }}
          />
          {why && <p id={`${spec.pointer}-key-why`} className="text-small text-danger">{why}</p>}
        </div>
      ) : (
        <button type="button" data-add-for={spec.pointer} className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => remember({ adding: { pointer: spec.pointer, parts: [] } })}>
          ＋ Add an entry
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

/** A list's items by number, each by its given parts; an item added is written, empty: its place is the person's. Its
 * last item removed, the list isn't sent: nothing given (F1). */
function Items({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const { memory, remember } = useParts();
  const emptied = useContext(EmptiedContext);
  const items = Array.isArray(value) ? (value as unknown[]) : [];
  const lineage = lineageKey(value);
  const asList = (list: unknown) => (Array.isArray(list) ? [...(list as unknown[])] : []);
  // `order`: each place's item now, by the place it came from; what's remembered of an item follows it (F5).
  const reorder = (order: number[]) => {
    const why = drawer.restructure(spec.pointer, { path: spec.path, make: (list) => order.map((j) => asList(list)[j]) });
    if (why === null) remember((now) => reindexed(now, spec.pointer, order));
    return why;
  };
  const places = items.map((_, j) => j);
  const swap = (i: number) => [...places.slice(0, i), i + 1, i, ...places.slice(i + 2)];
  const remove = (i: number) => {
    if (reorder(places.filter((j) => j !== i)) !== null) return;
    if (items.length === 1) emptied?.();
    focusAfterRemove(spec.pointer, i);
  };
  const button = (label: string, onClick: () => void, disabled = false, removes = false): ReactNode => (
    <Button size="sm" data-remove-of={removes ? spec.pointer : undefined} aria-label={label} className={NARROW} disabled={disabled} onClick={onClick}>
      {label.split(":")[0]}
    </Button>
  );
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {items.map((_, i) => {
        const item = { ...itemOf(spec, i), label: `${spec.label} › item ${i + 1}` };
        return (
          <EmptiedContext.Provider key={`${lineage}:${i}`} value={ITEM_EMPTIED}>
          <FieldView
            spec={item}
            drawn={{
              hideClear: true, parts: (s, v) => <GivenParts spec={s} value={v} />, shown: drawnNames(item, items[i], memory), rowOf: spec.pointer,
              actions: drawer.editable ? (
                <>
                  {button(`Move up: ${item.label}`, () => reorder(swap(i - 1)), i === 0)}
                  {button(`Move down: ${item.label}`, () => reorder(swap(i)), i === items.length - 1)}
                  {button(`Remove: ${item.label}`, () => remove(i), false, true)}
                </>
              ) : undefined,
            }}
          />
          </EmptiedContext.Provider>
        );  // prettier-ignore
      })}
      {drawer.editable && (
        <button type="button" data-add-for={spec.pointer} className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => drawer.restructure(spec.pointer, { path: spec.path, make: (list) => [...asList(list), {}] })}>
          ＋ Add an item
        </button>
      )}
      <p className="text-small text-muted">{WORDS.wholeList}</p>
    </div>
  );  // prettier-ignore
}
