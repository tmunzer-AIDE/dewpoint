// SPDX-License-Identifier: Apache-2.0
// The condition builder (4c-2b, the mockups' builder board; the owner's rulings: the builder replaces Fixed for
// conditions, one level of groups, per-comparison guards with "is there" and "is missing" defined). It writes a
// formula (lib/builder.ts) and opens only one it wrote. Comparisons are picked from the data tree; each offers the
// operators its value's type takes. What can't be written yet (a number half typed, a write refused) is held whole,
// with why (ruling 18).
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import {
  eitherKind, isGroup, kindOfText, NO_VALUE, numeric, OP_WORDS, opsFor, read, valueProblem, write, type Condition, type Group,
  type Literal, type Op, type Row,
} from "../../../lib/builder";  // prettier-ignore
import { formula, formulaOf, kindOf } from "../../../lib/config";
import type { ScopeEntry } from "../../../lib/data";
import { useDrawer } from "./context";
import { DataTree } from "./DataTree";
import { PillButton, usePillEntry } from "./Pill";
import { PillDetails } from "./PillDetails";

const EMPTY: Condition = { match: "all", items: [] };

/** The condition a field's value is, when the builder can show it: none yet, or a formula it wrote. */
export function conditionOf(value: unknown): Condition | null {
  if (value === undefined || value === null) return EMPTY;
  if (kindOf(value) === "cel") return read(formulaOf(value));
  return null;
}

/** Why a row's comparison can't be written, or null. */
const rowProblem = (r: Row): string | null =>
  NO_VALUE.has(r.op) || r.value === null ? null : valueProblem(r.value, r.path);

/** What's said under a comparison: what its guards make of missing data (the mockups' notes). */
function noteOf(r: Row): string | null {
  if (r.op === "is_there" || r.op === "is_missing") return null;
  if (r.guards.length > 0) return "If any part of its path is missing, null or another shape, this comparison is false.";
  if (r.nullTest) return "If it's null, this comparison is false.";
  return null;
}

function Match({ label, match, disabled, onChange }: {
  label: string; match: "all" | "any"; disabled: boolean; onChange: (m: "all" | "any") => void;
}) {  // prettier-ignore
  return (
    <div role="group" aria-label={label} className="inline-flex gap-px overflow-hidden rounded-lg border border-line-strong bg-line-strong">
      {(["all", "any"] as const).map((m) => (
        <button
          key={m} type="button" aria-pressed={match === m} disabled={disabled} onClick={() => match !== m && onChange(m)}
          className={`min-h-8 px-3 text-small disabled:bg-disabled-bg disabled:text-muted ${match === m ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          {m === "all" ? "all of these" : "any of these"}
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

const EQUALITY: ReadonlySet<Op> = new Set(["is", "is_not"]);

/** "is" and "is not" on a value that may be text or a number (#85): in a comparison made here, what's typed says which,
 * until the person picks one; a pick, and a comparison read back, keep their kind. */
function CompareAs({ label, kind, disabled, onChange }: {
  label: string; kind: Literal["kind"]; disabled: boolean; onChange: (kind: Literal["kind"]) => void;
}) {  // prettier-ignore
  return (
    <div role="group" aria-label={`Compare as, ${label}`} className="inline-flex gap-px overflow-hidden rounded-lg border border-line-strong bg-line-strong">
      {(["text", "number"] as const).map((k) => (
        <button
          key={k} type="button" aria-pressed={kind === k} disabled={disabled} onClick={() => kind !== k && onChange(k)}
          className={`min-h-8 px-3 text-small disabled:bg-disabled-bg disabled:text-muted ${kind === k ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          as {k}
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

type Opened = "details" | "tree";

function RowView({ row, label, field, disabled, follows, opened, onOpened, onPicked, onChange, onRemove, onReplace }: {
  row: Row; label: string; field: string; disabled: boolean; follows: boolean; opened: Opened | null;
  onOpened: (o: Opened | null) => void; onPicked: () => void; onChange: (r: Row) => void; onRemove: () => void;
  onReplace: (entry: ScopeEntry) => void;
}) {  // prettier-ignore
  const { entry, shown } = usePillEntry(row.path, field);
  // The previous revision's facts while a save's are asked: the choice stays, and what's typed follows (the review).
  const facts = entry ?? shown;
  // Its pill opens its details, as a pill in text does, without a default: the comparison's guards decide missing data
  // (#85). Replace… opens the tree here; closed, focus goes back to the pill. The builder keeps what's open.
  const pill = useRef<HTMLButtonElement | null>(null);
  const back = () => {
    onOpened(null);
    pill.current?.focus();
  };
  const ops = entry ? opsFor(entry.types, entry.format, entry.missing || entry.nullable || row.guards.length > 0) : [row.op];
  const problem = rowProblem(row);
  const note = noteOf(row);
  const problemId = useId();
  const either = facts !== null && eitherKind(facts.types) && EQUALITY.has(row.op) && row.value !== null;
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-1.5 border-t border-line py-2.5">
      <div>
        <PillButton
          pill={{ ref: row.path }} entry={shown} index={0} buttonRef={(el) => void (pill.current = el)}
          onOpen={() => onOpened(opened === "details" ? null : "details")}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={`Comparison, ${label}`} value={row.op} disabled={disabled}
          onChange={(e) => {
            const op = e.target.value as Op;
            const text = row.value?.text ?? "";
            // To "is" or "is not": a picked kind stays; a comparison made here follows what's typed.
            const kind =
              (facts && numeric(facts.types)) || ["more", "less", "at_least", "at_most"].includes(op) ? "number"
              : facts && eitherKind(facts.types) && EQUALITY.has(op) ? (!follows && row.value ? row.value.kind : kindOfText(text))
              : "text";  // prettier-ignore
            const value: Literal | null = NO_VALUE.has(op) ? null : { kind, text };
            onChange({ ...row, op, value });
          }}
          className={`${controlClass(false)} w-auto`}
        >
          {(ops.includes(row.op) ? ops : [row.op, ...ops]).map((op) => <option key={op} value={op}>{OP_WORDS[op]}</option>)}
        </select>
        {row.value !== null && (
          <input
            type="text" aria-label={`Value, ${label}`} value={row.value.text} disabled={disabled} spellCheck={false}
            aria-invalid={problem !== null} aria-describedby={problem ? problemId : undefined}
            onChange={(e) => {
              const text = e.target.value;
              onChange({ ...row, value: { kind: either && follows ? kindOfText(text) : row.value!.kind, text } });
            }}
            className={`${controlClass(problem !== null)} w-auto min-w-0 flex-1`}
          />
        )}
        {either && (
          <CompareAs
            label={label} kind={row.value!.kind} disabled={disabled}
            onChange={(kind) => {
              onPicked();
              onChange({ ...row, value: { kind, text: row.value!.text } });
            }}
          />
        )}
        {!disabled && <Button size="sm" aria-label={`Remove ${label.toLowerCase()}`} onClick={onRemove}>×</Button>}
      </div>
      {problem && <p id={problemId} className="text-small text-danger">{problem}</p>}
      {note && <p className="text-meta text-muted">{note}</p>}
      {opened === "details" && (
        <PillDetails
          field={field} pill={{ ref: row.path }} defaults={false} onDefault={() => undefined}
          onReplace={() => onOpened("tree")} onRemove={onRemove} onClose={back}
        />
      )}
      {opened === "tree" && (
        <DataTree
          field={field} purpose="condition" onClose={back}
          onPick={(picked) => {
            onOpened(null);
            onReplace(picked);
          }}
        />
      )}
    </div>
  );  // prettier-ignore
}

/** The comparison on another value (#85): its operator and value kept when the new value takes that operator, else
 * started again on it, as a new comparison is. Where the new value may be either, its kind stays. */
function replaced(row: Row, entry: ScopeEntry): Row {
  const f = entry.formula!;
  if (!opsFor(entry.types, entry.format, entry.missing || entry.nullable).includes(row.op)) return rowFor(entry);
  const was = row.value;
  const kind: Literal["kind"] | null =
    was === null ? null
    : numeric(entry.types) || ["more", "less", "at_least", "at_most"].includes(row.op) ? "number"
    : eitherKind(entry.types) && EQUALITY.has(row.op) ? was.kind
    : "text";  // prettier-ignore
  return { ...row, path: entry.path, guards: f.guards, nullTest: f.null_test, value: was === null || kind === null ? null : { kind, text: was.text } };
}

/** The places after a removal (item `i`, or row `k` of group `i`): the one removed goes, those after it move up. */
function shifted(places: ReadonlySet<string>, i: number, k?: number): Set<string> {
  const out = new Set<string>();
  for (const place of places) {
    const [a, b] = place.split(".").map(Number) as [number, number | undefined];
    if (k === undefined) {
      if (a === i) continue;
      out.add(a < i ? place : b === undefined ? `${a - 1}` : `${a - 1}.${b}`);
    } else {
      if (a === i && b === k) continue;
      out.add(a === i && b !== undefined && b > k ? `${a}.${b - 1}` : place);
    }
  }
  return out;
}

/** A comparison of an entry picked from the tree, with its first operator. */
function rowFor(entry: ScopeEntry): Row {
  const f = entry.formula!;
  const op = opsFor(entry.types, entry.format, entry.missing || entry.nullable)[0]!;
  const value: Literal | null = NO_VALUE.has(op) ? null : { kind: numeric(entry.types) ? "number" : "text", text: "" };
  return { path: entry.path, op, value, guards: f.guards, nullTest: f.null_test };
}

export function ConditionBuilder({ spec, value, disabled, onChange }: {
  spec: { pointer: string; path: (string | number)[]; label: string; entry: boolean };
  value: unknown; disabled: boolean; onChange: (next: unknown, typed: boolean) => string | null;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const held = drawer.held("condition", spec.pointer);
  const c: Condition = held?.condition ?? conditionOf(value) ?? EMPTY;
  // What's open, one at a time (the review of #85): the tree where a picked comparison goes (the top, a new group whose
  // first it is, a group), or a comparison's details or its Replace tree, by its place ("2", "1.3"). A removal closes it.
  const [panel, setPanel] = useState<{ adding: number | "top" | "group" } | { at: string; opened: Opened } | null>(null);
  const adding = panel !== null && "adding" in panel ? panel.adding : null;
  const setAdding = (at: number | "top" | "group") => setPanel({ adding: at });
  // The comparisons made here, by place: in those, what's typed says text or a number until the person picks (#85). A
  // removal moves the places after it; a condition changed from elsewhere (an undo, Formula) starts again with none.
  const following = useRef(new Set<string>());
  const written = useRef<string | null | undefined>(null); // null: nothing drawn yet
  const now = write(c);
  if (written.current !== now) {
    following.current = new Set();
    written.current = now;
  }
  const fixed = typeof value === "boolean" ? value : null;
  // Where focus goes once the change is drawn, never to <body> (the final review): the button that opened the tree,
  // after Escape; a picked comparison's operator; "＋ Condition" after a removal. Tried twice, then dropped, so a
  // request never moves focus later, as one types (M66).
  const box = useRef<HTMLDivElement>(null);
  const focusAfter = useRef<{ selector: string; tries: number } | null>(null);
  const focusOn = (selector: string) => void (focusAfter.current = { selector, tries: 2 });
  useEffect(() => {
    const want = focusAfter.current;
    if (!want) return;
    const el = box.current?.querySelector<HTMLElement>(want.selector);
    if (el || --want.tries === 0) focusAfter.current = null;
    el?.focus();
  });
  const comparison = (label: string) => `select[aria-label="Comparison, ${label}"]`;

  /** Writes the condition when every comparison can be; else holds it whole, with why. */
  const put = (next: Condition, typed: boolean) => {
    const problem = next.items.flatMap((x) => (isGroup(x) ? x.rows : [x])).map(rowProblem).find((p) => p !== null) ?? null;
    const text = write(next);
    written.current = text; // its own change: the places it follows stay
    const why = problem ?? onChange(text === undefined ? undefined : formula(text), typed);
    if (why === null) drawer.release("condition", spec.pointer);
    else drawer.hold("condition", spec.pointer, { path: spec.path, label: spec.label, text: text ?? "", condition: next, why, entry: spec.entry });
  };  // prettier-ignore
  const setItem = (i: number, item: Row | Group, typed = false) =>
    put({ ...c, items: c.items.map((x, j) => (j === i ? item : x)) }, typed);
  const removeItem = (i: number) => {
    focusOn('[data-add="top"]');
    setPanel(null);
    following.current = shifted(following.current, i);
    put({ ...c, items: c.items.filter((_, j) => j !== i) }, false);
  };
  /** A comparison's row, with what the builder keeps of it: whether it follows what's typed, and what's open. */
  const rowProps = (place: string) => ({
    follows: following.current.has(place),
    opened: panel !== null && "at" in panel && panel.at === place ? panel.opened : null,
    onOpened: (o: Opened | null) => setPanel(o === null ? null : { at: place, opened: o }),
    onPicked: () => void following.current.delete(place),
  });
  const text = write(c);

  return (
    <div ref={box} className="flex flex-col gap-2">
      {fixed !== null && c.items.length === 0 && (
        <p className="text-small text-muted">{fixed ? "Always true." : "Always false."} Add a condition to decide on data instead.</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-small">True when</span>
        {/* With fewer than two, all and any write the same: the choice waits for a second. */}
        <Match label={`Match, ${spec.label}`} match={c.match} disabled={disabled || c.items.length < 2} onChange={(match) => put({ ...c, match }, false)} />
      </div>
      <div className="flex flex-col">
        {c.items.map((x, i) =>
          isGroup(x) ? (
            <div key={i} role="group" aria-label={`Group ${i + 1}`} className="flex flex-col gap-1.5 border-t border-line py-2.5 pl-4">
              <div className="flex flex-wrap items-center gap-2">
                <Match label={`Match in group ${i + 1}`} match={x.match} disabled={disabled || x.rows.length < 2} onChange={(match) => setItem(i, { ...x, match })} />
                {!disabled && <Button size="sm" onClick={() => removeItem(i)}>Remove group</Button>}
              </div>
              {x.rows.map((r, k) => (
                <RowView
                  key={k} row={r} label={`Condition ${i + 1}.${k + 1}`} field={spec.pointer} disabled={disabled} {...rowProps(`${i}.${k}`)}
                  onChange={(next) => setItem(i, { ...x, rows: x.rows.map((y, m) => (m === k ? next : y)) }, true)}
                  onReplace={(entry) => {
                    focusOn(comparison(`Condition ${i + 1}.${k + 1}`));
                    setItem(i, { ...x, rows: x.rows.map((y, m) => (m === k ? replaced(r, entry) : y)) });
                  }}
                  onRemove={() => {
                    // Its only comparison gone, the group goes too (an empty group writes nothing): "＋ Condition" below.
                    if (x.rows.length === 1) return removeItem(i);
                    focusOn(`[data-add="${i}"]`);
                    setPanel(null);
                    following.current = shifted(following.current, i, k);
                    setItem(i, { ...x, rows: x.rows.filter((_, m) => m !== k) });
                  }}
                />
              ))}
              {!disabled && <div><Button size="sm" data-add={i} onClick={() => setAdding(i)}>＋ Condition</Button></div>}
            </div>
          ) : (
            <RowView
              key={i} row={x} label={`Condition ${i + 1}`} field={spec.pointer} disabled={disabled} {...rowProps(`${i}`)}
              onChange={(next) => setItem(i, next, true)} onRemove={() => removeItem(i)}
              onReplace={(entry) => {
                focusOn(comparison(`Condition ${i + 1}`));
                setItem(i, replaced(x, entry));
              }}
            />
          ),
        )}
      </div>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" aria-haspopup="dialog" data-add="top" onClick={() => setAdding("top")}>＋ Condition</Button>
          <Button size="sm" aria-haspopup="dialog" data-add="group" onClick={() => setAdding("group")}>＋ Group</Button>
        </div>
      )}
      {adding !== null && (
        <DataTree
          field={spec.pointer} purpose="condition"
          onClose={() => {
            focusOn(`[data-add="${adding}"]`);
            setPanel(null);
          }}
          onPick={(entry) => {
            const row = rowFor(entry);
            const at = adding;
            setPanel(null);
            if (at === "top") {
              focusOn(comparison(`Condition ${c.items.length + 1}`));
              following.current.add(`${c.items.length}`);
              put({ ...c, items: [...c.items, row] }, false);
            } else if (at === "group") {
              focusOn(comparison(`Condition ${c.items.length + 1}.1`));
              following.current.add(`${c.items.length}.0`);
              put({ ...c, items: [...c.items, { match: "any", rows: [row] }] }, false);
            } else {
              const g = c.items[at];
              if (g && isGroup(g)) {
                focusOn(comparison(`Condition ${at + 1}.${g.rows.length + 1}`));
                following.current.add(`${at}.${g.rows.length}`);
                setItem(at, { ...g, rows: [...g.rows, row] });
              }
            }
          }}
        />
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small text-muted">
        <dt className="font-semibold text-ink">is there</dt>
        <dd>Present and not null, with every part of the path above it present too. Empty text, 0 and false are there.</dd>
        <dt className="font-semibold text-ink">is missing</dt>
        <dd>The opposite: it, or a part of the path above it, is absent or null.</dd>
        <dt className="font-semibold text-ink">other tests</dt>
        <dd>Each guards its own data and is false when that data is missing, so a missing value never decides a group for the others.</dd>
      </dl>
      {text !== undefined && (
        <details>
          <summary className="cursor-pointer text-small">The formula it writes</summary>
          <pre className="mt-1 overflow-x-auto rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-meta">{text}</pre>
        </details>
      )}
    </div>
  );  // prettier-ignore
}
