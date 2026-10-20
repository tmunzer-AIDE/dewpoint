// SPDX-License-Identifier: Apache-2.0
// A CSV run's file in the run form (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): what
// the workflow reads before a file, the file being read, why one can't be, and the file's column chosen for each of the
// workflow's, with how it was proposed.
import { useId, type ChangeEvent, type DragEvent } from "react";
import { LINK_BUTTON } from "../../components/Button";
import { controlClass } from "../../components/Field";
import { Table, Th } from "../../components/Table";
import { Tag } from "../../components/Tag";
import { mbOf } from "../../lib/csv";
import { holds, mappingWords, staleWords, type CsvColumnForm, type StartForm } from "../../lib/runForm";
import { unmapped, type CsvFile } from "./useCsvFile";

type Csv = NonNullable<StartForm["csv"]>;

const count = (x: number) => x.toLocaleString("en-US");
const sizeOf = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
const ROW_HEAD = "border-t border-line px-3 py-2.5 text-left align-top font-normal";
const CELL = "border-t border-line px-3 py-2.5 align-top";

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

export function CsvPart({ form, csv, file, onChoose, onMap }: {
  form: StartForm; csv: Csv; file: CsvFile; onChoose: (f: File) => void; onMap: (column: string, header: string) => void;
}) {  // prettier-ignore
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
    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-small font-medium">{`${file.name} · ${count(file.upload.row_count)} rows · ${file.upload.headers.length} columns`}</p>
          <Choose label="Choose another file" onChoose={onChoose} />
        </div>
        {stale && <p className="text-small">{staleWords(form.version_number, file.upload.default_mapping.problems ?? [])}</p>}
        <Columns csv={csv} file={file} onMap={onMap} />
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
