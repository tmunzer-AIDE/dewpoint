// SPDX-License-Identifier: Apache-2.0
// A CSV run's file in the run form (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): what
// the workflow reads before a file, the file being read, why one can't be, and the file's column chosen for each of the
// workflow's, with how it was proposed. Once checked: its errors at a glance (counted by column and problem on the
// server, every error), or, every row passing, its first rows as written, the columns folded to a line.
import { useId, useState, type ChangeEvent, type DragEvent } from "react";
import { Button, LINK_BUTTON } from "../../components/Button";
import { controlClass } from "../../components/Field";
import { Table, Th } from "../../components/Table";
import { Tag } from "../../components/Tag";
import { mbOf } from "../../lib/csv";
import { cellWords, checkedWords, groupRows, holds, mappingWords, staleWords, type CsvColumnForm, type CsvPreview, type StartForm } from "../../lib/runForm";
import { listed } from "../editor/startInput";
import { unmapped, type CsvFile } from "./useCsvFile";

type Csv = NonNullable<StartForm["csv"]>;

const count = (x: number) => x.toLocaleString("en-US");
const sizeOf = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
const ROW_HEAD = "border-t border-line px-3 py-2.5 text-left align-top font-normal";
const CELL = "border-t border-line px-3 py-2.5 align-top";
const LISTED = 100; // the errors an answer lists row by row (the run form design §4.4); every one is counted

/** A declared column: its header, what it is, and its name when the header isn't it. */
function ColumnName({ c }: { c: CsvColumnForm }) {
  return (
    <>
      <span className="block">
        {c.header}
        {c.required && <> <Tag>required</Tag></>}
        {c.sensitive && <> <Tag>sensitive</Tag></>}
      </span>
      {c.name !== c.header && <span className="block font-mono text-meta text-muted">{c.name}</span>}
    </>
  );
}

/** The file chooser, as a button: a file chosen again is read again. */
function Choose({ label, onChoose }: { label: string; onChoose: (f: File) => void }) {
  const picked = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) onChoose(f);
  };
  return (
    <label className={`${LINK_BUTTON} cursor-pointer focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-focus`}>
      {label}
      <input type="file" accept=".csv,text/csv" className="sr-only" onChange={picked} />
    </label>
  );
}

function Reads({ csv }: { csv: Csv }) {
  return (
    <Table label="The columns it reads">
      <thead>
        <tr><Th>Column</Th><Th>Holds</Th></tr>
      </thead>
      <tbody>
        {csv.columns.map((c) => (
          <tr key={c.name}>
            <th scope="row" className={ROW_HEAD}><ColumnName c={c} /></th>
            <td className={`${CELL} text-small`}>{holds(c)}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Columns({ csv, file, onMap }: { csv: Csv; file: Extract<CsvFile, { phase: "staged" }>; onMap: (column: string, header: string) => void }) {
  const id = useId();
  const missing = new Set(unmapped(csv.columns, file.mapping));
  // A problem the server found under the columns chosen now: an answer for other columns says nothing of these.
  const problem = (c: CsvColumnForm) => file.shown.problems.find((p) => p.column === c.name && file.shown.mapping[c.name] === file.mapping[c.name]);
  return (
    <>
      <div className="flex flex-col gap-1">
        <h3 className="text-small font-semibold">Columns</h3>
        <p className="text-small text-muted">Each column the workflow reads, and the file&apos;s column it comes from.</p>
      </div>
      <Table label="Columns">
        <thead>
          <tr><Th>Column</Th><Th>From the file&apos;s</Th><Th>How</Th></tr>
        </thead>
        <tbody>
          {csv.columns.map((c, i) => {
            const chosen = file.mapping[c.name] ?? "";
            const error = missing.has(c.name) ? mappingWords("required_unmapped") : problem(c) ? mappingWords(problem(c)!.code) : undefined;
            const errorId = `${id}-${i}-err`;
            return (
              <tr key={c.name}>
                <th scope="row" className={ROW_HEAD}><ColumnName c={c} /></th>
                <td className={CELL}>
                  <select
                    aria-label={`${c.header}, from the file's column`} aria-invalid={!!error} aria-describedby={error ? errorId : undefined}
                    value={chosen} onChange={(e) => onMap(c.name, e.target.value)} className={`${controlClass(!!error)} min-w-40`}
                  >
                    <option value="">{c.required ? "Choose a column" : "Not used"}</option>
                    {chosen && !file.upload.headers.includes(chosen) && <option value={chosen}>{chosen}</option>}
                    {file.upload.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                  </select>
                  {error && <p id={errorId} className="mt-1 text-small text-danger">{error}</p>}
                </td>
                <td className={`${CELL} text-small text-muted`}>{file.how[c.name] ?? ""}</td>
              </tr>
            );  // prettier-ignore
          })}
        </tbody>
      </Table>
      {missing.size > 0 && <p className="text-small">No row is checked until every required column is mapped.</p>}
    </>
  );
}

/** A column's header, or the whole row's for a problem of no column (`cell_count`). */
const headerOf = (csv: Csv, name: string | null) => (name === null ? "The whole row" : (csv.columns.find((c) => c.name === name)?.header ?? name));

function Errors({ csv, shown, rows }: { csv: Csv; shown: CsvPreview; rows: number }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-small font-semibold text-danger">{checkedWords(shown, rows)}</p>
      <p className="text-small">The run can&apos;t start until every row passes. Fix the file, then choose it again.</p>
      <Table label="Errors by column">
        <thead>
          <tr><Th>Column</Th><Th>Problem</Th><Th>Rows</Th></tr>
        </thead>
        <tbody>
          {shown.error_groups.map((g) => (
            <tr key={`${g.column ?? ""}:${g.code}`}>
              <td className={`${CELL} text-small`}>{headerOf(csv, g.column)}</td>
              <td className={`${CELL} text-small`}>{cellWords(g.code)}</td>
              <td className={`${CELL} font-mono text-small`}>{groupRows(g)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      <details className="text-small">
        <summary className="min-h-6 cursor-pointer">{`Every error, row by row (${count(shown.error_count)})`}</summary>
        <Table label="Every error, row by row" className="mt-2">
          <thead>
            <tr><Th>Row</Th><Th>Column</Th><Th>Problem</Th></tr>
          </thead>
          <tbody>
            {shown.errors.map((e, i) => (
              <tr key={i}>
                <td className={`${CELL} font-mono`}>{count(e.row)}</td>
                <td className={CELL}>{headerOf(csv, e.column)}</td>
                <td className={CELL}>{cellWords(e.code)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </details>
      {shown.error_count > LISTED && (
        <p className="text-small text-muted">Above 100 errors, the first 100 are listed row by row; the counts above are of every error.</p>
      )}
    </div>
  );
}

/** The file's first rows as written, under the columns chosen (§5.3): a sensitive column is never in them. */
function Preview({ csv, shown, rows }: { csv: Csv; shown: CsvPreview; rows: number }) {
  const names = csv.columns.filter((c) => shown.preview.some((r) => c.name in r.cells));
  return (
    <div className="flex flex-col gap-2">
      <p className="text-small font-semibold text-ok">{checkedWords(shown, rows)}</p>
      <h3 className="text-small font-semibold">The file&apos;s first 5 rows, under these columns</h3>
      <Table label="The file's first 5 rows, under these columns">
        <thead>
          <tr><Th>#</Th>{names.map((c) => <Th key={c.name}>{c.header}</Th>)}</tr>
        </thead>
        <tbody>
          {shown.preview.map((r) => (
            <tr key={r.row}>
              <td className={`${CELL} font-mono text-small`}>{r.row}</td>
              {names.map((c) => <td key={c.name} className={`${CELL} text-small`}>{r.cells[c.name] ?? ""}</td>)}
            </tr>
          ))}
        </tbody>
      </Table>
      {shown.masked_columns.length > 0 && <p className="text-small text-muted">A column marked sensitive is never shown here.</p>}
    </div>
  );  // prettier-ignore
}

export function CsvPart({ form, csv, file, saveable, save, onChoose, onMap, onSave }: {
  form: StartForm; csv: Csv; file: CsvFile; saveable: boolean; save: boolean;
  onChoose: (f: File) => void; onMap: (column: string, header: string) => void; onSave: (save: boolean) => void;
}) {  // prettier-ignore
  const [unfolded, setUnfolded] = useState(false);
  const drop = (e: DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) onChoose(f);
  };
  if (file.phase === "reading") {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-small font-medium">{`${file.name} · ${sizeOf(file.size)}`}</p>
        <p className="text-small text-muted">Reading the file…</p>
      </div>
    );
  }
  if (file.phase === "staged") {
    const stale = file.upload.default_mapping.status === "stale";
    const rows = file.upload.row_count;
    const settled = !file.checking && !file.failed && unmapped(csv.columns, file.mapping).length === 0 && file.shown.problems.length === 0;
    const passes = settled && file.shown.error_count === 0;
    const mapped = csv.columns.filter((c) => file.mapping[c.name]);
    const unused = csv.columns.filter((c) => !file.mapping[c.name]).map((c) => c.header);
    const asSaved = mapped.length > 0 && mapped.every((c) => file.how[c.name] === "saved");
    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-small font-medium">{`${file.name} · ${count(rows)} rows · ${file.upload.headers.length} columns`}</p>
          <Choose label="Choose another file" onChoose={onChoose} />
        </div>
        {stale && <p className="text-small">{staleWords(form.version_number, file.upload.default_mapping.problems ?? [])}</p>}
        {passes && !unfolded ? (
          <p className="flex flex-wrap items-center gap-2 text-small">
            {`Columns: ${mapped.length} of ${csv.columns.length} mapped${asSaved ? ", as saved" : ""}${unused.length > 0 ? ` · ${listed(unused)} not used` : ""}`}
            <Button size="sm" onClick={() => setUnfolded(true)}>Change</Button>
          </p>
        ) : (
          <Columns csv={csv} file={file} onMap={onMap} />
        )}
        {saveable && (
          <label className="flex min-h-6 items-center gap-2 text-small">
            <input type="checkbox" checked={save} onChange={(e) => onSave(e.target.checked)} className="size-[16px] accent-accent" />
            Save these columns for this workflow&apos;s next CSV
          </label>
        )}
        {file.checking && <p className="text-small text-muted">Checking every row again with these columns…</p>}
        {file.failed && <p className="text-small text-danger">The rows couldn&apos;t be checked again with these columns. Change a column to check them again.</p>}
        {settled && (passes ? <Preview csv={csv} shown={file.shown} rows={rows} /> : file.shown.error_count > 0 && <Errors csv={csv} shown={file.shown} rows={rows} />)}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-small">This workflow starts from a CSV file: one run, one pass of its loop per row.</p>
      <div onDragOver={(e) => e.preventDefault()} onDrop={drop} className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line-strong px-4 py-6 text-center">
        <p className="flex flex-wrap items-center justify-center gap-2 text-small">
          Drop a CSV file here, or
          <Choose label="Choose a file" onChoose={onChoose} />
        </p>
        <p className="text-small text-muted">{`Up to ${count(csv.max_rows)} rows and ${mbOf(csv.max_bytes)} MB · comma, semicolon or tab separated · UTF-8`}</p>
      </div>
      {file.problem && (
        <p role="alert" className="text-small text-danger">
          {file.problem.words}
          {file.problem.code && <> <span className="font-mono">{file.problem.code}</span></>}
        </p>
      )}
      <h3 className="text-small font-semibold">The columns it reads</h3>
      <Reads csv={csv} />
    </div>
  );
}
