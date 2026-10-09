// SPDX-License-Identifier: Apache-2.0
// A value made of parts (4c-1, ruling 5): a group's properties, a list's items, a map's entries, each a field of its
// own; and a dynamic port's name, which edges hang on (ruling 9). A change to a list's or a map's shape applies the
// edits typed inside it first, or waits for them (ruling 18). A name is held while typed, applied when focus leaves or
// on Enter.
import { useId, useRef } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { freePort } from "../../../lib/config";
import { emptyOf, entryOf, isObject, itemOf, pointerOf, propertiesOf, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import type { GraphNode } from "../../../lib/workflows";
import { segment, useDrawer } from "./context";
import { FieldView } from "./FieldView";
import type { ControlProps } from "./scalars";

/** The widgets shown as their parts rather than as one control. */
export const isContainer = (widget: Widget): boolean => widget === "group" || widget === "list" || widget === "map";

/** The pointer segments of the parts a container shows: a problem below it in any other part is its own. */
export function partNames(spec: FieldSpec, value: unknown): string[] {
  if (spec.base === "list") return Array.isArray(value) ? (value as unknown[]).map((_, i) => String(i)) : [];
  if (spec.base === "map") return isObject(value) ? Object.keys(value).map(segment) : [];
  return propertiesOf(spec).map((p) => segment(p.name));
}

/** A new item: a case with the first free port name (ruling 9), else its schema's default, else an empty part. */
function newItem(item: FieldSpec, node: GraphNode): unknown {
  if (item.type.dynamic_ports !== null && item.path.length === 2 && item.path[0] === item.type.dynamic_ports) {
    return { port: freePort(node, item.type) };
  }
  if (item.schema.default !== undefined) return structuredClone(item.schema.default);
  return item.base === "group" || item.base === "map" ? {} : item.base === "list" ? [] : emptyOf(item);
}

const asList = (v: unknown): unknown[] => (Array.isArray(v) ? [...(v as unknown[])] : []);

function ListItems({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const add = useRef<HTMLButtonElement>(null);
  const items = asList(value);
  // Each changes the list's shape: the edits typed inside are applied first, or it waits (ruling 18).
  const move = (from: number, to: number) =>
    drawer.restructure(spec.pointer, {
      path: spec.path,
      make: (list) => {
        const next = asList(list);
        next.splice(to, 0, ...next.splice(from, 1));
        return next;
      },
    });
  const remove = (index: number) => {
    if (drawer.restructure(spec.pointer, { path: [...spec.path, index], make: () => undefined }) !== null) return;
    // Its controls are gone: focus goes to Add. A removal that asks first lands on the drawer's heading instead.
    requestAnimationFrame(() => add.current?.focus());
  };
  const append = () =>
    drawer.restructure(spec.pointer, { path: spec.path, make: (list) => [...asList(list), newItem(itemOf(spec, asList(list).length), drawer.node)] });
  return (
    <>
      {items.length === 0 && <p className="text-small text-muted">None yet.</p>}
      {items.map((_, i) => {
        const item = itemOf(spec, i);
        return (
          <div key={i} className="flex min-w-0 flex-col gap-2">
            <FieldView spec={item} />
            {drawer.editable && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" aria-label={`Move up: ${item.label}`} disabled={i === 0} onClick={() => move(i, i - 1)}>Move up</Button>
                <Button size="sm" aria-label={`Move down: ${item.label}`} disabled={i === items.length - 1} onClick={() => move(i, i + 1)}>
                  Move down
                </Button>
                <Button size="sm" variant="danger-outline" aria-label={`Remove: ${item.label}`} onClick={() => remove(i)}>Remove</Button>
              </div>
            )}
          </div>
        );
      })}
      {drawer.editable && (
        <Button ref={add} size="sm" className="self-start" onClick={append}>Add to {spec.label}</Button>
      )}
    </>
  );
}

/** A map entry's name: held while typed, applied on Enter or when focus leaves the name and its Discard; refused when
 * empty, `$value` (ruling 15) or another entry's, said here. Its Discard never renames first (the review of revision
 * 4). */
function NameField({ map, name }: { map: FieldSpec; name: string }) {
  const drawer = useDrawer();
  const id = useId();
  const pointer = pointerOf([...map.path, name]);
  const held = drawer.held("name", pointer);
  const why = held?.why ?? null;
  const commit = () => {
    if (held) drawer.apply("name", pointer);
  };
  return (
    // One focus region, its Discard before the input as a field's actions are: Tab out of the input leaves it, and
    // applies the name; a move to the Discard doesn't.
    <div
      data-name-pointer={pointer}
      className="flex min-w-0 flex-col gap-1.5"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) commit();
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={id} className="text-small font-semibold">Name</label>
        {held && drawer.editable && (
          <Button
            size="sm" aria-label={`Discard the new name for ${name}`}
            onMouseDown={(e) => e.preventDefault()} // a press keeps focus: no rename on the way to the discard
            onClick={() => drawer.release("name", pointer)}
          >
            Discard
          </Button>
        )}
      </div>
      <input
        id={id} type="text" value={held?.text ?? name} disabled={!drawer.editable} spellCheck={false} aria-label={`Name: ${name}`}
        aria-invalid={why !== null} aria-describedby={why !== null ? `${id}-p` : undefined}
        onChange={(e) => {
          if (e.target.value === name) drawer.release("name", pointer);
          else drawer.hold("name", pointer, { path: map.path, label: `${map.label}, the name ${name}`, text: e.target.value, why: null, from: name });
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        className={`${controlClass(why !== null)} font-mono`}
      />
      {why !== null && <p id={`${id}-p`} className="text-small text-danger">{why}</p>}
    </div>
  );  // prettier-ignore
}

function MapEntries({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const add = useRef<HTMLButtonElement>(null);
  const entries = isObject(value) ? Object.entries(value) : [];
  const append = () =>
    drawer.restructure(spec.pointer, {
      path: spec.path,
      make: (map) => {
        const own = isObject(map) ? map : {};
        let n = 1;
        while (Object.hasOwn(own, `field_${n}`)) n++;
        return { ...own, [`field_${n}`]: null };
      },
    });
  return (
    <>
      {entries.length === 0 && <p className="text-small text-muted">None yet.</p>}
      {entries.map(([name], i) => {
        const entry = entryOf(spec, name);
        return (
          <div key={i} className="flex min-w-0 flex-col gap-2">
            <NameField map={spec} name={name} />
            <FieldView spec={entry} />
            {drawer.editable && (
              <Button
                size="sm" variant="danger-outline" className="self-start" aria-label={`Remove: ${name}`}
                onClick={() => {
                  if (drawer.restructure(spec.pointer, { path: entry.path, make: () => undefined }) === null) {
                    requestAnimationFrame(() => add.current?.focus());
                  }
                }}
              >
                Remove
              </Button>
            )}
          </div>
        );  // prettier-ignore
      })}
      {drawer.editable && (
        <Button ref={add} size="sm" className="self-start" onClick={append}>Add to {spec.label}</Button>
      )}
    </>
  );
}

export function ContainerParts({ spec, value }: { spec: FieldSpec; value: unknown }) {
  if (spec.base === "list") return <ListItems spec={spec} value={value} />;
  if (spec.base === "map") return <MapEntries spec={spec} value={value} />;
  return propertiesOf(spec).map((part) => <FieldView key={part.pointer} spec={part} />);
}

/** A dynamic port's name (a switch case's `port`): edges hang on it, so it's held while typed and applied on Enter, or
 * when focus leaves its field (the field does that, so its Discard never applies it first), its edges following; a name
 * the graph's format refuses, or another port's, is refused there (ruling 9). */
export function PortControl({ spec, value, id, describedBy, invalid, disabled }: ControlProps) {
  const drawer = useDrawer();
  const held = drawer.held("port", spec.pointer);
  const now = typeof value === "string" ? value : "";
  const commit = () => {
    if (held) drawer.apply("port", spec.pointer);
  };
  return (
    <input
      id={id} type="text" value={held?.text ?? now} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required
      onChange={(e) => {
        if (e.target.value === now) drawer.release("port", spec.pointer);
        else drawer.hold("port", spec.pointer, { path: spec.path, label: spec.label, text: e.target.value, why: null });
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      className={`${controlClass(invalid)} font-mono`}
    />
  );  // prettier-ignore
}
