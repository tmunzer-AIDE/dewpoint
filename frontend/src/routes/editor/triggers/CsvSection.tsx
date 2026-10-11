// SPDX-License-Identifier: Apache-2.0
// The input's CSV file (4c-3b; the InputCsv and InputEdit boards): its typed columns, each edited in its row, and its
// limits. A header, a name or a limit a save wouldn't take is held with why (ruling 113), and one typed where the file
// has since changed (a column removed before it, an undo) is written only by Apply here; the server's problems show at
// their column, and a required column's default offers its two fixes. Focus goes back where it was once a column's
// editor closes (the review of revision 1).
import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Field, Select } from "../../../components/Field";
import { Table, Td, Th } from "../../../components/Table";
import {
  CSV_TYPES, MAX_ROWS, addColumn, csvOf, mbOf, removeColumn, rowsLimit, rulesOf, setColumn, setLimits, sizeLimit, textProblem, typeLabel,
  type CsvColumn, type CsvSettings, type CsvType,
} from "../../../lib/csv";  // prettier-ignore
import { setSettings } from "../../../lib/input";
import { parseNumber } from "../../../lib/unapplied";
import type { Diagnostic, GraphDoc } from "../../../lib/workflows";
import { useText } from "../drawer/scalars";
import type { FocusAt } from "./InputSection";
import { useTriggers } from "./context";
import { Check, Problems, StaleEdit, Values, heldWhy, problemsAt, writeTyped } from "./parts";

const AT = "/settings/csv";
const columnAt = (i: number) => `${AT}/columns/${i}`;
const NO_CHOICE = "A sensitive column can't be a Choice: its values would be written into the workflow.";

/** What `make` makes of the latest draft's CSV file; the draft as it is when it has none, or `make` changes nothing. */
const onCsv = (make: (csv: CsvSettings) => CsvSettings | null | undefined) => (d: GraphDoc): GraphDoc => {
  const csv = csvOf(d);
  const next = csv ? make(csv) : null;
  return next === null || next === undefined || next === csv ? d : setSettings(d, { csv: next });
};

/** A column's header or name: written as typed while a save takes it, held with why when it wouldn't. */
function ColumnText({ i, column, k, label }: { i: number; column: CsvColumn; k: "header" | "name"; label: string }) {
  const t = useTriggers();
  const at = `${columnAt(i)}/${k}`;
  const held = t.actions.held("text", at);
  return (
    <div className="flex flex-col gap-1.5">
      <Field
        label={label} value={held?.text ?? column[k]} disabled={!t.editable} spellCheck={false} error={heldWhy(t.actions, "text", at) ?? undefined}
        onChange={(e) => {
          const text = e.target.value;
          writeTyped(t.actions, "text", at, { path: ["csv", "columns", i, k], label: `Column ${i + 1}'s ${k}`, text }, textProblem(k, text), () =>
            t.actions.update(onCsv((csv) => setColumn(csv, i, { [k]: text })), null, at),
          );
        }}
      />
      <StaleEdit kind="text" at={at} />
    </div>
  );  // prettier-ignore
}

function ColumnDefault({ i, column, set }: { i: number; column: CsvColumn; set: (patch: Partial<CsvColumn>, key: string) => void }) {
  const t = useTriggers();
  const label = "Default (an empty cell gets it)";
  if (column.sensitive) return <Field label={label} value="" disabled />;
  if (column.type === "boolean" || column.type === "enum") {
    const options = column.type === "boolean" ? [["true", "Yes"], ["false", "No"]] : (column.values ?? []).map((v) => [JSON.stringify(v), v]);
    return (
      <Select
        label={label} value={"default" in column ? JSON.stringify(column.default) : ""} disabled={!t.editable}
        onChange={(e) => set({ default: e.target.value === "" ? undefined : (JSON.parse(e.target.value) as unknown) }, "default")}
      >
        <option value="">None</option>
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </Select>
    );  // prettier-ignore
  }
  return <TypedDefault i={i} column={column} label={label} />;
}

const shownDefault = (v: unknown) => (typeof v === "string" || typeof v === "number" ? String(v) : "");

/** A text or number column's default as typed: its own text kept while it still means the value ("2." while 2.5 is
 * typed: the final review), written when a save takes it, held with why when it wouldn't. */
function TypedDefault({ i, column, label }: { i: number; column: CsvColumn; label: string }) {
  const t = useTriggers();
  const at = `${columnAt(i)}/default`;
  const held = t.actions.held("number", at);
  const numeric = column.type === "integer" || column.type === "number";
  const [typed, setTyped] = useText(
    column.default,
    shownDefault,
    (text, v) => {
      if (!numeric) return text === shownDefault(v);
      const parsed = parseNumber(text, column.type === "integer");
      return "value" in parsed && parsed.value === v;
    },
    held?.text,
  );
  return (
    <div className="flex flex-col gap-1.5">
      <Field
        label={label} value={held?.text ?? typed} disabled={!t.editable} spellCheck={false} error={heldWhy(t.actions, "number", at) ?? undefined}
        onChange={(e) => {
          const text = e.target.value;
          setTyped(text);
          const holding = { path: ["csv", "columns", i, "default"], label: `Column ${i + 1}'s default`, text, whole: column.type === "integer" };
          if (!numeric) {
            // Text is written as typed, unless an edit is held here: typed for another column, it's never written over
            // this one unasked (the review of revision 2).
            const write = () => t.actions.update(onCsv((csv) => setColumn(csv, i, { default: text === "" ? undefined : text })), null, at);
            return held ? writeTyped(t.actions, "number", at, holding, null, write) : void write();
          }
          const parsed = parseNumber(text, column.type === "integer");
          writeTyped(t.actions, "number", at, holding, "problem" in parsed ? parsed.problem : null, () =>
            "problem" in parsed ? null : t.actions.update(onCsv((csv) => setColumn(csv, i, { default: parsed.value })), null, at),
          );
        }}
      />
      <StaleEdit kind="number" at={at} onDiscard={() => setTyped(shownDefault(column.default))} />
    </div>
  );  // prettier-ignore
}

/** The fixes a column's problem offers, where there are some (the InputEdit board). */
function Fixes({ d, set }: { d: Diagnostic; set: (patch: Partial<CsvColumn>, key: string) => void }) {
  if (d.code !== "csv.required_default") return null;
  return (
    <span className="flex flex-wrap gap-2">
      <Button size="sm" onClick={() => set({ default: undefined }, "default")}>Clear the default</Button>
      <Button size="sm" onClick={() => set({ required: false }, "required")}>Make it optional</Button>
    </span>
  );
}

function ColumnEditor({ i, column, last, onClose }: { i: number; column: CsvColumn; last: boolean; onClose: (removed?: boolean) => void }) {
  const t = useTriggers();
  const disabled = !t.editable;
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.querySelector("input")?.focus(), []);
  const set = (patch: Partial<CsvColumn>, key: string) =>
    t.actions.update(onCsv((csv) => setColumn(csv, i, patch)), null, `${columnAt(i)}/${key}`);
  const problems = problemsAt(t.check, columnAt(i));
  return (
    <div
      ref={box} role="group" aria-label={`The column ${column.header}`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="flex flex-col gap-3 rounded-lg border border-line-strong p-3"
    >
      <ColumnText i={i} column={column} k="header" label="Header in the file" />
      <ColumnText i={i} column={column} k="name" label="Name" />
      <Select label="Type" value={column.type} disabled={disabled} hint={column.sensitive ? NO_CHOICE : undefined} onChange={(e) => set({ type: e.target.value as CsvType }, "type")}>
        {CSV_TYPES.map((x) => <option key={x.value} value={x.value} disabled={x.value === "enum" && column.sensitive === true}>{x.label}</option>)}
      </Select>
      <Check label="Required" checked={column.required === true} disabled={disabled} hint="A row with this cell empty is refused." onChange={(required) => set({ required }, "required")} />
      <Check
        label="Sensitive" checked={column.sensitive === true} disabled={disabled || column.type === "enum"}
        hint={column.type === "enum" ? NO_CHOICE : "Kept apart from run history; it has no default."} onChange={(sensitive) => set({ sensitive }, "sensitive")}
      />
      {column.type === "enum" && (
        <Values
          label={`The column ${column.header}'s values`} values={column.values ?? []} disabled={disabled}
          hint={`A cell must be one of these, as written. Up to 200. ${NO_CHOICE}`} onChange={(values) => set({ values }, "values")}
        />
      )}
      <ColumnDefault i={i} column={column} set={set} />
      {problems.map((d, n) => (
        <div key={`${d.code}:${n}`} className="flex flex-col gap-2">
          <Problems problems={[d]} />
          {!disabled && <Fixes d={d} set={set} />}
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" onClick={() => onClose()}>Done</Button>
        {!disabled && (
          <Button
            size="sm" variant="danger-outline" disabled={last}
            onClick={() => {
              t.actions.discard(columnAt(i));
              const said = `Removed the column ${column.header}.`;
              if (t.actions.update(onCsv((csv) => removeColumn(csv, i)), said) === null) onClose(true);
            }}
          >
            Remove column
          </Button>
        )}
      </div>
      {last && !disabled && <p className="text-small text-muted">A CSV file keeps one column at least: remove the file instead.</p>}
    </div>
  );  // prettier-ignore
}

/** Most rows, or the largest file in MB: written while a save takes it, held with why when it wouldn't. */
function Limit({ k, label, csv }: { k: "max_rows" | "max_bytes"; label: string; csv: CsvSettings }) {
  const t = useTriggers();
  const at = `${AT}/${k}`;
  const held = t.actions.held("limit", at);
  const readLimit = (text: string) => (k === "max_bytes" ? sizeLimit(text) : rowsLimit(text));
  const show = (v: unknown) => (typeof v === "number" ? (k === "max_bytes" ? mbOf(v) : String(v)) : "");
  // Its own text, kept while it still means the limit ("1." while 1.5 is typed: the final review).
  const [typed, setTyped] = useText(csv[k], show, (text, v) => {
    const read = readLimit(text);
    return "value" in read && read.value === v;
  }, held?.text);  // prettier-ignore
  return (
    <div className="flex flex-col gap-1.5">
      <Field
        label={label} value={held?.text ?? typed} disabled={!t.editable} inputMode="decimal" error={heldWhy(t.actions, "limit", at) ?? undefined}
        placeholder={k === "max_bytes" ? "5" : String(MAX_ROWS)}
        onChange={(e) => {
          const text = e.target.value;
          setTyped(text);
          const read = readLimit(text);
          writeTyped(t.actions, "limit", at, { path: ["csv", k], label, text }, "problem" in read ? read.problem : null, () =>
            "problem" in read ? null : t.actions.update(onCsv((csv) => setLimits(csv, { [k]: read.value })), null, at),
          );
        }}
      />
      <StaleEdit kind="limit" at={at} onDiscard={() => setTyped(show(csv[k]))} />
    </div>
  );  // prettier-ignore
}

export function CsvSection({ csv, focusAt, back }: { csv: CsvSettings; focusAt: FocusAt; back: (...keys: string[]) => void }) {
  const t = useTriggers();
  const [editing, setEditing] = useState<number | null>(null);
  useEffect(() => {
    const m = focusAt ? /^\/settings\/csv\/columns\/(\d+)/.exec(focusAt.pointer) : null;
    if (m) setEditing(Number(m[1]));
  }, [focusAt]);
  const columnProblems = csv.columns.flatMap((c, i) => (editing === i ? [] : problemsAt(t.check, columnAt(i)).map((d) => ({ i, c, d }))));
  return (
    <div role="group" aria-labelledby="triggers-csv" className="flex flex-col gap-3">
      <h4 id="triggers-csv" className="text-small font-semibold">CSV file</h4>
      <p className="text-small text-muted">
        Started by hand with a file: one run reads its rows as <code className="font-mono">trigger.rows</code> and their count as{" "}
        <code className="font-mono">trigger.row_count</code>.
      </p>
      <Problems problems={problemsAt(t.check, AT, true)} />
      <Table label="CSV columns">
        <thead>
          <tr><Th>Header</Th><Th>Name</Th><Th>Type</Th><Th>Rules</Th><Th><span className="sr-only">Actions</span></Th></tr>
        </thead>
        <tbody>
          {csv.columns.map((c, i) =>
            editing === i ? (
              <tr key={i}>
                <Td colSpan={5}>
                  <ColumnEditor
                    i={i} column={c} last={csv.columns.length === 1}
                    onClose={(removed) => {
                      setEditing(null);
                      back(removed ? "add-column" : `column:${i}`);
                    }}
                  />
                </Td>
              </tr>
            ) : (
              <tr key={i}>
                <Td>{c.header}</Td>
                <Td className="font-mono text-small">{c.name}</Td>
                <Td>{typeLabel(c.type)}</Td>
                <Td className="text-small text-muted">{rulesOf(c)}</Td>
                <Td className="text-right">
                  {t.editable && <Button size="sm" aria-label={`Edit ${c.header}`} data-back={`column:${i}`} onClick={() => setEditing(i)}>Edit</Button>}
                </Td>
              </tr>
            ),
          )}
        </tbody>
      </Table>
      {columnProblems.map(({ i, c, d }, n) => (
        <div key={n} className="flex flex-wrap items-center gap-2">
          <p className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>{c.header}: {d.message}</p>
          {t.editable && <Button size="sm" onClick={() => setEditing(i)}>Edit {c.header}</Button>}
        </div>
      ))}
      <p className="text-small text-muted">Types: {CSV_TYPES.map((x) => x.label).join(", ")}.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Limit k="max_rows" label="Most rows" csv={csv} />
        <Limit k="max_bytes" label="Largest file (MB)" csv={csv} />
      </div>
      <p className="text-small text-muted">At most 10,000 rows and 5 MB, the platform&apos;s limits; lower them here if you like.</p>
      {t.editable && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" data-back="add-column" onClick={() => t.actions.update(onCsv(addColumn), "Added a column to the CSV file.")}>＋ Column</Button>
          <Button
            size="sm" variant="danger-outline"
            onClick={() => {
              t.actions.discard(AT);
              if (t.actions.update((d) => setSettings(d, { csv: undefined }), "Removed the CSV file. Undo brings it back.") === null) back("csv");
            }}
          >
            Remove the CSV file
          </Button>
        </div>
      )}
      <p className="text-small text-muted">
        A workflow that takes a CSV file runs only when started by hand with a file: a schedule, a webhook or another workflow can&apos;t give it rows.
      </p>
    </div>
  );  // prettier-ignore
}
