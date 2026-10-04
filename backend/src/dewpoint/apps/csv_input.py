# SPDX-License-Identifier: Apache-2.0
"""A CSV file as data only (engine 2b spec §8.1): no formula, no type guessing, nothing evaluated. It's decoded as UTF-8
(an optional BOM dropped), its delimiter detected among comma, semicolon and tab from its header record, and read with
strict quoting; blank lines are skipped. Its caps are enforced: bytes, then data records.

A table's rows are built through a mapping from declared column names to the file's headers: each cell converted to its
column's canonical value (`engine.graph.csv.convert`), an empty cell absent (its column's default, or `required`). What
breaks a rule is reported as the record's number (1 is the first after the header), the column's declared name and a
fixed code: never a cell's text nor a header, both of which are the file's data.

What the builder keeps is bounded by the records, never by records times columns (the owner's M2 review: 200 required
columns of empty cells in 10,000 records break 2 million rules in a 2 MB file): the first `LISTED_ERRORS` errors in
detail, each skipped record's number and the first rule it broke, and a count of every error.

A field may be as long as the platform's byte cap: Python's csv module refuses one past 131,072 characters by default,
so its process-wide limit is raised to that cap here (nothing else in the process reads CSV)."""

import csv
import io
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.graph.csv import MAX_BYTES, convert

DELIMITERS = (",", ";", "\t")  # tried in this order: a tie goes to the earlier one
FILE_CODES = frozenset(
    {"csv_encoding", "csv_empty", "csv_duplicate_header", "csv_malformed", "csv_too_many_rows", "csv_too_large"}
)
ROW_CODES = frozenset({"required", "cell_count"})  # beside a cell's conversion codes (`CELL_CODES`)
MAPPING_CODES = frozenset({"required_unmapped", "unknown_column", "unknown_header", "header_reused"})
LISTED_ERRORS = 100  # errors kept in detail; the count is every one

csv.field_size_limit(max(csv.field_size_limit(), MAX_BYTES))


class CsvFileError(Exception):
    """A file that can't be read as a table: its code only (`FILE_CODES`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Table:
    headers: list[str]
    rows: list[list[str]]  # each record's cells, as the file holds them


@dataclass(frozen=True)
class RowError:
    row: int  # the record's number: 1 is the first after the header
    column: str | None  # the declared column's name; None for the record as a whole
    code: str


@dataclass(frozen=True)
class Built:
    rows: list[dict[str, Any]]  # every record that broke no rule
    skipped: list[tuple[int, str]]  # every other record: its number and the first rule it broke
    errors: list[RowError]  # the first `LISTED_ERRORS` errors, in order
    error_count: int  # every error


def _records(text: str, delimiter: str) -> Iterator[list[str]]:
    return csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)


def _delimiter(text: str) -> str:
    """The candidate that splits the header record into the most fields, read strictly: a comma inside a quoted
    semicolon-separated header doesn't count."""
    best, most = DELIMITERS[0], 0
    for candidate in DELIMITERS:
        try:
            fields = len(next(_records(text, candidate), []))
        except csv.Error:
            continue
        if fields > most:
            best, most = candidate, fields
    return best


def read_table(data: bytes, *, max_rows: int, max_bytes: int) -> Table:
    """`data` as a table, or CsvFileError. The caller enforces `max_bytes` while it reads the body; it's checked here
    again."""
    if len(data) > max_bytes:
        raise CsvFileError("csv_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvFileError("csv_encoding") from None
    if "\x00" in text:  # the csv module's handling of NUL differs between Python versions
        raise CsvFileError("csv_malformed")
    records = _records(text, _delimiter(text))
    headers: list[str] | None = None
    rows: list[list[str]] = []
    try:
        for record in records:
            if not record:
                continue  # a blank line
            if headers is None:
                if len(set(record)) != len(record):
                    raise CsvFileError("csv_duplicate_header")
                headers = record
                continue
            if len(rows) == max_rows:
                raise CsvFileError("csv_too_many_rows")
            rows.append(record)
    except csv.Error:
        raise CsvFileError("csv_malformed") from None
    if headers is None:
        raise CsvFileError("csv_empty")
    return Table(headers, rows)


def exact_mapping(columns: Sequence[Mapping[str, Any]], headers: Sequence[str]) -> dict[str, str]:
    """Each declared column whose header the file has exactly, mapped to it."""
    present = set(headers)
    return {c["name"]: c["header"] for c in columns if c["header"] in present}


def mapping_problems(
    columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str], headers: Sequence[str] | None
) -> list[dict[str, str]]:
    """What keeps `mapping` from building rows, each as a column's declared name and a code (`MAPPING_CODES`): a name
    the declaration lacks, a required column left unmapped, and, given the file's `headers`, a header it doesn't have
    or one mapped twice."""
    declared = {c["name"] for c in columns}
    problems = [{"column": name, "code": "unknown_column"} for name in mapping if name not in declared]
    if headers is not None:
        present, used = set(headers), set()
        for name, header in mapping.items():
            if name not in declared:
                continue
            if header not in present:
                problems.append({"column": name, "code": "unknown_header"})
            elif header in used:
                problems.append({"column": name, "code": "header_reused"})
            used.add(header)
    problems += [{"column": c["name"], "code": "required_unmapped"} for c in columns
                 if c.get("required") and c["name"] not in mapping]  # fmt: skip
    return problems


def build_rows(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]) -> Built:
    """The rows `mapping` builds from `table` (its problems checked first, `mapping_problems`); a record that breaks a
    rule builds none, and is reported within the builder's bounds."""
    position = {header: i for i, header in enumerate(table.headers)}
    rows: list[dict[str, Any]] = []
    skipped: list[tuple[int, str]] = []
    errors: list[RowError] = []
    count = 0
    for number, record in enumerate(table.rows, start=1):
        broke: list[RowError] = []
        if len(record) != len(table.headers):
            broke.append(RowError(number, None, "cell_count"))
        row: dict[str, Any] = {}
        for c in columns if not broke else ():
            header = mapping.get(c["name"])
            text = record[position[header]] if header is not None else ""
            if text == "":
                if "default" in c:
                    row[c["name"]] = c["default"]
                elif c.get("required"):
                    broke.append(RowError(number, c["name"], "required"))
                continue
            value, code = convert(c["type"], text, c.get("values"))
            if code is not None:
                broke.append(RowError(number, c["name"], code))
            else:
                row[c["name"]] = value
            if len(broke) > LISTED_ERRORS:  # a record keeps no more detail than the whole file lists
                broke.pop()
                count += 1
        if not broke:
            rows.append(row)
            continue
        skipped.append((number, broke[0].code))
        count += len(broke)
        errors.extend(broke[: LISTED_ERRORS - len(errors)])
    return Built(rows, skipped, errors, count)
