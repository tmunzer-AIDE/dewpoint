# SPDX-License-Identifier: Apache-2.0
"""Migration 0042's `plugin_calls` (plugins-3 D3, D25): plugin code the worker runs for the API.

The API inserts a call, reads its result and deletes it, within its tenant, and never changes one. The worker claims
and answers, within its tenant, changing only the claim and the answer. It finds work across tenants only through a
function returning queue metadata for the refs and types its build has, and deletes long-expired calls only through
another. A call's shape follows its kind and state."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dewpoint.core.db import tenant_scope
from tests.support.connections import add_connection


async def tenant(owner: Any) -> uuid.UUID:
    tid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants (id, name, slug) values (:i, 't', :s)"), {"i": tid, "s": tid.hex[:12]}
        )
    return tid


INSERT_OPTIONS = (
    "insert into plugin_calls (id, tenant_id, kind, node_ref, field, query, expires_at) "
    "values (:i, :t, 'options', :ref, 'site_id', '', now() + make_interval(secs => :ttl))"
)


async def add_call(maker: Any, tid: uuid.UUID, *, ref: str = "demo.pick@1", ttl: float = 30) -> uuid.UUID:
    cid = uuid.uuid4()
    async with maker() as s, s.begin():
        await tenant_scope(s, tid)
        await s.execute(text(INSERT_OPTIONS), {"i": cid, "t": tid, "ref": ref, "ttl": ttl})
    return cid


async def test_the_table_forces_row_level_security(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        query = text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'plugin_calls'")
        assert tuple((await s.execute(query)).one()) == (True, True)


async def test_each_service_sees_only_its_tenants_calls(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    a, b = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    mine, theirs = await add_call(api_sessionmaker, a), await add_call(api_sessionmaker, b)
    for maker in (api_sessionmaker, worker_sessionmaker):
        async with maker() as s, s.begin():
            await tenant_scope(s, a)
            seen = set((await s.execute(text("select id from plugin_calls"))).scalars())
        assert seen == {mine} and theirs not in seen


async def test_the_api_never_inserts_for_another_tenant(owner_sessionmaker, api_sessionmaker) -> None:
    a, b = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(text(INSERT_OPTIONS), {"i": uuid.uuid4(), "t": b, "ref": "demo.pick@1", "ttl": 30})


async def test_the_api_deletes_but_never_changes_a_call(owner_sessionmaker, api_sessionmaker) -> None:
    a = await tenant(owner_sessionmaker)
    cid = await add_call(api_sessionmaker, a)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(text("update plugin_calls set state = 'failed', error = 'x' where id = :i"), {"i": cid})
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        assert (await s.execute(text("delete from plugin_calls where id = :i"), {"i": cid})).rowcount == 1


@pytest.mark.parametrize(
    "statement",
    [
        INSERT_OPTIONS,
        "update plugin_calls set node_ref = 'other.node@1' where id = :i",
        "update plugin_calls set query = 'x' where id = :i",
        "update plugin_calls set expires_at = now() + interval '1 day' where id = :i",
        "delete from plugin_calls where id = :i",
    ],
)
async def test_the_worker_changes_only_the_claim_and_the_answer(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker, statement: str
) -> None:
    a = await tenant(owner_sessionmaker)
    cid = await add_call(api_sessionmaker, a)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(text(statement), {"i": cid, "t": a, "ref": "demo.pick@1", "ttl": 30})
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        claimed = await s.execute(
            text(
                "update plugin_calls set state = 'claimed', claim_token = gen_random_uuid(), "
                "lease_until = now() + interval '15 seconds' where id = :i"
            ),
            {"i": cid},
        )
    assert claimed.rowcount == 1


async def _candidates(maker: Any, refs: list[str], types: list[str]) -> set[uuid.UUID]:
    async with maker() as s, s.begin():
        rows = await s.execute(
            text("select tenant_id, id from plugin_call_candidates(:r, :t, 50)"), {"r": refs, "t": types}
        )
        return {row[1] for row in rows}


async def test_candidates_are_the_due_calls_of_the_refs_and_types_a_build_has(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    a, b = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    due_a, due_b = await add_call(api_sessionmaker, a), await add_call(api_sessionmaker, b)
    other_ref = await add_call(api_sessionmaker, a, ref="demo.other@1")
    expired = await add_call(api_sessionmaker, a, ttl=-1)
    lapsed, live, done = [await add_call(api_sessionmaker, a) for _ in range(3)]
    conn = await add_connection(owner_sessionmaker, a, type_key="demo")
    verify = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "update plugin_calls set state = 'claimed', claim_token = gen_random_uuid(), "
                "lease_until = now() - interval '1 second' where id = :i"
            ),
            {"i": lapsed},
        )
        await s.execute(
            text(
                "update plugin_calls set state = 'claimed', claim_token = gen_random_uuid(), "
                "lease_until = now() + interval '15 seconds' where id = :i"
            ),
            {"i": live},
        )
        await s.execute(text("update plugin_calls set state = 'done', result_ct = '\\x00' where id = :i"), {"i": done})
        await s.execute(
            text(
                "insert into plugin_calls (id, tenant_id, kind, connection_type, connection_id, connection_revision, "
                "expires_at) values (:i, :t, 'verify', 'demo', :c, 1, now() + interval '30 seconds')"
            ),
            {"i": verify, "t": a, "c": conn},
        )
    found = await _candidates(worker_sessionmaker, ["demo.pick@1"], ["demo"])
    assert found == {due_a, due_b, lapsed, verify}
    assert not {other_ref, expired, live, done} & found
    assert await _candidates(worker_sessionmaker, [], []) == set()


async def test_only_the_worker_finds_candidates_or_sweeps(api_sessionmaker, dispatch_sessionmaker) -> None:
    for maker in (api_sessionmaker, dispatch_sessionmaker):
        for statement in ("select * from plugin_call_candidates(array['x@1'], array['x'], 1)",
                          "select plugin_calls_sweep()"):  # fmt: skip
            with pytest.raises(DBAPIError, match="permission denied"):
                async with maker() as s, s.begin():
                    await s.execute(text(statement))


async def test_the_sweep_deletes_calls_a_minute_past_their_expiry(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    a = await tenant(owner_sessionmaker)
    old = await add_call(api_sessionmaker, a, ttl=-61)
    recent = await add_call(api_sessionmaker, a, ttl=-1)
    async with worker_sessionmaker() as s, s.begin():
        assert (await s.execute(text("select plugin_calls_sweep()"))).scalar_one() == 1
    async with owner_sessionmaker() as s:
        left = set((await s.execute(text("select id from plugin_calls"))).scalars())
    assert left == {recent} and old not in left


BASE = {
    "kind": "options", "node_ref": "demo.pick@1", "field": "site_id", "connection_type": None, "connection_id": None,
    "connection_revision": None, "state": "pending", "claim_token": None, "lease_until": None, "result_ct": None,
    "error": None,
}  # fmt: skip
CONN = "the connection"


@pytest.mark.parametrize(
    "change",
    [
        {"node_ref": None},
        {"field": None},
        {"kind": "verify", "node_ref": None, "field": None, "connection_type": "demo"},
        {"kind": "verify", "node_ref": None, "field": None, "connection_type": "demo", "connection_id": CONN},
        {"connection_id": CONN},
        {"kind": "other"},
        {"state": "claimed"},
        {"state": "done"},
        {"state": "failed"},
        {"claim_token": uuid.uuid4(), "lease_until": datetime.now(UTC)},
        {"state": "unknown"},
    ],
)
async def test_a_calls_shape_follows_its_kind_and_state(owner_sessionmaker, change: dict[str, Any]) -> None:
    a = await tenant(owner_sessionmaker)
    conn = await add_connection(owner_sessionmaker, a, type_key="demo")
    row = {**BASE, **{k: (conn if v == CONN else v) for k, v in change.items()}}
    with pytest.raises(IntegrityError, match="check constraint"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(
                text(
                    "insert into plugin_calls (tenant_id, expires_at, kind, node_ref, field, connection_type, "
                    "connection_id, connection_revision, state, claim_token, lease_until, result_ct, error) "
                    "values (:t, now() + interval '30 seconds', :kind, :node_ref, :field, :connection_type, "
                    ":connection_id, :connection_revision, :state, :claim_token, :lease_until, :result_ct, :error)"
                ),
                {"t": a, **row},
            )


async def test_a_query_is_short(owner_sessionmaker, api_sessionmaker) -> None:
    a = await tenant(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="too long"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(
                text(
                    "insert into plugin_calls (tenant_id, kind, node_ref, field, query, expires_at) "
                    "values (:t, 'options', 'demo.pick@1', 'site_id', :q, now() + interval '30 seconds')"
                ),
                {"t": a, "q": "x" * 201},
            )


async def test_deleting_a_connection_deletes_its_calls(owner_sessionmaker) -> None:
    a = await tenant(owner_sessionmaker)
    conn = await add_connection(owner_sessionmaker, a, type_key="demo")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "insert into plugin_calls (tenant_id, kind, connection_type, connection_id, connection_revision, "
                "expires_at) values (:t, 'verify', 'demo', :c, 1, now() + interval '30 seconds')"
            ),
            {"t": a, "c": conn},
        )
        await s.execute(text("delete from connections where id = :c"), {"c": conn})
        assert (await s.execute(text("select count(*) from plugin_calls"))).scalar_one() == 0
