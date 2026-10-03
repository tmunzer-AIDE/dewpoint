# SPDX-License-Identifier: Apache-2.0
"""A CSV file read as data only (engine 2b spec §8.1): UTF-8 with an optional BOM, the delimiter detected among comma,
semicolon and tab, the caps enforced, the headers unique. Its rows are built through a mapping from declared columns to
the file's headers, each cell converted to its column's type; a row that breaks a rule is reported as its number, the
column's declared name and a fixed code, never what the cell holds."""

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from dewpoint.apps.csv_input import (
    FILE_CODES,
    CsvFileError,
    RowError,
    build_rows,
    exact_mapping,
    mapping_problems,
    read_table,
)
from dewpoint.engine.graph.csv import CELL_CODES, trigger_schema

COLUMNS = [
    {"header": "Site", "name": "site", "type": "string", "required": True},
    {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
    {"header": "MAC", "name": "mac", "type": "mac"},
    {"header": "PSK", "name": "psk", "type": "string", "sensitive": True},
]
MAPPING = {"site": "Site", "vlan": "VLAN", "mac": "MAC", "psk": "PSK"}


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_the_delimiter_is_detected_among_comma_semicolon_and_tab(delimiter: str) -> None:
    data = f"Site{delimiter}VLAN\r\nparis{delimiter}10\r\n".encode()
    table = read_table(data, max_rows=10, max_bytes=1000)
    assert (table.headers, table.rows) == (["Site", "VLAN"], [["paris", "10"]])


def test_a_bom_quotes_and_blank_lines_are_handled() -> None:
    data = '﻿Site,Note\n"paris, fr","two\nlines"\n\n"say ""hi""",x\n'.encode()
    table = read_table(data, max_rows=10, max_bytes=1000)
    assert table.headers == ["Site", "Note"]
    assert table.rows == [["paris, fr", "two\nlines"], ['say "hi"', "x"]]


def test_a_comma_in_a_quoted_semicolon_header_doesnt_fool_the_detection() -> None:
    table = read_table(b'"a,b";c\n1;2\n', max_rows=10, max_bytes=1000)
    assert (table.headers, table.rows) == (["a,b", "c"], [["1", "2"]])


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"Site\n\xff\xfe\n", "csv_encoding"),
        (b"", "csv_empty"),
        (b"\n\n", "csv_empty"),
        (b"Site,Site\nx,y\n", "csv_duplicate_header"),
        (b'Site\n"unterminated\n', "csv_malformed"),
        (b"Site\nx\x00y\n", "csv_malformed"),
        (b"Site\n1\n2\n3\n", "csv_too_many_rows"),
        (b"S" * 1001, "csv_too_large"),
    ],
)
def test_a_file_that_cant_be_read_gives_its_code(data: bytes, code: str) -> None:
    with pytest.raises(CsvFileError) as e:
        read_table(data, max_rows=2, max_bytes=1000)
    assert e.value.code == code and code in FILE_CODES
    assert str(e.value) == code  # never the file's text


def test_exact_header_matches_are_mapped() -> None:
    assert exact_mapping(COLUMNS, ["PSK", "Site", "vlan", "extra"]) == {"psk": "PSK", "site": "Site"}


def test_a_mapping_is_checked_against_the_declaration_and_the_file() -> None:
    headers = ["Site", "VLAN", "PSK"]
    assert mapping_problems(COLUMNS, {"site": "Site"}, headers) == []
    assert mapping_problems(COLUMNS, {"vlan": "VLAN"}, headers) == [{"column": "site", "code": "required_unmapped"}]
    assert mapping_problems(COLUMNS, {"site": "Site", "nope": "VLAN"}, headers) == [
        {"column": "nope", "code": "unknown_column"}
    ]
    assert mapping_problems(COLUMNS, {"site": "Elsewhere"}, headers) == [{"column": "site", "code": "unknown_header"}]
    assert mapping_problems(COLUMNS, {"site": "Site", "psk": "Site"}, headers) == [
        {"column": "psk", "code": "header_reused"}
    ]


def test_rows_are_built_typed_with_defaults_filled_and_absent_cells_omitted() -> None:
    table = read_table(b"Site,VLAN,MAC,PSK,Extra\nparis,,AA-BB-CC-DD-EE-FF,s3cret,ignored\nlyon,20,,,\n",
                       max_rows=10, max_bytes=1000)  # fmt: skip
    rows, errors = build_rows(table, COLUMNS, MAPPING)
    assert errors == []
    assert rows == [
        {"site": "paris", "vlan": 1, "mac": "aa:bb:cc:dd:ee:ff", "psk": "s3cret"},
        {"site": "lyon", "vlan": 20},
    ]


def test_a_row_that_breaks_a_rule_is_its_number_column_and_code() -> None:
    table = read_table(b"Site,VLAN,MAC\n,x,zz\nok,1\nfine,2,\n", max_rows=10, max_bytes=1000)
    rows, errors = build_rows(table, COLUMNS, {"site": "Site", "vlan": "VLAN", "mac": "MAC"})
    assert rows == [{"site": "fine", "vlan": 2}]
    assert errors == [
        RowError(1, "site", "required"),
        RowError(1, "vlan", "not_integer"),
        RowError(1, "mac", "not_mac"),
        RowError(2, None, "cell_count"),
    ]


ROW_SCHEMA = trigger_schema({"csv": {"columns": COLUMNS, "max_rows": 10_000}})["properties"]["rows"]["items"]
CELL = st.text(alphabet=string.printable + "é﻿ ", max_size=12)


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=400))
def test_any_bytes_read_as_a_table_or_give_a_file_code(data: bytes) -> None:
    try:
        table = read_table(data, max_rows=50, max_bytes=1000)
    except CsvFileError as e:
        assert e.code in FILE_CODES
        return
    assert len(set(table.headers)) == len(table.headers)
    assert all(isinstance(cell, str) for row in table.rows for cell in row)


@settings(max_examples=300, deadline=None)
@given(st.lists(st.lists(CELL, min_size=4, max_size=5), max_size=8))
def test_built_rows_always_match_the_row_schema_and_errors_never_quote_a_cell(cells: list[list[str]]) -> None:
    from dewpoint.apps.csv_input import Table

    rows, errors = build_rows(Table(["Site", "VLAN", "MAC", "PSK"], cells), COLUMNS, MAPPING)
    validator = Draft202012Validator(ROW_SCHEMA)
    assert all(validator.is_valid(row) for row in rows)
    assert len(rows) + len({e.row for e in errors}) == len(cells)
    assert all(e.code in CELL_CODES | {"required", "cell_count"} and e.column in (None, *MAPPING) for e in errors)
