# SPDX-License-Identifier: Apache-2.0
"""Ingress's tables and functions (engine 2b spec §8.3, §14; the owner's rulings 3 and 8 on the 2b-3b outline): every
table under forced row-level security; ingress holding **no table privilege**, only `EXECUTE` on its three SECURITY
DEFINER functions, each with a pinned `search_path` and closed to everyone else; an event and a binding belonging to
their endpoint's tenant by a foreign key; one binding per endpoint and workflow."""

import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dewpoint.core.db import tenant_scope
from tests.core.ingress.support import endpoint, state
from tests.support.workflows import seed_workflow

TABLES = ("webhook_endpoints", "trigger_bindings", "inbound_events", "tenant_event_counters")
FUNCTIONS = (
    "ingress_environment()",
    "resolve_webhook_endpoint(uuid)",
    "record_inbound_events(uuid, text, bigint, uuid[], bytea[], integer[], bytea[], bytea[])",
)
ROLES = ("dewpoint_api", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin", "dewpoint_auditor")


async def test_ingress_tables_force_row_level_security(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        rows = (await s.execute(text("select relname, relrowsecurity and relforcerowsecurity from pg_class "
                                     "where relname = any(:t)"), {"t": list(TABLES)})).all()  # fmt: skip
    assert sorted(rows) == sorted((t, True) for t in TABLES)


async def test_ingress_has_no_table_privilege_at_all(owner_sessionmaker, ingress_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        granted = (await s.execute(text(
            "select table_name, privilege_type from information_schema.role_table_grants "
            "where grantee = 'dewpoint_ingress'"
        ))).all()  # fmt: skip
    assert granted == []
    for table in (*TABLES, "tenant_event_keys", "platform_settings", "tenants", "data_keys", "run_requests"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with ingress_sessionmaker() as s:
                await s.execute(text(f"select 1 from {table} limit 1"))  # noqa: S608


async def test_only_ingress_executes_its_functions(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        for function in FUNCTIONS:
            allowed = text("select has_function_privilege(:r, :f, 'EXECUTE')")
            assert (await s.execute(allowed, {"r": "dewpoint_ingress", "f": function})).scalar_one() is True
            for role in ROLES:
                assert (await s.execute(allowed, {"r": role, "f": function})).scalar_one() is False, (role, function)
            acl = (await s.execute(text("select proacl::text from pg_proc where oid = cast(:f as regprocedure)"),
                                   {"f": function})).scalar_one()  # fmt: skip
            assert not any(entry.startswith("=") for entry in acl.strip("{}").split(","))  # no grant to PUBLIC


async def test_the_functions_are_definers_with_a_pinned_search_path(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        for function in FUNCTIONS:
            query = text("select prosecdef, proconfig from pg_proc where oid = cast(:f as regprocedure)")
            found = await s.execute(query, {"f": function})
            assert tuple(found.one()) == (True, ["search_path=public, pg_temp"])


async def test_an_event_and_a_binding_belong_to_their_endpoints_tenant(owner_sessionmaker) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    other, _ = await endpoint(owner_sessionmaker)
    _, workflow, _ = await seed_workflow(owner_sessionmaker)
    for statement, params in (
        ("insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes) "
         "values (:i, :t, :e, 1, '\\x01', 1)", {}),
        ("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
         "select :i, :t, :e, :w, created_by from webhook_endpoints where id = :e", {"w": workflow}),
    ):  # fmt: skip
        with pytest.raises(IntegrityError):
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text(statement), {"i": uuid.uuid4(), "t": other, "e": endpoint_id} | params)


async def test_one_binding_per_endpoint_and_workflow(owner_sessionmaker) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        user = (await s.execute(text("select created_by from webhook_endpoints where id = :e"),
                                {"e": endpoint_id})).scalar_one()  # fmt: skip
        workflow = uuid.uuid4()
        await s.execute(text("insert into workflows(id,tenant_id,name,enabled,draft) values (:w,:t,'W',true,'{}')"),
                        {"w": workflow, "t": tenant})  # fmt: skip
        insert = text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
                      "values (:i, :t, :e, :w, :u)")  # fmt: skip
        await s.execute(insert, {"i": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": workflow, "u": user})
    with pytest.raises(IntegrityError):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(insert, {"i": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": workflow, "u": user})


async def test_the_api_and_the_dispatcher_see_ingress_rows_within_their_tenant_only(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    for maker in (api_sessionmaker, dispatch_sessionmaker):
        for scope, seen in ((tenant, 1), (uuid.uuid4(), 0)):
            async with maker() as s, s.begin():
                await tenant_scope(s, scope)
                found = await s.execute(
                    text("select count(*) from webhook_endpoints where id = :e"), {"e": endpoint_id}
                )
                assert found.scalar_one() == seen


@pytest.mark.usefixtures("development_deployment")
async def test_the_resolver_returns_what_ingress_decides_with_and_nothing_for_another_id(
    owner_sessionmaker, ingress_sessionmaker
) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    async with ingress_sessionmaker() as s:
        found = (await s.execute(text("select * from resolve_webhook_endpoint(:e)"), {"e": endpoint_id})).mappings()
        row = dict(found.one())
        unknown = (await s.execute(text("select * from resolve_webhook_endpoint(:e)"), {"e": uuid.uuid4()})).all()
        environment = (await s.execute(text("select ingress_environment()"))).scalar_one()
    assert (row["tenant_id"], row["enabled"], row["tenant_active"], row["auth_kind"]) == (tenant, True, True, "bearer")
    assert (row["key_version"], len(row["public_key"]), row["body_limit"], row["id_source"]) == (1, 32, 1048576, "none")
    assert unknown == [] and environment == "development"


async def test_without_a_recorded_environment_ingress_reads_none(ingress_sessionmaker) -> None:
    async with ingress_sessionmaker() as s:
        assert (await s.execute(text("select ingress_environment()"))).scalar_one() is None


async def test_a_binding_cant_point_to_another_tenants_workflow(owner_sessionmaker, api_sessionmaker) -> None:
    """The owner's M1 review: a binding's workflow belongs to its tenant, by a foreign key, so not even the API's own
    insert, scoped to its tenant, can bind another tenant's workflow."""
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    _, foreign, _ = await seed_workflow(owner_sessionmaker)
    async with owner_sessionmaker() as s:
        user = (await s.execute(text("select created_by from webhook_endpoints where id = :e"),
                                {"e": endpoint_id})).scalar_one()  # fmt: skip
    with pytest.raises(IntegrityError):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(
                text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
                     "values (:i, :t, :e, :w, :u)"),
                {"i": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": foreign, "u": user},
            )  # fmt: skip


@pytest.mark.parametrize(
    ("columns", "changed"),
    [
        ({"id_source": "none"}, {"id_source": "pointer", "id_pointer": "/id"}),
        ({"id_source": "none"}, {"id_source": "header", "id_header": "x-event-id"}),
        ({"id_source": "pointer", "id_pointer": "/id"}, {"id_pointer": "/other"}),
        ({"id_source": "header", "id_header": "x-event-id"}, {"id_header": "x-other-id"}),
    ],
)
async def test_the_api_cant_change_where_an_endpoints_ids_are(
    owner_sessionmaker, api_sessionmaker, columns: dict[str, Any], changed: dict[str, Any]
) -> None:
    """The owner's docs review: where an endpoint's ids are decides how its later deliveries are deduplicated, so it
    never changes. Not even the API's own update, scoped to its tenant, can change it: its role has no grant on
    `id_source`, `id_pointer` or `id_header`."""
    tenant, endpoint_id = await endpoint(owner_sessionmaker, **columns)
    refused: DBAPIError | None = None
    try:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            sets = ", ".join(f"{column} = :{column}" for column in changed)
            await s.execute(text(f"update webhook_endpoints set {sets} where id = :e"),  # noqa: S608
                            {"e": endpoint_id} | changed)  # fmt: skip
    except DBAPIError as e:
        refused = e
    stored = await state(owner_sessionmaker, endpoint_id)
    assert {column: stored[column] for column in changed} == {column: columns.get(column) for column in changed}
    assert refused is not None and "permission denied" in str(refused.orig)


@pytest.mark.parametrize(
    ("column", "value"),
    [("request_per_s", 1000.0), ("request_burst", 100_000), ("event_per_s", 1000.0), ("event_burst", 100_000),
     ("byte_per_s", 1e9)],
)  # fmt: skip
async def test_the_apis_role_has_no_grant_to_update_an_endpoints_rates(
    owner_sessionmaker, api_sessionmaker, column: str, value: float
) -> None:
    """The owner's docs review: the API writes none of an endpoint's rates, so its role has no grant to update them.
    Least privilege, not a ceiling: the role still inserts every column of a new endpoint, and updates its byte burst,
    which a larger body limit needs."""
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    before = (await state(owner_sessionmaker, endpoint_id))[column]
    refused: DBAPIError | None = None
    try:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text(f"update webhook_endpoints set {column} = :v where id = :e"),  # noqa: S608
                            {"v": value, "e": endpoint_id})  # fmt: skip
    except DBAPIError as e:
        refused = e
    assert (await state(owner_sessionmaker, endpoint_id))[column] == before
    assert refused is not None and "permission denied" in str(refused.orig)


async def test_the_api_still_makes_endpoints_and_changes_what_it_manages(owner_sessionmaker, api_sessionmaker) -> None:
    """The control for the test above, as the API's role: it still makes an endpoint, and changes every column the
    API changes (a PATCH's fields, a rotated secret, the byte burst a larger body limit needs, the time)."""
    tenant, bearer = await endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s:
        user = (await s.execute(text("select created_by from webhook_endpoints where id = :e"),
                                {"e": bearer})).scalar_one()  # fmt: skip
    signed, digest = uuid.uuid4(), hashlib.sha256(b"rotated").digest()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await s.execute(
            text("insert into webhook_endpoints (id, tenant_id, name, created_by, auth_kind, hmac_secret, "
                 "signature_header, timestamp_header, id_source, id_pointer, dedupe_key) values (:i, :t, 'signed', :u, "
                 "'hmac', 'sealed', 'x-signature', 'x-timestamp', 'pointer', '/id', 'sealed-dedupe-key')"),
            {"i": signed, "t": tenant, "u": user},
        )  # fmt: skip
        await s.execute(
            text("update webhook_endpoints set hmac_secret = 'resealed', signature_header = 'x-sig', "
                 "timestamp_header = 'x-ts', updated_at = now() where id = :e"),
            {"e": signed},
        )  # fmt: skip
        await s.execute(
            text("update webhook_endpoints set name = 'renamed', enabled = false, allowlist = '{203.0.113.0/24}', "
                 "tolerance_s = 600, body_limit = 5242880, byte_burst = 26278400, events_pointer = '/events', "
                 "bearer_digest = :d, updated_at = now() where id = :e"),
            {"d": digest, "e": bearer},
        )  # fmt: skip
    made, changed = await state(owner_sessionmaker, signed), await state(owner_sessionmaker, bearer)
    assert (made["hmac_secret"], made["signature_header"], made["timestamp_header"]) == (b"resealed", "x-sig", "x-ts")
    assert (made["id_source"], made["id_pointer"]) == ("pointer", "/id")
    assert (changed["name"], changed["enabled"], changed["tolerance_s"], changed["body_limit"]) == (
        "renamed", False, 600, 5242880,
    )  # fmt: skip
    assert (changed["events_pointer"], changed["bearer_digest"], changed["byte_burst"]) == ("/events", digest, 26278400)


async def test_an_endpoints_default_event_rate_is_below_one_dispatchers_measured_drain(owner_sessionmaker) -> None:
    """The owner's M4 review: an endpoint's default event rate stays below what one dispatcher's own loop drains
    (`tests/probes/ingress_load.py drain`: 12.6 events/s at a fan-out of 5, 15.9 at 3, 22.9 at 1), so a sender keeping
    to it isn't refused for a backlog the platform can't clear. Its burst still admits a whole 500-event batch. A
    pending quota's 429 is backpressure, never a throughput promise."""
    _, endpoint_id = await endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s:
        rate, burst = (await s.execute(text("select event_per_s, event_burst from webhook_endpoints where id = :e"),
                                       {"e": endpoint_id})).one()  # fmt: skip
    assert (rate, burst) == (10, 1000)


async def test_a_tenants_default_event_rate_is_below_what_its_endpoints_drain_together(owner_sessionmaker) -> None:
    """The owner's M4 review: every match holds the tenant's counter row, so a tenant's endpoints are matched one at a
    time. `tests/probes/ingress_load.py tenant-drain` measured one tenant's four endpoints draining no faster than one
    (23.8 events/s against 22.9, 24.7 with two dispatchers), and `drain` 13.0 events/s at a fan-out of 5: the tenant's
    rate stays below that, whatever its number of endpoints. Its burst (5,000) is the abuse budget for a spike, which
    the pending quota then holds back; a 429 there is backpressure, never a throughput promise."""
    tenant, _ = await endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_event_counters (tenant_id) values (:t)"), {"t": tenant})
        rate, burst = (await s.execute(text("select event_per_s, event_burst from tenant_event_counters "
                                            "where tenant_id = :t"), {"t": tenant})).one()  # fmt: skip
    assert (rate, burst) == (10, 5000)
