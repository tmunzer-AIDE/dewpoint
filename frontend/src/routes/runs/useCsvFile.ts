// SPDX-License-Identifier: Apache-2.0
// A CSV run's file (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): chosen, uploaded as it
// is, read by the server against the version's columns, the file's columns proposed for them (saved, or the same names),
// and the person's choice of each. A changed choice has every row checked again (B11): one check at a time, and only the
// last change's (§7), its answer shown only while it's the choice shown. A file a start used, or kept past its hour, is
// chosen again.
import { useEffect, useRef, useState } from "react";
import { announce } from "../../lib/announce";
import {
  checkedWords, previewCsv, refusalOf, uploadCsv, uploadProblem, type CsvColumnForm, type CsvPreview, type CsvUpload, type Mapping,
  type StartForm,
} from "../../lib/runForm";  // prettier-ignore

/** How a column's choice was made: proposed from the saved columns, by the same name, or left out; the person's own
 * choice says nothing. */
export type How = "saved" | "same name" | "left out";

export type Problem = { words: string; code: string | null };
export type CsvFile =
  | { phase: "none"; problem: Problem | null }
  | { phase: "reading"; name: string; size: number }
  | {
      phase: "staged"; name: string; upload: CsvUpload; mapping: Mapping; how: Partial<Record<string, How>>; shown: CsvPreview;
      checking: boolean; failed: boolean;
    };  // prettier-ignore

type Csv = NonNullable<StartForm["csv"]>;

/** The required columns `mapping` gives no file's column: no row is built without them. */
export const unmapped = (columns: CsvColumnForm[], mapping: Mapping) => columns.filter((c) => c.required && !mapping[c.name]).map((c) => c.name);

const howOf = (columns: CsvColumnForm[], upload: CsvUpload): Partial<Record<string, How>> =>
  Object.fromEntries(columns.map((c) => [c.name, !upload.mapping[c.name] ? "left out" : upload.default_mapping.status === "applied" ? "saved" : "same name"]));

const same = (a: Mapping, b: Mapping) => JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort());

/** The codes that end an upload: it's chosen again. */
export const ENDED = new Set(["upload_expired", "upload_consumed", "upload_not_found"]);

export function useCsvFile(tenantId: string, workflowId: string) {
  const [file, setFile] = useState<CsvFile>({ phase: "none", problem: null });
  const chosen = useRef(0); // the files chosen: an answer for one chosen since is dropped
  const flight = useRef<{ busy: boolean; next: { id: string; mapping: Mapping } | null }>({ busy: false, next: null });
  // The file as last drawn: what a call made after an await (a newer version read) works from.
  const latest = useRef(file);
  useEffect(() => {
    latest.current = file;
  }, [file]);

  async function choose(f: File, csv: Csv) {
    const n = ++chosen.current;
    setFile({ phase: "reading", name: f.name, size: f.size });
    announce("Reading the file…");
    try {
      const upload = await uploadCsv(tenantId, workflowId, f);
      if (n !== chosen.current) return;
      setFile({ phase: "staged", name: f.name, upload, mapping: upload.mapping, how: howOf(csv.columns, upload), shown: upload, checking: false, failed: false });
      if (unmapped(csv.columns, upload.mapping).length === 0) announce(checkedWords(upload, upload.row_count));
    } catch (e) {
      if (n === chosen.current) setFile({ phase: "none", problem: uploadProblem(f.name, e, csv) });
    }
  }

  /** Every row checked again under `mapping`: after the one in flight, if any, and only the last asked meanwhile. */
  async function check(id: string, mapping: Mapping, rows: number) {
    flight.current.next = { id, mapping };
    if (flight.current.busy) return;
    flight.current.busy = true;
    announce("Checking every row again with these columns…");
    try {
      while (flight.current.next) {
        const ask = flight.current.next;
        flight.current.next = null;
        const current = (f: CsvFile): f is Extract<CsvFile, { phase: "staged" }> => f.phase === "staged" && f.upload.upload_id === ask.id && same(f.mapping, ask.mapping);
        try {
          const shown = await previewCsv(tenantId, workflowId, ask.id, ask.mapping);
          if (flight.current.next) continue; // a later choice is checked next: this answer is already old
          setFile((f) => (current(f) ? { ...f, shown, checking: false, failed: false } : f));
          announce(checkedWords(shown, rows));
        } catch (e) {
          if (flight.current.next) continue;
          const refused = refusalOf(e);
          if (ENDED.has(refused.code)) setFile({ phase: "none", problem: { words: refused.words, code: refused.code } });
          else setFile((f) => (current(f) ? { ...f, checking: false, failed: true } : f));
        }
      }
    } finally {
      flight.current.busy = false;
    }
  }

  /** Each column's choice kept or changed, then every row checked again once each required column has one. */
  function choices(f: Extract<CsvFile, { phase: "staged" }>, csv: Csv, mapping: Mapping, how: Partial<Record<string, How>>) {
    const ready = unmapped(csv.columns, mapping).length === 0;
    const next = { ...f, mapping, how, checking: ready, failed: false };
    latest.current = next; // a second choice before the next draw starts from this one
    setFile(next);
    if (ready) void check(f.upload.upload_id, mapping, f.upload.row_count);
  }

  /** The file's column chosen for `column` ("" for none). */
  function map(column: string, header: string, csv: Csv) {
    const f = latest.current;
    if (f.phase !== "staged") return;
    const mapping = { ...f.mapping };
    if (header) mapping[column] = header;
    else delete mapping[column];
    choices(f, csv, mapping, { ...f.how, [column]: undefined });
  }

  /** A newer version's form (§5.3): the staged file kept, each choice whose column it still reads, checked again; a
   * version that reads no CSV drops the file. */
  function recheck(form: StartForm) {
    const f = latest.current;
    if (f.phase !== "staged") return;
    if (!form.csv) return setFile({ phase: "none", problem: null });
    const names = new Set(form.csv.columns.map((c) => c.name));
    const mapping = Object.fromEntries(Object.entries(f.mapping).filter(([name]) => names.has(name)));
    choices(f, form.csv, mapping, Object.fromEntries(Object.entries(f.how).filter(([name]) => names.has(name))));
  }

  /** The upload ended (a start used it, its hour passed): the file is chosen again, `problem` saying why. */
  const drop = (problem: Problem) => setFile({ phase: "none", problem });

  return { file, choose, map, recheck, drop };
}

/** Why a CSV start can't go ahead yet, or null (§5.3): said beside Start, which waits. */
export function csvReason(file: CsvFile, columns: CsvColumnForm[]): string | null {
  if (file.phase !== "staged") return "Choose a file first.";
  if (unmapped(columns, file.mapping).length > 0) return "Choose the file's column for every required column first.";
  if (file.checking) return "The rows are being checked.";
  if (file.failed) return "The rows must be checked first.";
  if (file.shown.problems.length > 0) return "Fix the columns marked first.";
  if (file.shown.error_count > 0) return "Every row must pass first.";
  return null;
}
