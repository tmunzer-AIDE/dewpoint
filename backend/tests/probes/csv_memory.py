# SPDX-License-Identifier: Apache-2.0
"""The CSV reader's memory (the 2b-4b plan's M3, item 5): what one upload's parse allocates at the platform's caps
(5 MiB, 10,000 rows, 200 declared columns), for the files that make it largest, and what concurrent uploads hold. Run
by hand, never in CI; it takes seconds and needs no database. From `backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.csv_memory [--out FILE]

Memory is Python's own allocations (`tracemalloc`), so the numbers don't depend on the machine's load: the body as the
route reads it (its chunks, then joined), the text it decodes, the parsed records, and the rows a mapping builds
(`described`, the upload's preview and errors), as `stage` does them, the parse and the build on the event loop.
`retained` is what a request still holds while it awaits the database and the key service, after its parse: so N
uploads in one process hold N times it, besides the one parsing. The shapes:

- `distinct`: 200 short distinct cells a row, every column declared, as many rows as fit;
- `short`: 200 two-character cells a row, alike: the most cells the cap holds at 200 columns;
- `wide_empty`: as many empty cells a row as fit 10,000 rows, 200 of them declared;
- `wide_ucs4`: `distinct`, with one character outside the Basic Multilingual Plane (its text 4 bytes a character);
- `one_cell`: a single 5 MiB cell, outside the Latin-1 range."""

import argparse
import json
import platform
import sys
import tracemalloc
from typing import Any

from dewpoint.apps.csv_input import build_rows, exact_mapping, read_table
from dewpoint.apps.csv_uploads import described
from dewpoint.apps.inputs import reasons
from dewpoint.core.claims.service import _plain
from dewpoint.engine.graph.csv import MAX_BYTES, MAX_ROWS, trigger_schema
from dewpoint.engine.split import split

COLUMNS = 200  # the most a declaration has (engine/graph/model.py)
CHUNK = 64 * 1024  # what the server hands the route at a time, about


def _cell(n: int) -> str:
    """A short cell no other cell shares (`n` in base 26, two letters at least): a string of its own once parsed."""
    letters = ""
    while True:
        n, r = divmod(n, 26)
        letters = chr(97 + r) + letters
        if n == 0:
            break
    return letters.rjust(2, "a")


def _fit(header: str, row: Any, rows: int) -> bytes:
    """`header` and up to `rows` of `row(i)`, within MAX_BYTES."""
    out, size = [header], len(header.encode())
    for i in range(rows):
        line = row(i)
        size += len(line.encode())
        if size > MAX_BYTES:
            break
        out.append(line)
    return "".join(out).encode()


def shapes(max_rows: int = MAX_ROWS) -> dict[str, tuple[bytes, list[dict[str, Any]]]]:
    """Each shape, at most `max_rows` rows (the platform's cap by default; fewer for a quick check)."""
    declared = [{"header": f"c{i}", "name": f"c{i}", "type": "string"} for i in range(COLUMNS)]
    header = ",".join(f"c{i}" for i in range(COLUMNS)) + "\n"
    distinct = _fit(header, lambda i: ",".join(_cell(i * COLUMNS + j) for j in range(COLUMNS)) + "\n", max_rows)
    short = _fit(header, lambda _: ",".join(["ab"] * COLUMNS) + "\n", max_rows)  # each parsed cell its own string
    wide = (MAX_BYTES // MAX_ROWS) - 1  # cells a row whose empty cells fill the cap at 10,000 rows
    empty_header = ",".join(f"c{i}" for i in range(wide)) + "\n"
    wide_empty = _fit(empty_header, lambda i: "," * (wide - 1) + "\n", max_rows)
    ucs4 = distinct.replace(b"aaa", "\U0001f600".encode(), 1)[:MAX_BYTES]
    one = (header.split(",")[0] + "\n" + "Ā" * ((MAX_BYTES - 8) // 2) + "\n").encode()
    one_declared = [declared[0]]
    return {
        "distinct": (distinct, declared), "short": (short, declared), "wide_empty": (wide_empty, declared),
        "wide_ucs4": (ucs4, declared), "one_cell": (one, one_declared),
    }  # fmt: skip


def measure(data: bytes, columns: list[dict[str, Any]]) -> dict[str, Any]:
    """One upload's parse, as `stage` does it, in MiB: its peak, and what it holds while it awaits."""
    tracemalloc.start()
    try:
        chunks = [data[i : i + CHUNK] for i in range(0, len(data), CHUNK)]  # the route's read, then its join
        body = b"".join(chunks)
        del chunks
        table = read_table(body, max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
        held, _ = tracemalloc.get_traced_memory()
        shown = described(table, columns, exact_mapping(columns, table.headers))
        _, peak = tracemalloc.get_traced_memory()
        rows = len(table.rows)
        del shown
    finally:
        tracemalloc.stop()
    mib = 1024 * 1024
    return {"bytes": len(data), "rows": rows, "peak_mib": round(peak / mib, 1), "retained_mib": round(held / mib, 1)}


def measure_start(data: bytes, columns: list[dict[str, Any]]) -> dict[str, Any]:
    """A start from the staged file, as admission does it before it seals: the parse, every row built, the input
    checked against the trigger's schema and split, its envelope and claims (the rows, past 64 KiB) encoded, their
    sealing stood in for by a copy of their size. All of it is held until the request's transaction commits: the rows
    are the run's input."""
    schema = trigger_schema({"csv": {"columns": columns, "max_rows": MAX_ROWS, "max_bytes": MAX_BYTES}})
    tracemalloc.start()
    try:
        table = read_table(data, max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
        built = build_rows(table, columns, exact_mapping(columns, table.headers))
        value = {"rows": built.rows, "row_count": len(built.rows)}
        refused = reasons(schema, value)
        done = split(value, schema, lambda _pointer: "x")
        plain = [_plain(done.envelope), *(_plain(c.value) for c in done.claims)]  # rows past 64 KiB: a claim
        sealed = [bytearray(len(p) + 28) for p in plain]
        held, peak = tracemalloc.get_traced_memory()
        rows = len(built.rows)
        del table, built, value, done, plain, sealed
    finally:
        tracemalloc.stop()
    mib = 1024 * 1024
    return {"rows": rows, "refused": bool(refused), "peak_mib": round(peak / mib, 1),
            "retained_mib": round(held / mib, 1)}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    made = shapes()
    found = {name: measure(data, columns) for name, (data, columns) in made.items()}
    starts = {name: measure_start(data, columns) for name, (data, columns) in made.items()}
    report = {"python": sys.version.split()[0], "machine": platform.machine(), "uploads": found, "starts": starts}
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
