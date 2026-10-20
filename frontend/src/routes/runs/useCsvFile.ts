// SPDX-License-Identifier: Apache-2.0
// A CSV run's file (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): chosen, uploaded as it
// is, read by the server against the version's columns, the file's columns proposed for them (saved, or the same names),
// and the person's choice of each. The upload's answer says what keeps the file from building rows.
import { useRef, useState } from "react";
import { announce } from "../../lib/announce";
import { uploadCsv, uploadProblem, type CsvColumnForm, type CsvPreview, type CsvUpload, type Mapping } from "../../lib/runForm";

/** How a column's choice was made: proposed from the saved columns, by the same name, or left out; the person's own
 * choice says nothing. */
export type How = "saved" | "same name" | "left out";

export type CsvFile =
  | { phase: "none"; problem: { words: string; code: string | null } | null }
  | { phase: "reading"; name: string; size: number }
  | { phase: "staged"; name: string; upload: CsvUpload; mapping: Mapping; how: Partial<Record<string, How>>; shown: CsvPreview };

/** The required columns `mapping` gives no file's column: no row is built without them. */
export const unmapped = (columns: CsvColumnForm[], mapping: Mapping) => columns.filter((c) => c.required && !mapping[c.name]).map((c) => c.name);

const howOf = (columns: CsvColumnForm[], upload: CsvUpload): Partial<Record<string, How>> =>
  Object.fromEntries(columns.map((c) => [c.name, !upload.mapping[c.name] ? "left out" : upload.default_mapping.status === "applied" ? "saved" : "same name"]));

export function useCsvFile(tenantId: string, workflowId: string) {
  const [file, setFile] = useState<CsvFile>({ phase: "none", problem: null });
  const chosen = useRef(0); // the files chosen: an answer for one chosen since is dropped

  async function choose(f: File, csv: { columns: CsvColumnForm[]; max_rows: number; max_bytes: number }) {
    const n = ++chosen.current;
    setFile({ phase: "reading", name: f.name, size: f.size });
    announce("Reading the file…");
    try {
      const upload = await uploadCsv(tenantId, workflowId, f);
      if (n !== chosen.current) return;
      setFile({ phase: "staged", name: f.name, upload, mapping: upload.mapping, how: howOf(csv.columns, upload), shown: upload });
    } catch (e) {
      if (n === chosen.current) setFile({ phase: "none", problem: uploadProblem(f.name, e, csv) });
    }
  }

  /** The file's column chosen for `column` ("" for none). */
  function map(column: string, header: string) {
    setFile((f) => {
      if (f.phase !== "staged") return f;
      const mapping = { ...f.mapping };
      if (header) mapping[column] = header;
      else delete mapping[column];
      return { ...f, mapping, how: { ...f.how, [column]: undefined } };
    });
  }

  return { file, choose, map };
}

/** Why a CSV start can't go ahead yet, or null (§5.3): said beside Start, which waits. */
export function csvReason(file: CsvFile, columns: CsvColumnForm[]): string | null {
  if (file.phase !== "staged") return "Choose a file first.";
  if (unmapped(columns, file.mapping).length > 0) return "Choose the file's column for every required column first.";
  if (file.shown.problems.length > 0) return "Fix the columns marked first.";
  if (file.shown.error_count > 0) return "Every row must pass first.";
  return null;
}
