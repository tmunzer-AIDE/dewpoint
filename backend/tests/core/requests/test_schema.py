# SPDX-License-Identifier: Apache-2.0
"""Admission's tables (engine 2b spec §7.1, §7.5, §14; revision 7's envelope): the request queue, the slots and the
limits under forced row-level security; the trigger's envelope stored beside its claims with a shape the database
enforces; `runs` ordered by when they were queued; and the one way the dispatcher sees every tenant's queue, which
shows it nothing but what it needs to pick."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dewpoint.core.db import tenant_scope
from tests.support.workflows import seed_workflow

TABLES = ("run_requests", "tenant_run_limits", "run_slots")


async def claim(
    s: Any, tenant: uuid.UUID, owner: uuid.UUID, *, role: str = "claim", pointer: str | None = ""
) -> uuid.UUID:
    claim_id = uuid.uuid4()
    await s.execute(
        text(
            "insert into run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, ciphertext, "
            "pointer, role) values (:id, :t, :o, :o, '[]', :c, :p, :r)"
        ),
        {"id": claim_id, "t": tenant, "o": owner, "c": b"\x01", "p": pointer, "r": role},
    )
    return claim_id


def request(tenant: uuid.UUID, wf: uuid.UUID, version: uuid.UUID | None, **extra: Any) -> dict[str, Any]:
    return {"id": uuid.uuid4(), "tenant_id": tenant, "workflow_id": wf, "workflow_version_id": version,
            "source": "manual", "mode": "live", "idempotency_key": str(uuid.uuid4()), "digest": b"\x02" * 32,
            "digest_key_version": 1, "status": "queued", "envelope_id": None, **extra}  # fmt: skip


INSERT_REQUEST = text(
    "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, idempotency_key, digest, "
    "digest_key_version, status, envelope_id, ended_at, starting_at) values (:id, :tenant_id, :workflow_id, "
    ":workflow_version_id, :source, :mode, :idempotency_key, :digest, :digest_key_version, cast(:status as varchar), "
    ":envelope_id, case when cast(:status as varchar) in ('cancelled', 'refused', 'dead') then now() end, "
    "case when cast(:status as varchar) = 'starting' then now() end)"
)


@pytest.mark.parametrize("table", TABLES)
async def test_each_admission_table_forces_row_level_security(owner_sessionmaker, table) -> None:
    async with owner_sessionmaker() as s:
        flags = (
            await s.execute(
                text("select relrowsecurity, relforcerowsecurity from pg_class where relname = :t"), {"t": table}
            )
        ).one()
    assert tuple(flags) == (True, True)


async def test_a_request_with_its_envelope_is_seen_only_within_its_tenant(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    other, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
    values = request(tenant, wf, version)
    async with api_sessionmaker() as s, s.begin():  # admission runs in the API's transaction (ruling 2)
        await tenant_scope(s, tenant)
        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
        await s.execute(INSERT_REQUEST, values)
    count = text("select count(*) from run_requests")
    for maker in (api_sessionmaker, dispatch_sessionmaker):
        async with maker() as s, s.begin():
            assert (await s.execute(count)).scalar_one() == 0
            await tenant_scope(s, other)
            assert (await s.execute(count)).scalar_one() == 0
        async with maker() as s, s.begin():
            await tenant_scope(s, tenant)
            assert (await s.execute(count)).scalar_one() == 1


async def test_the_worker_never_reads_the_queue(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text("select count(*) from run_requests"))


async def test_only_a_refused_request_has_no_envelope(owner_sessionmaker) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(INSERT_REQUEST, request(tenant, wf, None, status="refused"))  # refused before it was frozen
    with pytest.raises(IntegrityError, match="run_requests_envelope_iff_admitted"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(INSERT_REQUEST, request(tenant, wf, version))
    async with owner_sessionmaker() as s, s.begin():
        values = request(tenant, wf, version, status="refused")
        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
        with pytest.raises(IntegrityError, match="run_requests_envelope_iff_admitted"):
            await s.execute(INSERT_REQUEST, values)


async def test_a_request_reaches_only_an_envelope_it_owns(owner_sessionmaker) -> None:
    """The reference can't name a claim, nor another request's envelope (revision 7: an enforced shape)."""
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    for role, owned in (("claim", True), ("envelope", False)):
        with pytest.raises(IntegrityError, match="run_requests_envelope"):
            async with owner_sessionmaker() as s, s.begin():
                values = request(tenant, wf, version)
                owner = values["id"] if owned else uuid.uuid4()
                pointer = "" if role == "claim" else None
                values["envelope_id"] = await claim(s, tenant, owner, role=role, pointer=pointer)
                await s.execute(INSERT_REQUEST, values)


async def test_an_envelope_outlives_no_request_and_stands_alone_per_owner(owner_sessionmaker) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    values = request(tenant, wf, version)
    async with owner_sessionmaker() as s, s.begin():
        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
        await s.execute(INSERT_REQUEST, values)
    with pytest.raises(IntegrityError, match="run_requests_envelope"):  # retention deletes both together, never one
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("delete from run_inputs where id = :e"), {"e": values["envelope_id"]})
    with pytest.raises(IntegrityError, match="run_inputs_one_envelope"):
        async with owner_sessionmaker() as s, s.begin():
            await claim(s, tenant, values["id"], role="envelope", pointer=None)


@pytest.mark.parametrize(("role", "pointer"), [("claim", None), ("envelope", ""), ("envelope", "/a"), ("other", "")])
async def test_a_claim_has_a_pointer_and_an_envelope_none(owner_sessionmaker, role, pointer) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    with pytest.raises(IntegrityError, match="run_inputs_role"):
        async with owner_sessionmaker() as s, s.begin():
            await claim(s, tenant, uuid.uuid4(), role=role, pointer=pointer)


async def test_an_idempotency_key_is_one_request_per_tenant(owner_sessionmaker) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    other, wf2, version2 = await seed_workflow(owner_sessionmaker, name="Other")
    first = request(tenant, wf, version, status="refused", workflow_version_id=None)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(INSERT_REQUEST, first)
        await s.execute(
            INSERT_REQUEST, request(other, wf2, None, status="refused", idempotency_key=first["idempotency_key"])
        )
    with pytest.raises(IntegrityError, match="run_requests_idempotency"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(
                INSERT_REQUEST, request(tenant, wf, None, status="refused", idempotency_key=first["idempotency_key"])
            )


async def test_runs_are_queued_before_they_start(owner_sessionmaker) -> None:
    """A root run's row is written at dispatch, before Temporal answers: it's queued at once and started only once the
    start is confirmed (§7.3)."""
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, iterations) "
                "values (:id, :t, :w, :v, 'live', 'running', 0)"
            ),  # fmt: skip
            {"id": uuid.uuid4(), "t": tenant, "w": wf, "v": version},
        )
        row = (await s.execute(text("select queued_at is not null, started_at from runs"))).one()
    assert tuple(row) == (True, None)


async def test_the_current_build_is_written_by_the_dispatcher_and_read_by_admission(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    async with dispatch_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "insert into current_build (id, build_id, engine_abi, observed_at) values (1, 'b6', 6, now()) "
                "on conflict (id) do update set build_id = excluded.build_id, engine_abi = excluded.engine_abi, "
                "observed_at = excluded.observed_at"
            )  # fmt: skip
        )
    async with api_sessionmaker() as s:
        assert (await s.execute(text("select build_id, engine_abi from current_build"))).one() == ("b6", 6)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await s.execute(text("update current_build set engine_abi = 5"))


async def test_the_dispatcher_picks_from_every_tenant_seeing_only_what_it_needs(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    """Ruling 3: across tenants, only queue-selection metadata. The oldest due request of each tenant, FIFO among due
    ones: one waiting for its next attempt doesn't hold back those behind it."""
    a, wf_a, v_a = await seed_workflow(owner_sessionmaker)
    b, wf_b, v_b = await seed_workflow(owner_sessionmaker, name="B")
    rows = []
    async with owner_sessionmaker() as s, s.begin():
        for tenant, wf, v, delay in ((a, wf_a, v_a, "1 hour"), (a, wf_a, v_a, None), (a, wf_a, v_a, None),
                                     (b, wf_b, v_b, None)):  # fmt: skip
            values = request(tenant, wf, v)
            values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
            await s.execute(INSERT_REQUEST, values)
            await s.execute(text("update run_requests set queued_at = now() + make_interval(secs => :n) where id = :i"),
                            {"n": len(rows), "i": values["id"]})  # queued in this order  # fmt: skip
            if delay:
                await s.execute(text(f"update run_requests set next_attempt_at = now() + interval '{delay}' "
                                     "where id = :i"), {"i": values["id"]})  # fmt: skip
            rows.append(values["id"])
    async with dispatch_sessionmaker() as s:
        picked = (await s.execute(text("select * from dispatch_candidates(10)"))).mappings().all()
    assert {(r["tenant_id"], r["request_id"]) for r in picked} == {(a, rows[1]), (b, rows[3])}
    assert set(picked[0].keys()) == {"tenant_id", "request_id"}
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s:
            await s.execute(text("select * from dispatch_candidates(10)"))


async def test_a_slot_is_reserved_by_the_dispatcher_and_released_by_the_end_write(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    run = uuid.uuid4()
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await s.execute(text("insert into run_slots (tenant_id, run_id) values (:t, :r)"), {"t": tenant, "r": run})
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert (await s.execute(text("delete from run_slots where run_id = :r"), {"r": run})).rowcount == 1


async def test_a_tenant_is_active_until_it_is_erased(owner_sessionmaker) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        assert (
            await s.execute(text("select status from tenants where id = :t"), {"t": tenant})
        ).scalar_one() == "active"
    with pytest.raises(IntegrityError, match="tenants_status"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update tenants set status = 'paused' where id = :t"), {"t": tenant})


# Who may do what (§7, §14): admission freezes requests in the API's transaction and a user cancels a queued one; the
# dispatcher moves requests, reserves slots under the limits row and records the current build; the worker's end write
# releases a slot. Column-level grants narrow the API's updates to a cancel's columns.
ALLOWED = {
    ("admin", "run_requests"): {"select", "update"},  # a forced retirement cancels queued requests (engine-core §4.5)
    ("api", "run_requests"): {"select", "insert", "update"},
    ("api", "tenant_run_limits"): {"select"},
    ("api", "run_slots"): {"select"},
    ("api", "current_build"): {"select"},
    ("dispatch", "run_requests"): {"select", "insert", "update"},
    ("dispatch", "tenant_run_limits"): {"select", "insert", "update"},
    ("dispatch", "run_slots"): {"select", "insert", "delete"},
    ("dispatch", "current_build"): {"select", "insert", "update"},
    ("worker", "run_slots"): {"select", "delete"},
}
ROLES = ("api", "dispatch", "worker", "admin", "auditor")
OPS = ("select", "insert", "update", "delete")


@pytest.mark.parametrize("table", [*TABLES, "current_build"])
async def test_each_role_has_exactly_its_privileges(owner_sessionmaker, table) -> None:
    async with owner_sessionmaker() as s:
        for role in ROLES:
            for op in OPS:
                granted = (
                    await s.execute(
                        text(  # an update granted on a cancel's columns only counts too; a delete is whole-table
                            "select has_table_privilege(:r, :t, :p) "
                            "or (:p <> 'delete' and has_any_column_privilege(:r, :t, :p))"
                        ),
                        {"r": f"dewpoint_{role}", "t": table, "p": op},
                    )
                ).scalar_one()
                assert granted == (op in ALLOWED.get((role, table), set())), (role, table, op)


async def test_the_api_updates_only_what_a_cancel_changes(owner_sessionmaker, api_sessionmaker) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    values = request(tenant, wf, version)
    async with owner_sessionmaker() as s, s.begin():
        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
        await s.execute(INSERT_REQUEST, values)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        cancel = (
            "update run_requests set status = 'cancelled', reason = 'user_cancelled', ended_at = now() where id = :i"
        )
        await s.execute(text(cancel), {"i": values["id"]})
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text("update run_requests set attempts = 9 where id = :i"), {"i": values["id"]})


async def test_a_request_reaches_no_envelope_of_another_tenant(owner_sessionmaker) -> None:
    """The reference proves the envelope's tenant too, not only its id, owner and role (the owner's M1 checkpoint)."""
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    other, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
    with pytest.raises(IntegrityError, match="run_requests_envelope"):
        async with owner_sessionmaker() as s, s.begin():
            values = request(tenant, wf, version)
            values["envelope_id"] = await claim(s, other, values["id"], role="envelope", pointer=None)
            await s.execute(INSERT_REQUEST, values)
