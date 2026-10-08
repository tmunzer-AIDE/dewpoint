# SPDX-License-Identifier: Apache-2.0
"""Exporting a workflow and importing it into another tenant (sub-project 4, B12), fail-closed both ways."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select

from dewpoint.core.models.audit import AuditEntry
from tests.apps.api.helpers import member_client, session_client
from tests.support.connections import add_connection
from tests.support.graphs import cel, ref
from tests.support.registry import sync_test_plugins

CALL, SUB = str(uuid.uuid4()), str(uuid.uuid4())


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


def draft(conn: object, sub: str) -> dict:
    return {
        "graph_format": 1,
        "nodes": [
            {"id": CALL, "key": "call", "type": "testkit.http_call@1", "config": {"connection": conn, "path": "/x"}},
            {"id": SUB, "key": "sub", "type": "flow.run_workflow@1", "config": {"workflow_id": sub, "input": {}}},
        ],
        "edges": [{"from": {"node": CALL, "port": "out"}, "to": {"node": SUB}}],
        "settings": {"failure_handler": sub},
    }


async def exported(app, owner_sessionmaker, api_settings) -> dict:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    conn = await add_connection(owner_sessionmaker, tid)
    async with c:
        sub = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Cleanup"})).json()
        body = {"name": "Nightly", "draft": draft(str(conn), sub["id"])}
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json=body)).json()
        r = await c.get(f"/api/v1/t/{tid}/workflows/{wf['id']}/export")
    assert r.status_code == 200, r.text
    return r.json()


async def imported(app, owner_sessionmaker, api_settings, doc: dict, bind: dict | None = None) -> tuple:
    """Import into a fresh tenant: (the answer, that tenant's workflows after it)."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        body = {"name": "Imported", "document": doc, **({"bind": bind} if bind else {})}
        r = await c.post(f"/api/v1/t/{tid}/workflows/import", json=body)
        listed = (await c.get(f"/api/v1/t/{tid}/workflows")).json()
    return r, listed


async def test_the_file_carries_no_tenant_id(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    kinds = [(b["id"], b["kind"], b["type"]) for b in doc["bindings"]]
    assert kinds == [("b1", "connection", "testkit"), ("b2", "workflow", None)]
    assert doc["bindings"][1]["label"] == "Cleanup" and len(doc["bindings"][1]["sites"]) == 2
    nodes = {n["key"]: n for n in doc["graph"]["nodes"]}
    assert nodes["call"]["config"] == {"path": "/x"} and nodes["sub"]["config"] == {"input": {}}
    assert "failure_handler" not in doc["graph"]["settings"]


async def test_importing_binds_each_placeholder_to_this_tenants_own(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    conn = await add_connection(owner_sessionmaker, tid)
    async with c:
        target = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Target"})).json()
        r = await c.post(
            f"/api/v1/t/{tid}/workflows/import",
            json={"name": "Imported", "document": doc, "bind": {"b1": str(conn), "b2": target["id"]}},
        )
    assert r.status_code == 201, r.text
    assert r.json()["draft"] == draft(str(conn), target["id"])
    assert r.json()["name"] == "Imported" and r.json()["draft_revision"] == 1
    # An editor can't read the audit log (audit.view is an admin's): read its newest entry as the database's owner.
    async with owner_sessionmaker() as s:
        q = select(AuditEntry).where(AuditEntry.tenant_id == tid).order_by(AuditEntry.seq.desc()).limit(1)
        entry = (await s.execute(q)).scalar_one()
    assert (entry.action, entry.target_id) == ("workflow.create", r.json()["id"])
    assert entry.details == {"name": "Imported", "source": "import"}


@pytest.mark.parametrize("case", ["wrong_type", "unknown", "unexpected"])
async def test_a_binding_of_the_wrong_kind_is_refused_and_nothing_is_created(
    app, owner_sessionmaker, api_settings, case
) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    _, elsewhere = await session_client(app, owner_sessionmaker, api_settings, "editor")
    bind = {
        "wrong_type": {"b1": str(await add_connection(owner_sessionmaker, tid, type_key="mist"))},
        "unknown": {"b1": str(await add_connection(owner_sessionmaker, elsewhere))},  # another tenant's
        "unexpected": {"b9": str(uuid.uuid4())},
    }[case]
    async with c:
        r = await c.post(f"/api/v1/t/{tid}/workflows/import", json={"name": "Imported", "document": doc, "bind": bind})
        listed = (await c.get(f"/api/v1/t/{tid}/workflows")).json()
    assert r.status_code == 422 and r.json() == {"error": "bad_binding", "binding": next(iter(bind)), "reason": case}
    assert listed == []


async def test_an_unbound_placeholder_imports_with_its_sites_empty(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    r, _ = await imported(app, owner_sessionmaker, api_settings, doc)
    assert r.status_code == 201, r.text
    assert r.json()["draft"]["nodes"][0]["config"] == {"path": "/x"}


async def test_a_file_embedding_an_id_is_refused_and_nothing_is_created(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    doc["graph"]["nodes"][0]["config"]["connection"] = str(uuid.uuid4())  # "leave unbound" would keep it
    r, listed = await imported(app, owner_sessionmaker, api_settings, doc)
    problem = {"reason": "embedded_value", "binding": None, "node": CALL, "field": "/connection"}
    assert (r.status_code, r.json()) == (422, {"error": "bad_document", "problems": [problem]})
    assert listed == []


async def test_a_binding_naming_a_property_its_step_doesnt_mark_is_refused(
    app, owner_sessionmaker, api_settings
) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    doc["bindings"][0]["sites"] = [{"node": CALL, "field": "/path"}]
    r, listed = await imported(app, owner_sessionmaker, api_settings, doc, {"b1": str(uuid.uuid4())})
    assert r.status_code == 422 and r.json()["problems"] == [
        {"reason": "bad_site", "binding": "b1", "node": CALL, "field": "/path"}
    ]
    assert listed == []


# Spellings of one UUID the graph's format accepts, which the engine reads as one step (the owner's review of M1).
ALIASES: dict[str, Callable[[str], str]] = {"uppercase": str.upper, "unhyphenated": lambda u: u.replace("-", "")}


@pytest.mark.parametrize("alias", ALIASES.values(), ids=ALIASES.keys())
async def test_two_steps_whose_ids_are_one_uuid_arent_exported(app, owner_sessionmaker, api_settings, alias) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    twins = draft(str(uuid.uuid4()), str(uuid.uuid4()))
    twins["nodes"].append({"id": alias(CALL), "key": "twin", "type": "testkit.http_call@1", "config": {"path": "/y"}})
    async with c:
        made = await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Twins", "draft": twins})
        assert made.status_code == 201, made.text  # the format allows it; validation refuses it later
        r = await c.get(f"/api/v1/t/{tid}/workflows/{made.json()['id']}/export")
    problem = {"reason": "duplicate_node", "binding": None, "node": CALL, "field": None}
    assert (r.status_code, r.json()) == (422, {"error": "not_portable", "problems": [problem]})


@pytest.mark.parametrize("alias", ALIASES.values(), ids=ALIASES.keys())
async def test_a_file_whose_steps_ids_are_one_uuid_creates_nothing(
    app, owner_sessionmaker, api_settings, alias
) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    twin = {"id": alias(SUB), "key": "twin", "type": "flow.run_workflow@1", "config": {"input": {}}}
    doc["graph"]["nodes"].append(twin)
    r, listed = await imported(app, owner_sessionmaker, api_settings, doc)
    problem = {"reason": "duplicate_node", "binding": None, "node": SUB, "field": None}
    assert (r.status_code, r.json()) == (422, {"error": "bad_document", "problems": [problem]})
    assert listed == []


MALFORMED: list[Callable[[dict], None]] = [
    lambda d: d.update(graph=None),
    lambda d: d.update(bindings=[None]),
    lambda d: d.update(format="other"),
    lambda d: d.update(format_version=2),
    lambda d: d.update(extra=1),
    lambda d: d["bindings"][0].update(id="B 1"),
    lambda d: d["bindings"][0].update(sites=[]),
    lambda d: d["bindings"][0]["sites"][0].update(node=7),
    lambda d: d["bindings"][0].update(kind="secret"),
]


@pytest.mark.parametrize("change", MALFORMED)
async def test_a_malformed_file_is_refused_and_nothing_is_created(
    app, owner_sessionmaker, api_settings, change
) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    change(doc)
    r, listed = await imported(app, owner_sessionmaker, api_settings, doc)
    assert r.status_code == 422 and r.json()["error"] == "invalid", r.text
    assert listed == []


async def test_a_draft_that_cant_be_made_portable_isnt_exported(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    odd = str(uuid.uuid4())
    unknown = draft(str(uuid.uuid4()), str(uuid.uuid4()))
    unknown["nodes"].append(
        {"id": odd, "key": "odd", "type": "vendor.unknown@1", "config": {"account": str(uuid.uuid4())}}
    )
    expression = draft(cel("vars.c"), str(uuid.uuid4()))
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Odd", "draft": unknown})).json()
        b = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Cel", "draft": expression})).json()
        first = await c.get(f"/api/v1/t/{tid}/workflows/{a['id']}/export")
        second = await c.get(f"/api/v1/t/{tid}/workflows/{b['id']}/export")
    problem = {"reason": "unknown_type", "binding": None, "node": odd, "field": None}
    assert (first.status_code, first.json()) == (422, {"error": "not_portable", "problems": [problem]})
    problem = {"reason": "unexpected_value", "binding": None, "node": CALL, "field": "/connection"}
    assert (second.status_code, second.json()) == (422, {"error": "not_portable", "problems": [problem]})


async def test_viewers_export_and_only_editors_import(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W"})).json()
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with viewer:
        doc = await viewer.get(f"/api/v1/t/{tid}/workflows/{wf['id']}/export")
        assert doc.status_code == 200
        r = await viewer.post(f"/api/v1/t/{tid}/workflows/import", json={"name": "X", "document": doc.json()})
        assert r.status_code == 403


def _send(token: object) -> dict:
    return {
        "graph_format": 1,
        "nodes": [{"id": CALL, "key": "send", "type": "testkit.ambiguous_send@1", "config": {"token": token}}],
        "edges": [],
    }  # noqa: E501


async def test_a_draft_holding_a_sensitive_literal_isnt_exported(app, owner_sessionmaker, api_settings) -> None:
    # Ledger M25: a value written into a field its type marks sensitive would travel in the file, to any tenant that
    # imports it. Export refuses it, by the validator's own rule (`sensitive.literal`), and never says it.
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        leaky = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Leaky", "draft": _send("tok-9f2c")})).json()
        r = await c.get(f"/api/v1/t/{tid}/workflows/{leaky['id']}/export")
        passed = (
            await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Passed", "draft": _send(ref("trigger.token"))})
        ).json()  # noqa: E501
        ok = await c.get(f"/api/v1/t/{tid}/workflows/{passed['id']}/export")
    problem = {"reason": "sensitive_literal", "binding": None, "node": CALL, "field": "/token"}
    assert (r.status_code, r.json()) == (422, {"error": "not_portable", "problems": [problem]})
    assert "tok-9f2c" not in r.text
    assert ok.status_code == 200, ok.text  # filled at run time from the run's input: nothing to carry
