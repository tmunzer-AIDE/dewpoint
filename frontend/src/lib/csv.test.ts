// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { rootOf } from "./config";
import { addColumn, bytesOf, csvProblem, mbOf, newCsv, removeColumn, rulesOf, setColumn, setLimits, type CsvSettings } from "./csv";

const CSV: CsvSettings = {
  columns: [
    { header: "AP name", name: "ap_name", type: "string", required: true },
    { header: "Floor", name: "floor", type: "integer", required: true, default: 0 },
    { header: "Band", name: "band", type: "enum", default: "5 GHz", values: ["2.4 GHz", "5 GHz", "6 GHz"] },
  ],
};

describe("what a draft's save takes as a CSV declaration", () => {
  it("takes a declaration the strict model takes", () => {
    expect(csvProblem(CSV)).toBeNull();
    expect(csvProblem(undefined)).toBeNull();
    expect(csvProblem({ ...CSV, max_rows: 10_000, max_bytes: 5 * 1024 * 1024 })).toBeNull();
  });

  it("says what the save would refuse, so nothing refused is written", () => {
    expect(csvProblem({ columns: [] })).toBe("A CSV file has from 1 to 200 columns.");
    expect(csvProblem({ columns: CSV.columns, extra: 1 })).toMatch(/^A CSV file's declaration holds/);
    expect(csvProblem({ columns: [{ header: "", name: "a", type: "string" }] })).toBe("Column 1's header is from 1 to 200 characters.");
    expect(csvProblem({ columns: [{ header: "A", name: "a".repeat(64), type: "string" }] })).toBe("Column 1's name is from 1 to 63 characters.");
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "date" }] })).toMatch(/^Column 1's type is one of/);
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "string", note: "x" }] })).toBe("Column 1 holds something a column can't.");
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "enum", values: ["x".repeat(201)] }] })).toMatch(/at most 200 texts/);
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "string", required: "yes" }] })).toMatch(/true or false/);
    expect(csvProblem({ ...CSV, max_rows: 10_001 })).toBe("Most rows is a whole number from 1 to 10,000.");
    expect(csvProblem({ ...CSV, max_bytes: 0 })).toBe("The largest file is from 1 byte to 5 MB.");
  });
});

describe("columns", () => {
  it("starts a file with one text column, and adds one whose header and name aren't taken", () => {
    expect(newCsv()).toEqual({ columns: [{ header: "Column 1", name: "column_1", type: "string" }] });
    expect(addColumn(CSV).columns[3]).toEqual({ header: "Column 4", name: "column_4", type: "string" });
    const taken = { columns: [{ header: "Column 2", name: "x", type: "string" as const }] };
    expect(addColumn(taken).columns[1]).toEqual({ header: "Column 3", name: "column_3", type: "string" });
  });

  it("keeps the list's lineage through an edit in place and an addition, never through a removal", () => {
    const edited = setColumn(CSV, 0, { header: "AP" });
    expect(rootOf(edited.columns)).toBe(rootOf(CSV.columns));
    expect(rootOf(edited.columns[0]!)).toBe(rootOf(CSV.columns[0]!));
    expect(rootOf(addColumn(CSV).columns)).toBe(rootOf(CSV.columns));
    expect(rootOf(removeColumn(CSV, 0)!.columns)).not.toBe(rootOf(CSV.columns));
  });

  it("removes a column but never the last one: the file goes instead", () => {
    expect(removeColumn(CSV, 1)!.columns.map((c) => c.name)).toEqual(["ap_name", "band"]);
    expect(removeColumn(newCsv(), 0)).toBeNull();
  });

  it("keeps values for a Choice alone, drops a sensitive column's default and one that no longer fits", () => {
    expect(setColumn(CSV, 2, { type: "string" }).columns[2]).toEqual({ header: "Band", name: "band", type: "string", default: "5 GHz" });
    expect(setColumn(CSV, 0, { type: "enum" }).columns[0]).toEqual({ header: "AP name", name: "ap_name", type: "enum", required: true, values: [] });
    expect(setColumn(CSV, 1, { sensitive: true }).columns[1]).toEqual({ header: "Floor", name: "floor", type: "integer", required: true, sensitive: true });
    expect(setColumn(CSV, 1, { type: "boolean" }).columns[1]).not.toHaveProperty("default");
    expect(setColumn(CSV, 2, { values: ["2.4 GHz"] }).columns[2]).not.toHaveProperty("default");
    expect(setColumn(CSV, 1, { default: undefined }).columns[1]).not.toHaveProperty("default");
    // A required column's default is the server's to refuse (`csv.required_default`): written as asked.
    expect(setColumn(CSV, 0, { default: "x" }).columns[0]).toMatchObject({ required: true, default: "x" });
  });

  it("sets the limits, and leaves one to the platform's when it's cleared", () => {
    expect(setLimits(CSV, { max_rows: 500 })).toEqual({ ...CSV, max_rows: 500 });
    expect(setLimits({ ...CSV, max_rows: 500 }, { max_rows: undefined })).toEqual(CSV);
  });

  it("says a column's rules as the InputCsv board does", () => {
    expect(CSV.columns.map(rulesOf)).toEqual(["required", "required, default 0", "default 5 GHz"]);
    expect(rulesOf({ header: "Owner", name: "owner", type: "string", sensitive: true })).toBe("sensitive");
    expect(rulesOf({ header: "On", name: "on", type: "boolean", default: false })).toBe("default no");
  });

  it("reads the largest file in MB, up to the platform's 5 MB", () => {
    expect(bytesOf("5")).toBe(5 * 1024 * 1024);
    expect(bytesOf("0.5")).toBe(524_288);
    expect(bytesOf("6")).toBeNull();
    expect(bytesOf("0")).toBeNull();
    expect(bytesOf("x")).toBeNull();
    expect(mbOf(5 * 1024 * 1024)).toBe("5");
    expect(mbOf(524_288)).toBe("0.5");
  });
});
