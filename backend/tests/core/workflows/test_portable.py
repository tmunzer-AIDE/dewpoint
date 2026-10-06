# SPDX-License-Identifier: Apache-2.0
"""A workflow as a file (sub-project 4, B12), fail-closed: no tenant's id leaves but as a typed placeholder, and an
import writes nothing it hasn't checked against this server's node types."""

import copy
import uuid

import pytest

from dewpoint.core.workflows import portable
from tests.support.graphs import cel

CALL, SUB, OTHER = (str(uuid.uuid4()) for _ in range(3))
C1, W1 = str(uuid.uuid4()), str(uuid.uuid4())
SCHEMAS = {
    "testkit.http_call@1": {
        "properties": {"connection": {"type": "string", "x-dewpoint-connection": "testkit"}, "path": {"type": "string"}}
    },
    "flow.run_workflow@1": {"properties": {"workflow_id": {"type": "string"}, "input": {"type": "object"}}},
}
LABELS = {("connection", C1): "Acme Prod", ("workflow", W1): "Cleanup"}


def draft(conn: object = C1, sub: object = W1, handler: object = W1) -> dict:
    return {
        "graph_format": 1,
        "nodes": [
            {"id": CALL, "key": "call", "type": "testkit.http_call@1", "config": {"connection": conn, "path": "/x"}},
            {"id": SUB, "key": "sub", "type": "flow.run_workflow@1", "config": {"workflow_id": sub, "input": {}}},
        ],
        "edges": [],
        "settings": {"failure_handler": handler},
    }


def exported() -> dict:
    return portable.export_document("Nightly", draft(), SCHEMAS, LABELS)


def problems(doc: dict) -> list[tuple[str, str | None, str | None, str | None]]:
    found = portable.check_document(doc["graph"], doc["bindings"], SCHEMAS)
    return [(p.reason, p.binding, p.node, p.field) for p in found]


def test_the_markers_are_the_sdks_and_the_flow_plugins() -> None:
    from dewpoint.plugins.flow.nodes import RunWorkflow
    from dewpoint.sdk.fields import CONNECTION

    assert portable.CONNECTION_MARKER == CONNECTION
    assert portable.RUN_WORKFLOW == f"{RunWorkflow.type}@{RunWorkflow.version}"


def test_export_replaces_each_tenant_id_with_a_typed_placeholder() -> None:
    doc = exported()
    assert (doc["format"], doc["format_version"], doc["name"]) == ("dewpoint.workflow", 1, "Nightly")
    assert doc["bindings"] == [
        {"id": "b1", "kind": "connection", "type": "testkit", "label": "Acme Prod",
         "sites": [{"node": CALL, "field": "/connection"}]},
        {"id": "b2", "kind": "workflow", "type": None, "label": "Cleanup",
         "sites": [{"node": SUB, "field": "/workflow_id"}, {"node": None, "field": "/settings/failure_handler"}]},
    ]  # fmt: skip
    nodes = {n["key"]: n for n in doc["graph"]["nodes"]}
    assert nodes["call"]["config"] == {"path": "/x"} and nodes["sub"]["config"] == {"input": {}}
    assert "failure_handler" not in doc["graph"]["settings"]


def test_an_id_the_tenant_doesnt_name_is_labelled_unknown() -> None:
    doc = portable.export_document("Nightly", draft(), SCHEMAS, {})
    assert [b["label"] for b in doc["bindings"]] == ["Unknown connection", "Unknown workflow"]


def test_an_empty_site_is_emptied_and_exports_no_binding() -> None:
    doc = portable.export_document("Nightly", draft(conn=None, handler=None), SCHEMAS, LABELS)
    assert [(b["id"], b["kind"]) for b in doc["bindings"]] == [("b1", "workflow")]
    assert "connection" not in doc["graph"]["nodes"][0]["config"] and doc["graph"]["settings"] == {}


def test_one_id_at_two_sites_is_one_binding() -> None:
    two = draft()
    again = {"id": OTHER, "key": "again", "type": "testkit.http_call@1", "config": {"connection": C1.upper()}}
    two["nodes"].append(again)
    doc = portable.export_document("Nightly", two, SCHEMAS, LABELS)
    sites = [{"node": CALL, "field": "/connection"}, {"node": OTHER, "field": "/connection"}]
    assert doc["bindings"][0]["sites"] == sites


def test_a_step_of_a_type_this_server_doesnt_know_isnt_exported() -> None:
    odd = draft()
    odd["nodes"].append({"id": OTHER, "key": "odd", "type": "vendor.unknown@1", "config": {"account": C1}})
    with pytest.raises(portable.NotPortableError) as e:
        portable.export_document("Nightly", odd, SCHEMAS, LABELS)
    assert [p.to_json() for p in e.value.problems] == [
        {"reason": "unknown_type", "binding": None, "node": OTHER, "field": None}
    ]


@pytest.mark.parametrize(
    ("changed", "where"),
    [
        (draft(conn=cel("vars.c")), (CALL, "/connection")),  # an expression where an id goes
        (draft(conn="not-a-uuid"), (CALL, "/connection")),
        (draft(sub=7), (SUB, "/workflow_id")),
        (draft(handler="nope"), (None, "/settings/failure_handler")),
    ],
)
def test_a_site_holding_anything_but_an_id_isnt_exported(changed: dict, where: tuple) -> None:
    with pytest.raises(portable.NotPortableError) as e:
        portable.export_document("Nightly", changed, SCHEMAS, LABELS)
    assert [(p.reason, p.node, p.field) for p in e.value.problems] == [("unexpected_value", *where)]


def test_two_steps_sharing_an_id_arent_exported() -> None:
    twins = draft()
    twins["nodes"].append(copy.deepcopy(twins["nodes"][0]) | {"key": "twin"})
    with pytest.raises(portable.NotPortableError) as e:
        portable.export_document("Nightly", twins, SCHEMAS, LABELS)
    assert [(p.reason, p.node) for p in e.value.problems] == [("duplicate_node", CALL)]


def test_import_binds_each_placeholder_and_round_trips() -> None:
    doc = exported()
    assert problems(doc) == []
    assert portable.apply(doc["graph"], doc["bindings"], {"b1": C1, "b2": W1}, SCHEMAS) == draft()


def test_an_unbound_placeholder_leaves_its_sites_empty() -> None:
    doc = exported()
    back = portable.apply(doc["graph"], doc["bindings"], {"b1": C1}, SCHEMAS)
    nodes = {n["key"]: n for n in back["nodes"]}
    assert nodes["call"]["config"]["connection"] == C1
    assert "workflow_id" not in nodes["sub"]["config"] and "failure_handler" not in back["settings"]


def test_an_embedded_id_is_refused() -> None:
    doc = exported()
    doc["graph"]["nodes"][0]["config"]["connection"] = C1  # left unbound, it would stay
    doc["graph"]["settings"]["failure_handler"] = W1
    assert problems(doc) == [
        ("embedded_value", None, CALL, "/connection"),
        ("embedded_value", None, None, "/settings/failure_handler"),
    ]


@pytest.mark.parametrize(
    ("site", "kind"),
    [
        ({"node": str(uuid.uuid4()), "field": "/connection"}, "connection"),  # no such step
        ({"node": CALL, "field": "/path"}, "connection"),  # a property its type doesn't mark
        ({"node": CALL, "field": "/nested/connection"}, "connection"),  # nested: the SDK marks top-level only
        ({"node": None, "field": "/settings/outputs"}, "workflow"),  # settings other than the failure handler
        ({"node": SUB, "field": "/workflow_id"}, "connection"),  # a workflow's site, bound as a connection
        ({"node": CALL, "field": "/connection"}, "workflow"),  # a connection's site, bound as a workflow
    ],
)
def test_a_site_an_import_may_not_write_is_refused(site: dict, kind: str) -> None:
    doc = exported()
    doc["bindings"] = [
        {"id": "b7", "kind": kind, "type": "testkit" if kind == "connection" else None, "label": "x", "sites": [site]}
    ]
    assert problems(doc) == [("bad_site", "b7", site["node"], site["field"])]


def test_a_connection_binding_takes_its_sites_type() -> None:
    doc = exported()
    doc["bindings"][0]["type"] = "mist"
    assert problems(doc) == [("bad_site", "b1", CALL, "/connection")]


def test_binding_ids_and_sites_are_each_used_once() -> None:
    doc = exported()
    doc["bindings"].append(copy.deepcopy(doc["bindings"][0]))
    assert problems(doc) == [("duplicate_binding", "b1", None, None), ("overlapping_site", "b1", CALL, "/connection")]


def test_a_step_of_a_type_this_server_doesnt_know_isnt_imported() -> None:
    doc = exported()
    doc["graph"]["nodes"].append({"id": OTHER, "key": "odd", "type": "vendor.unknown@1", "config": {}})
    assert problems(doc) == [("unknown_type", None, OTHER, None)]


def test_apply_refuses_whatever_the_check_refuses() -> None:
    doc = exported()
    doc["graph"]["nodes"][0]["config"]["connection"] = C1
    with pytest.raises(portable.BadDocumentError) as e:
        portable.apply(doc["graph"], doc["bindings"], {"b1": C1}, SCHEMAS)
    assert [p.reason for p in e.value.problems] == ["embedded_value"]
