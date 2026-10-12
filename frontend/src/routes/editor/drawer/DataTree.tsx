// SPDX-License-Identifier: Apache-2.0
// The data a field can read, to insert as a pill (4c-2b, the mockups' tree boards): the saved draft's scope (B6) by
// where it comes from, each value with its type, whether it may be missing or null, and whether it's sensitive. In the
// drawer, under its field, never over the canvas (the 320 px board). An ARIA tree: one tab stop, arrows to move, → to
// open, ← to close or go up, Enter to insert, Escape to close. A key a reference can't name, or a value validation
// refuses here, is shown and can't be chosen (ruling 118).
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { opsFor } from "../../../lib/builder";
import { DraftMoved, groupOf, scopeQuery, tagsOf, typeWords, type ScopeEntry, type Where } from "../../../lib/data";
import { parsePath } from "../../../lib/pills";
import { useDrawer } from "./context";

/** What a pick is for: text takes any value a reference can name; a condition, one a formula can read. */
export type Purpose = "text" | "condition";

/** Why an entry can't be chosen here, or null. */
export function refusal(entry: ScopeEntry, purpose: Purpose): string | null {
  if (entry.problem) return entry.problem.message;
  if (!entry.nameable) return "A reference can't name this key.";
  if (purpose === "condition" && entry.formula === null) return "A formula can't read this key.";
  // A comparison needs an operator: an object that's always there takes none (the review of revision 1).
  if (purpose === "condition" && opsFor(entry.types, entry.format, entry.missing || entry.nullable).length === 0) {
    return "It's always there, so there's nothing to compare: open it and pick one of its values.";
  }
  // A template's part is text, a number or a yes or no (template.part_not_scalar).
  if (purpose === "text" && entry.types.some((t) => t === "object" || t === "array")) return "Only text, numbers and yes-or-no values go into text.";
  return null;
}

interface Row {
  entry: ScopeEntry;
  level: number;
}

function useWhere(field: string): Where | null {
  const drawer = useDrawer();
  return drawer.revision === null
    ? null
    : { tenantId: drawer.tenantId, workflowId: drawer.workflowId, revision: drawer.revision, node: drawer.node.id, field };
}

/** One value: its name, its tags, its type; its children once opened. */
function Item({ row, where, purpose, open, active, setActive, toggle, pick, register, rows }: {
  row: Row; where: Where; purpose: Purpose; open: ReadonlySet<string>; active: string | null; setActive: (path: string) => void;
  toggle: (path: string) => void; pick: (entry: ScopeEntry) => void; register: (path: string, el: HTMLLIElement | null) => void;
  rows: (path: string, entries: ScopeEntry[] | null) => void;
}) {  // prettier-ignore
  const { entry, level } = row;
  const expanded = entry.children && open.has(entry.path);
  const children = useQuery({ ...scopeQuery(where, { kind: "under", path: entry.path }), enabled: expanded });
  // The same array while the answer is: the tree learns what's shown below each value only when it changes.
  const kids = useMemo(
    () => (expanded && children.data?.state === "ok" ? children.data.entries.filter((e) => e.parent === entry.path) : null),
    [expanded, children.data, entry.path],
  );
  useEffect(() => rows(entry.path, kids), [entry.path, kids, rows]);
  const why = refusal(entry, purpose);
  return (
    <li
      ref={(el) => register(entry.path, el)}
      role="treeitem" aria-level={level} aria-expanded={entry.children ? expanded : undefined}
      aria-selected={active === entry.path} aria-disabled={why !== null || undefined}
      tabIndex={active === entry.path ? 0 : -1} data-path={entry.path}
      onFocus={(e) => {
        if (e.target === e.currentTarget) setActive(entry.path);
      }}
      onClick={(e) => {
        e.stopPropagation();
        setActive(entry.path);
        if (why === null) pick(entry);
        else if (entry.children) toggle(entry.path);
      }}
      className="outline-none"
    >
      <div
        className={`flex min-h-8 items-center gap-2 px-3 py-1 text-body ${active === entry.path ? "bg-accent-soft outline outline-2 -outline-offset-2 outline-focus" : ""} ${why ? "text-muted" : ""}`}
        style={{ paddingLeft: `${12 + (level - 2) * 16}px` }}
      >
        <span aria-hidden="true" className="w-3 text-muted">{entry.children ? (expanded ? "▾" : "▸") : ""}</span>
        {/* A root is named by its path (`run.now`): in its group, its last part says it. */}
        <span className="font-mono text-small">{entry.parent === null ? (entry.path.split(".").at(-1) ?? entry.name) : entry.name}</span>
        {tagsOf(entry).map((t) => (
          <span key={t.text} className={`rounded-sm border px-1.5 text-meta ${t.conditional ? "border-dashed border-warn-line bg-warn-bg text-warn-ink" : "border-line-strong text-muted"}`}>
            {t.text}
          </span>
        ))}
        <span className="ml-auto text-meta text-muted">{typeWords(entry)}</span>
      </div>
      {why !== null && <p className="px-3 pb-1 text-meta text-muted" style={{ paddingLeft: `${28 + (level - 2) * 16}px` }}>{why}</p>}
      {expanded && children.isPending && <p className="px-3 py-1 text-small text-muted">Loading…</p>}
      {expanded && children.isError && (
        <p className="px-3 py-1 text-small text-danger">
          {children.error instanceof DraftMoved ? children.error.message : "Its values couldn't be loaded. Close and try again."}
        </p>
      )}
      {expanded && (
        <ul role="group">
          {(kids ?? []).map((k) => (
            <Item
              key={k.path} row={{ entry: k, level: level + 1 }} where={where} purpose={purpose} open={open} active={active}
              setActive={setActive} toggle={toggle} pick={pick} register={register} rows={rows}
            />
          ))}
        </ul>
      )}
      {expanded && children.data?.more && <p className="px-3 py-1 text-small text-muted">Showing the first 500.</p>}
    </li>
  );  // prettier-ignore
}

/** The trigger's own input isn't declared: its fields aren't known, so a path is typed (the owner's ruling: the
 * untyped trigger keeps its fallback). It's checked by the server before it's inserted. */
function TypedPath({ where, pick }: { where: Where; pick: (entry: ScopeEntry) => void }) {
  const [text, setText] = useState("trigger.");
  const [asked, setAsked] = useState<string | null>(null);
  const answer = useQuery({ ...scopeQuery(where, { kind: "at", path: asked ?? "" }), enabled: asked !== null });
  const id = useId();
  const entry = answer.data?.state === "ok" ? (answer.data.entries[0] ?? null) : null;
  const why =
    asked === null || answer.isPending ? null
    : answer.error instanceof DraftMoved ? answer.error.message
    : (answer.data?.problem?.message ?? answer.data?.reason ?? (entry ? refusal(entry, "text") : "Nothing is there."));  // prettier-ignore
  useEffect(() => {
    if (entry && asked !== null && why === null) {
      pick(entry);
      setAsked(null);
    }
  }, [entry, asked, why, pick]);
  const valid = parsePath(text)?.[0];
  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <p className="text-small text-muted">
        This workflow doesn&apos;t declare its trigger&apos;s input, so its fields aren&apos;t known: each is any value, may be
        missing and counts as sensitive. Type a path to use one:
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          id={id} type="text" value={text} spellCheck={false} aria-label="A path in the trigger"
          aria-describedby={why ? `${id}-why` : undefined} aria-invalid={why !== null}
          onChange={(e) => {
            setText(e.target.value);
            setAsked(null);
          }}
          className={`${controlClass(why !== null)} min-w-0 flex-1 font-mono text-small`}
        />
        <Button size="md" disabled={!valid || !("field" in valid) || valid.field !== "trigger"} onClick={() => setAsked(text)}>Insert</Button>
      </div>
      {why && <p id={`${id}-why`} className="text-small text-danger">{why}</p>}
    </div>
  );  // prettier-ignore
}

export function DataTree({ field, purpose, onPick, onClose }: {
  field: string; purpose: Purpose; onPick: (entry: ScopeEntry) => void; onClose: () => void;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const where = useWhere(field);
  const [find, setFind] = useState("");
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [active, setActive] = useState<string | null>(null);
  const items = useRef(new Map<string, HTMLLIElement>());
  const loaded = useRef(new Map<string, ScopeEntry[] | null>());
  const [, redraw] = useState(0);
  const findId = useId();
  // Opened, by "/" or "＋ Data", focus goes to its search: typing finds, ↓ enters the tree, Escape gives focus back.
  useEffect(() => document.getElementById(findId)?.focus(), [findId]);
  const top = useQuery({ ...scopeQuery(where ?? ({} as Where), find.trim() === "" ? { kind: "top" } : { kind: "find", text: find.trim() }), enabled: where !== null });
  const titleOf = (key: string) => {
    const node = drawer.steps.find((s) => s.key === key);
    return node?.title ?? null;
  };

  // The groups, each a step, the trigger, the run…, holding its roots' children; a root with none shows itself.
  const groups = (() => {
    const entries = top.data?.state === "ok" ? top.data.entries : [];
    const roots = entries.filter((e) => e.parent === null);
    const found = find.trim() !== "";
    const byGroup = new Map<string, { title: string; detail: string | null; rows: ScopeEntry[] }>();
    for (const e of found ? entries : roots) {
      const g = groupOf(e, titleOf);
      const group = byGroup.get(g.key) ?? { title: g.title, detail: g.detail, rows: [] };
      const kids = found ? [] : entries.filter((c) => c.parent === e.path);
      // A root's fields show under its group (a step's output, the trigger's input…); a root with none shows itself.
      group.rows.push(...(kids.length > 0 ? kids : [e]));
      byGroup.set(g.key, group);
    }
    return [...byGroup.entries()];
  })();

  /** The items shown, in order: what arrows move through. */
  const order = (): string[] => {
    const out: string[] = [];
    const walk = (rows: ScopeEntry[]) => {
      for (const e of rows) {
        out.push(e.path);
        if (open.has(e.path)) walk(loaded.current.get(e.path) ?? []);
      }
    };
    for (const [key, g] of groups) {
      out.push(`group:${key}`);
      walk(g.rows);
    }
    return out;
  };
  const entryAt = (path: string): ScopeEntry | null => {
    for (const [, g] of groups) {
      const hit = g.rows.find((r) => r.path === path);
      if (hit) return hit;
    }
    for (const list of loaded.current.values()) {
      const hit = list?.find((r) => r.path === path);
      if (hit) return hit;
    }
    return null;
  };
  const move = (path: string | undefined) => {
    if (!path) return;
    setActive(path);
    items.current.get(path)?.focus();
  };
  const toggle = (path: string) => setOpen((o) => {
    const next = new Set(o);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    return next;
  });  // prettier-ignore
  const pick = (entry: ScopeEntry) => {
    if (refusal(entry, purpose) === null) onPick(entry);
  };

  const onKey = (e: KeyboardEvent<HTMLUListElement>) => {
    const list = order();
    const at = active === null ? -1 : list.indexOf(active);
    const entry = active === null ? null : entryAt(active);
    switch (e.key) {
      case "ArrowDown":
        move(list[Math.min(list.length - 1, at + 1)]);
        break;
      case "ArrowUp":
        move(list[Math.max(0, at - 1)]);
        break;
      case "Home":
        move(list[0]);
        break;
      case "End":
        move(list[list.length - 1]);
        break;
      case "ArrowRight":
        if (entry?.children && !open.has(entry.path)) toggle(entry.path);
        else if (entry?.children) move(loaded.current.get(entry.path)?.[0]?.path);
        else return;
        break;
      case "ArrowLeft":
        if (entry && open.has(entry.path)) toggle(entry.path);
        else if (entry?.parent && items.current.has(entry.parent)) move(entry.parent);
        else return;
        break;
      case "Enter":
        if (entry) pick(entry);
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  const register = (path: string, el: HTMLLIElement | null) => {
    if (el) items.current.set(path, el);
    else items.current.delete(path);
  };
  const rows = useCallback((path: string, entries: ScopeEntry[] | null) => {
    if (loaded.current.get(path) !== entries) {
      loaded.current.set(path, entries);
      redraw((n) => n + 1);
    }
  }, []);
  const first = order()[0] ?? null;
  // The trigger's input isn't declared: nothing below it to browse, so a path is typed (the untyped trigger's fallback).
  const untyped = top.data?.state === "ok" && top.data.entries.some((e) => e.root === "trigger" && e.parent === null && !e.children);
  const current = active ?? first;

  return (
    <div
      role="dialog" aria-label="Insert data"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // closes the tree, not the drawer
          onClose();
        }
      }}
      className="flex flex-col gap-2 rounded-lg border border-line-strong bg-surface py-2"
    >
      <div className="flex items-center justify-between gap-2 px-3">
        <label htmlFor={findId} className="text-small font-semibold">Find data</label>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      <div className="px-3">
        <input
          id={findId} type="search" value={find} maxLength={100} placeholder="A field's name, like timezone"
          onChange={(e) => {
            setFind(e.target.value);
            setActive(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              move(order()[0]);
            }
          }}
          className={controlClass(false)}
        />
      </div>
      {where === null ? (
        <p className="px-3 text-small text-muted">A version&apos;s data isn&apos;t shown: open the draft to insert data.</p>
      ) : top.isPending ? (
        <p className="px-3 text-small text-muted">Loading the data available here…</p>
      ) : top.isError ? (
        <p className="px-3 text-small text-danger">
          {top.error instanceof DraftMoved ? top.error.message : "The data available here couldn't be loaded. Close and try again."}
        </p>
      ) : top.data.state === "unavailable" ? (
        <p className="px-3 text-small text-muted">{top.data.reason}</p>
      ) : groups.length === 0 ? (
        <p className="px-3 text-small text-muted">{find.trim() === "" ? "No data is available here yet." : "Nothing matches."}</p>
      ) : (
        <>
        {untyped && purpose === "text" && <TypedPath where={where} pick={pick} />}
        <ul role="tree" aria-label="Data available here" onKeyDown={onKey} className="max-h-96 overflow-y-auto">
          {groups.map(([key, g]) => (
            <li
              key={key} role="treeitem" aria-level={1} aria-expanded={true} aria-selected={current === `group:${key}`}
              tabIndex={current === `group:${key}` ? 0 : -1} ref={(el) => register(`group:${key}`, el)}
              onFocus={(e) => {
                if (e.target === e.currentTarget) setActive(`group:${key}`);
              }}
              className={`outline-none ${current === `group:${key}` ? "outline outline-2 -outline-offset-2 outline-focus" : ""}`}
            >
              <span className="block px-3 pt-2.5 pb-1 text-small font-semibold">
                {g.title}{g.detail && <span className="font-normal text-muted"> · {g.detail}</span>}
              </span>
              <ul role="group">
                {g.rows.map((e) => (
                  <Item
                    key={e.path} row={{ entry: e, level: 2 }} where={where} purpose={purpose} open={open} active={current}
                    setActive={setActive} toggle={toggle} pick={pick} register={register} rows={rows}
                  />
                ))}
              </ul>
            </li>
          ))}
        </ul>
        </>
      )}
      {top.data?.state === "ok" && top.data.more && <p className="px-3 text-small text-muted">More data matches: type more of its name.</p>}
      <p className="px-3 text-meta text-muted">↑ ↓ move · → open · Enter insert · Esc close</p>
    </div>
  );  // prettier-ignore
}
