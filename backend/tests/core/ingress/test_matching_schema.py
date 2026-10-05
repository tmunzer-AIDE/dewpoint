# SPDX-License-Identifier: Apache-2.0
"""What matching, cancelling and the recount need from the schema (engine 2b spec §8.3; "Functions and lock order" in
the 2b-3b outline): the dispatcher picks pending events through `event_candidates(n)`, ids only, fairly across tenants
(every tenant's oldest due event before any tenant's second, FIFO within one); the recount's tenants through
`recount_candidates(n)`, each at most every 10 minutes; the API cancels within its tenant, releasing the pending
counters. Both functions are the dispatcher's alone, definers with a pinned path."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from tests.core.ingress.support import endpoint

FUNCTIONS = ("event_candidates(integer)", "recount_candidates(integer)")
FUTURE, PAST = datetime(2999, 1, 1, tzinfo=UTC), datetime(2000, 1, 1, tzinfo=UTC)
ROLES = ("dewpoint_api", "dewpoint_ingress", "dewpoint_worker", "dewpoint_admin", "dewpoint_auditor")


async def event(owner, tenant: uuid.UUID, endpoint_id: uuid.UUID, ago_s: int, **columns: object) -> uuid.UUID:
    """An event received `ago_s` seconds ago, pending unless `columns` say otherwise."""
    event_id = uuid.uuid4()
    values = {"status": "pending", "next_attempt_at": None, "ended_at": None} | columns
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes, status, "
                 "next_attempt_at, ended_at, received_at) values (:id, :t, :e, 1, '\\x01', 1, :status, "
                 ":next_attempt_at, :ended_at, now() - make_interval(secs => :ago))"),
            {"id": event_id, "t": tenant, "e": endpoint_id, "ago": ago_s} | values,
        )  # fmt: skip
    return event_id


async def candidates(dispatch, n: int = 50) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    async with dispatch() as s:
        found = await s.execute(text("select tenant_id, event_id, endpoint_id from event_candidates(:n)"), {"n": n})
        return [tuple(row) for row in found.all()]


async def test_every_tenants_oldest_due_event_comes_before_any_tenants_second(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    a, a_endpoint = await endpoint(owner_sessionmaker)
    b, b_endpoint = await endpoint(owner_sessionmaker)
    a1 = await event(owner_sessionmaker, a, a_endpoint, 50)
    a2 = await event(owner_sessionmaker, a, a_endpoint, 40)
    a3 = await event(owner_sessionmaker, a, a_endpoint, 30)
    b1 = await event(owner_sessionmaker, b, b_endpoint, 10)
    assert await candidates(dispatch_sessionmaker) == [
        (a, a1, a_endpoint), (b, b1, b_endpoint), (a, a2, a_endpoint), (a, a3, a_endpoint),
    ]  # fmt: skip
    assert [c[1] for c in await candidates(dispatch_sessionmaker, 2)] == [a1, b1]


async def test_only_due_pending_events_are_candidates(owner_sessionmaker, dispatch_sessionmaker) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    due = await event(owner_sessionmaker, tenant, endpoint_id, 60)
    await event(owner_sessionmaker, tenant, endpoint_id, 50, next_attempt_at=FUTURE)  # backing off
    await event(owner_sessionmaker, tenant, endpoint_id, 40, status="matched", ended_at=PAST)
    await event(owner_sessionmaker, tenant, endpoint_id, 30, status="dead", ended_at=PAST)
    again = await event(owner_sessionmaker, tenant, endpoint_id, 20, next_attempt_at=PAST)
    assert [c[1] for c in await candidates(dispatch_sessionmaker)] == [due, again]


async def test_a_tenant_is_recounted_at_most_every_ten_minutes(owner_sessionmaker, dispatch_sessionmaker) -> None:
    tenant, _ = await endpoint(owner_sessionmaker)
    other, _ = await endpoint(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_event_counters (tenant_id, recounted_at) values "
                             "(:t, null), (:o, now() - interval '9 minutes')"), {"t": tenant, "o": other})  # fmt: skip
    async with dispatch_sessionmaker() as s:
        found = (await s.execute(text("select tenant_id from recount_candidates(10)"))).scalars().all()
    assert found == [tenant]
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenant_event_counters set recounted_at = now() - interval '11 minutes' "
                             "where tenant_id = :o"), {"o": other})  # fmt: skip
    async with dispatch_sessionmaker() as s:
        found = (await s.execute(text("select tenant_id from recount_candidates(10)"))).scalars().all()
    assert found == [tenant, other]  # never recounted first, then the longest ago


async def test_the_candidate_functions_are_the_dispatchers_alone(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        for function in FUNCTIONS:
            allowed = text("select has_function_privilege(:r, :f, 'EXECUTE')")
            assert (await s.execute(allowed, {"r": "dewpoint_dispatch", "f": function})).scalar_one() is True
            for role in ROLES:
                assert (await s.execute(allowed, {"r": role, "f": function})).scalar_one() is False, (role, function)
            query = text("select prosecdef, proconfig, proacl::text from pg_proc where oid = cast(:f as regprocedure)")
            definer, config, acl = (await s.execute(query, {"f": function})).one()
            assert (definer, config) == (True, ["search_path=public, pg_temp"])
            assert not any(entry.startswith("=") for entry in acl.strip("{}").split(","))


async def test_the_api_cancels_within_its_tenant_and_releases_the_pending_counters(
    owner_sessionmaker, api_sessionmaker
) -> None:
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    other, other_endpoint = await endpoint(owner_sessionmaker)
    mine = await event(owner_sessionmaker, tenant, endpoint_id, 10)
    theirs = await event(owner_sessionmaker, other, other_endpoint, 10)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_event_counters (tenant_id) values (:t)"), {"t": tenant})
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        changed = await s.execute(text("update inbound_events set status = 'cancelled', reason = 'cancelled', "
                                       "ended_at = now() where id = any(:ids)"), {"ids": [mine, theirs]})  # fmt: skip
        assert changed.rowcount == 1  # row-level security: its own tenant's only
        await s.execute(text("update webhook_endpoints set pending_events = 0, pending_bytes = 0 where id = :e"),
                        {"e": endpoint_id})  # fmt: skip
        await s.execute(text("update tenant_event_counters set pending_events = 0, pending_bytes = 0 "
                             "where tenant_id = :t"), {"t": tenant})  # fmt: skip
    with pytest.raises(Exception, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text("update inbound_events set attempts = 9 where id = :e"), {"e": mine})
