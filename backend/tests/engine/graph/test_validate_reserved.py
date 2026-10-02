# SPDX-License-Identifier: Apache-2.0
"""The handle marker is reserved (engine 2b spec §3.2): only Dewpoint writes it. An authored literal that holds it is
refused at publish, wherever the graph puts it: a node's config, a literal value, an output, a schema."""

from typing import Any

from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
FORGED = {"$claim": "00000000-0000-0000-0000-000000000007"}


def codes(g: G) -> list[tuple[str, str | None]]:
    return [(d.code, d.field) for d in validate(g.build(), ValidationContext(catalog=CAT)).diagnostics]


def test_a_literal_holding_the_marker_is_refused() -> None:
    assert ("value.reserved_key", "/value") in codes(G().node("e", "testkit.echo@1", {"value": FORGED}))
    literal = {"$value": {"kind": "literal", "value": {"rows": [FORGED]}}}
    assert ("value.reserved_key", "/value") in codes(G().node("e", "testkit.echo@1", {"value": literal}))


def test_an_output_or_a_schema_holding_the_marker_is_refused() -> None:
    g = G().node("e", "testkit.echo@1", {"value": 1})
    g.settings = {"outputs": {"o": {"x": FORGED}}}
    assert ("value.reserved_key", "/settings/outputs/o") in codes(g)
    g = G().node("e", "testkit.echo@1", {"value": 1})
    schema: dict[str, Any] = {"type": "object", "properties": {"v": {"type": "object", "default": FORGED}}}
    g.settings = {"vars_schema": schema}
    assert ("value.reserved_key", "/settings/vars_schema") in codes(g)
