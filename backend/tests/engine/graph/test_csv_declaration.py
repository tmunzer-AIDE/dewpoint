# SPDX-License-Identifier: Apache-2.0
"""A workflow's CSV declaration (engine 2b spec §8.1): `graph.settings.csv` lists the file's columns (header, variable
name, type, required, default, sensitive) and its caps, at most the platform's 10,000 rows and 5 MiB. Publish refuses a
default on a sensitive column (§3.8), duplicate headers or names, a default its type rejects, and a required column with
a default. A graph without a declaration serializes as it always did, so its hash doesn't change."""

from typing import Any

import pytest

from dewpoint.engine.graph.model import GraphFormatError, graph_hash, graph_json, parse_graph
from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)


def column(name: str, type_: str = "string", **extra: Any) -> dict[str, Any]:
    return {"header": name.title(), "name": name, "type": type_, **extra}


def declared(*columns: dict[str, Any], **caps: Any) -> G:
    g = G().node("a", "testkit.echo@1", {"value": 1})
    g.settings = {"csv": {"columns": list(columns), **caps}}
    return g


def codes(g: G) -> list[tuple[str, str | None]]:
    return [(d.code, d.field) for d in validate(g.build(), ValidationContext(catalog=CAT)).diagnostics]


def test_a_graph_without_a_csv_serializes_as_before() -> None:
    g = G().node("a", "testkit.echo@1", {"value": 1}).build()
    assert "csv" not in graph_json(g)["settings"]
    assert graph_hash(g) == graph_hash(parse_graph(graph_json(g)))


def test_a_declaration_round_trips_and_an_omitted_default_stays_omitted() -> None:
    g = declared(column("site"), column("vlan", "integer", default=1), column("psk", sensitive=True)).build()
    dumped = graph_json(g)["settings"]["csv"]
    assert "default" not in dumped["columns"][0] and "default" not in dumped["columns"][2]
    assert dumped["columns"][1]["default"] == 1
    assert (dumped["max_rows"], dumped["max_bytes"]) == (10_000, 5 * 1024 * 1024)
    assert graph_json(parse_graph(graph_json(g))) == graph_json(g)


def test_a_valid_declaration_publishes() -> None:
    g = declared(
        column("site", required=True),
        column("mac", "mac"),
        column("net", "cidr", default="10.0.0.0/8"),
        column("kind", "enum", values=["ap", "switch"]),
        column("psk", sensitive=True),
    )
    assert codes(g) == []


@pytest.mark.parametrize("default", [None, "", "s3cret"])
def test_publish_refuses_any_default_on_a_sensitive_column(default: Any) -> None:
    assert codes(declared(column("site"), column("psk", sensitive=True, default=default))) == [
        ("sensitive.default", "/settings/csv/columns/1/default")
    ]


def test_publish_refuses_the_values_of_a_sensitive_column() -> None:
    """An enum's values are literals in the published graph (§3.8): a sensitive column can't list them, whatever the
    start form masks."""
    assert codes(declared(column("key", "enum", sensitive=True, values=["k1", "k2"]))) == [
        ("sensitive.literal", "/settings/csv/columns/0/values")
    ]


def test_publish_refuses_duplicate_headers_and_names() -> None:
    assert codes(declared(column("site"), {"header": "Site", "name": "other", "type": "string"})) == [
        ("csv.duplicate_header", "/settings/csv/columns/1/header")
    ]
    assert codes(declared(column("site"), {"header": "Other", "name": "site", "type": "string"})) == [
        ("csv.duplicate_name", "/settings/csv/columns/1/name")
    ]


@pytest.mark.parametrize("name", ["Site", "1st", "in", "null", "site\n"])  # `$` matches before a final newline
def test_publish_refuses_a_name_that_isnt_an_identifier(name: str) -> None:
    assert codes(declared({"header": "H", "name": name, "type": "string"})) == [
        ("csv.invalid_name", "/settings/csv/columns/0/name")
    ]


@pytest.mark.parametrize(
    ("type_", "default", "ok"),
    [
        ("integer", 5, True), ("integer", "5", False), ("integer", True, False), ("integer", 2**63, False),
        ("number", 1.5, True), ("number", "1.5", False),
        ("boolean", False, True), ("boolean", "no", False),
        ("mac", "aa:bb:cc:dd:ee:ff", True), ("mac", "AA-BB-CC-DD-EE-FF", False), ("mac", "aa:bb", False),
        ("ip", "10.0.0.1", True), ("ip", "2001:db8::1", True), ("ip", "2001:DB8:0::1", False),
        ("ip", "010.0.0.1", False),
        ("cidr", "10.0.0.0/8", True), ("cidr", "10.0.0.1/8", False),
        ("string", "x", True), ("string", 1, False),
    ],
)  # fmt: skip
def test_a_default_must_be_its_types_canonical_value(type_: str, default: Any, ok: bool) -> None:
    found = codes(declared(column("c", type_, default=default)))
    assert found == ([] if ok else [("csv.bad_default", "/settings/csv/columns/0/default")])


def test_an_enum_needs_its_values_and_only_an_enum_has_them() -> None:
    assert codes(declared(column("kind", "enum"))) == [("csv.enum_values", "/settings/csv/columns/0/values")]
    assert codes(declared(column("site", values=["a"]))) == [("csv.enum_values", "/settings/csv/columns/0/values")]
    assert codes(declared(column("kind", "enum", values=["ap"], default="switch"))) == [
        ("csv.bad_default", "/settings/csv/columns/0/default")
    ]


def test_a_required_column_takes_no_default() -> None:
    assert codes(declared(column("vlan", "integer", required=True, default=1))) == [
        ("csv.required_default", "/settings/csv/columns/0/default")
    ]


@pytest.mark.parametrize(
    ("caps", "where"),
    [
        ({"max_rows": 10_001}, "max_rows"),
        ({"max_bytes": 5 * 1024 * 1024 + 1}, "max_bytes"),
        ({"max_rows": 0}, "max_rows"),
    ],
)
def test_caps_past_the_platforms_are_refused(caps: dict[str, int], where: str) -> None:
    with pytest.raises(GraphFormatError) as e:
        declared(column("site"), **caps).build()
    assert [d.field for d in e.value.diagnostics] == [f"/settings/csv/{where}"]


def test_a_declaration_needs_a_column() -> None:
    with pytest.raises(GraphFormatError) as e:
        declared().build()
    assert [d.field for d in e.value.diagnostics] == ["/settings/csv/columns"]
