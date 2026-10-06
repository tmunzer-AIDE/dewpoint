# SPDX-License-Identifier: Apache-2.0
"""Run executions' evidence (the owner's M3 rulings): a terminal row isn't proof that Temporal closed an execution,
and retention can delete the row before Temporal deletes its history. Each root's evidence is written with each start
attempt, before Temporal is asked. The dispatcher's leader reads each closed execution's history exactly (its chain's
first run, its continuation, every child it started) and records each, until Temporal shows the execution gone; one
seen and gone before it was read is lost. One Temporal never showed is pending, never judged: nothing proves the
namespace's retention over the time it went unchecked (the value reported now can't), so it may still land, or have
landed and gone unseen, starting children no one recorded. Both keep every key they could hold. Retiring a key proves
each execution that could hold it gone, by describing it: one open, retained, not yet read, lost or pending keeps the
key."""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio import workflow
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from dewpoint.apps.dispatcher import evidence
from dewpoint.core.crypto import retire
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.core.retention.support import OLD, TREE_ROWS, count, sql, tenant, tree
from tests.support.keys import FIXTURE_CONVERTER

QUEUE = "dewpoint-evidence-test"
RETENTION = timedelta(days=1)


@workflow.defn(name="EvidenceChild")
class Child:
    @workflow.run
    async def run(self, hold: bool) -> str:
        if hold:  # open until terminated
            await workflow.wait_condition(lambda: False)
        return "done"


@workflow.defn(name="EvidenceParent")
class Parent:
    """A child, then a continuation, whose own child it waits for; with `orphan`, a child it abandons, still open."""

    @workflow.run
    async def run(self, spec: dict[str, Any]) -> str:
        child = run_workflow_id(spec["tenant"], str(workflow.uuid4()))
        await workflow.execute_child_workflow("EvidenceChild", False, id=child, task_queue=QUEUE)
        if spec["round"] == 0:
            workflow.continue_as_new({**spec, "round": 1})
        if spec["orphan"]:
            await workflow.start_child_workflow("EvidenceChild", True, id=spec["orphan"], task_queue=QUEUE,
                                                parent_close_policy=workflow.ParentClosePolicy.ABANDON)  # fmt: skip
        return "done"


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


@pytest.fixture
async def client(server) -> AsyncIterator[Client]:
    target = server.client.service_client.config.target_host  # its own client: another test's worker may linger
    own = await Client.connect(target, namespace=server.client.namespace, data_converter=FIXTURE_CONVERTER)
    async with Worker(own, task_queue=QUEUE, workflows=[Parent, Child], workflow_runner=UnsandboxedWorkflowRunner()):
        yield own


async def _root(owner: Any, tenant_id: uuid.UUID, workflow_id: str, *, ago: timedelta = timedelta(0),
                read: bool = False, seen: bool = False, checked: timedelta | None = None,
                unproven: bool = False) -> None:  # fmt: skip
    """A root's evidence, written `ago`; `checked`: how long ago Temporal was last asked about it."""
    await sql(owner, "insert into execution_evidence (tenant_id, workflow_id, started_at, read_at, seen_at, "
              "checked_at, unproven) values (:t, :w, now() - cast(:ago as interval), case when :read then now() end, "
              "case when :seen then now() end, now() - cast(:checked as interval), :unproven)", t=tenant_id,
              w=workflow_id, ago=ago, read=read, seen=seen, checked=checked, unproven=unproven)  # fmt: skip


async def _rows(owner: Any, tenant_id: uuid.UUID) -> list[tuple[str, str | None, bool, bool]]:
    async with owner() as s:
        found = await s.execute(
            text(
                "select workflow_id, run_id, read_at is not null, lost_at is not null "
                "from execution_evidence where tenant_id = :t order by id"
            ),
            {"t": tenant_id},
        )
        return [tuple(r) for r in found]  # type: ignore[misc]


async def _passes(dispatch: Any, client: Client, owner: Any, n: int = 8) -> None:
    """The leader's passes, each row made due first (a pass schedules its next look ahead)."""
    for _ in range(n):
        await sql(owner, "update execution_evidence set next_check_at = now() where read_at is null")
        await evidence.check_evidence(dispatch, client, retention=RETENTION)


async def _proof(admin: Any, client: Client, tenant_id: uuid.UUID, *,
                 before: timedelta | None = None) -> tuple[int, ...]:  # fmt: skip
    """(open, retained, unread, lost, pending), of the executions started before `before` ago (None: all)."""
    async with admin() as s, s.begin():
        await tenant_scope(s, tenant_id)
        at = None if before is None else (await s.execute(text("select now() - cast(:b as interval)"),
                                                          {"b": before})).scalar_one()  # fmt: skip
        p = await evidence.prove(s, client, tenant_id, before=at)
    return p.open, p.retained, p.unread, p.lost, p.pending


async def test_a_chain_and_every_child_it_started_are_recorded_from_its_history(
    client, owner_sessionmaker, dispatch_sessionmaker, admin_sessionmaker
) -> None:
    ctx = await tenant(owner_sessionmaker)
    t = str(ctx["t"])
    root, orphan = run_workflow_id(t, str(uuid.uuid4())), run_workflow_id(t, str(uuid.uuid4()))
    await _root(owner_sessionmaker, ctx["t"], root)  # as its row's insert writes it
    handle = await client.start_workflow("EvidenceParent", {"tenant": t, "round": 0, "orphan": orphan}, id=root,
                                         task_queue=QUEUE)  # fmt: skip
    assert await handle.result() == "done"
    await _passes(dispatch_sessionmaker, client, owner_sessionmaker)
    described = await client.get_workflow_handle(root).describe()
    first, last = described.raw_description.workflow_execution_info.first_run_id, described.run_id
    found = await _rows(owner_sessionmaker, ctx["t"])
    assert {(w, r) for w, r, read, _ in found if w == root and read} == {(root, first), (root, last)}
    children = [(w, read) for w, _, read, _ in found if w != root]
    assert len(children) == 3 and all(w.startswith(f"t:{t}:run:") for w, _ in children)
    assert sorted(read for w, read in children) == [False, True, True]  # the orphan is still open: not yet read
    assert not any(lost for *_, lost in found)
    assert await _proof(admin_sessionmaker, client, ctx["t"]) == (1, 4, 0, 0, 0)
    await client.get_workflow_handle(orphan).terminate()
    await _passes(dispatch_sessionmaker, client, owner_sessionmaker, n=2)
    assert await _proof(admin_sessionmaker, client, ctx["t"]) == (0, 5, 0, 0, 0)


async def test_what_temporal_doesnt_show_is_proven_gone_lost_or_pending_never_judged_by_retention(
    client, owner_sessionmaker, dispatch_sessionmaker, admin_sessionmaker
) -> None:
    """An execution Temporal doesn't show: read before, it's proven gone (its row goes); seen before and never read,
    its history went unread (lost); never seen, it's pending, whatever its age or the retention Temporal reports,
    known or not, and however long it went unchecked: nothing proves the retention over that time."""
    ctx = await tenant(owner_sessionmaker)
    t = str(ctx["t"])
    unseen, seen, young, done = (run_workflow_id(t, str(uuid.uuid4())) for _ in range(4))
    await _root(owner_sessionmaker, ctx["t"], unseen, ago=timedelta(days=2))
    await _root(owner_sessionmaker, ctx["t"], seen, ago=timedelta(hours=1), seen=True)
    await _root(owner_sessionmaker, ctx["t"], young)
    await _root(owner_sessionmaker, ctx["t"], done, ago=timedelta(days=40), read=True, seen=True)
    for retention in (None, RETENTION, timedelta(days=30)):
        await sql(owner_sessionmaker, "update execution_evidence set next_check_at = now()")
        await evidence.check_evidence(dispatch_sessionmaker, client, retention=retention)
        assert {(w, gone) for w, _, _, gone in await _rows(owner_sessionmaker, ctx["t"])} == {
            (unseen, False), (seen, True), (young, False),
        }  # fmt: skip
    assert await _proof(admin_sessionmaker, client, ctx["t"]) == (0, 0, 0, 1, 2)


async def test_a_retention_increase_never_lets_an_unseen_start_pass_for_a_newer_key(
    client, owner_sessionmaker, dispatch_sessionmaker, admin_sessionmaker
) -> None:
    """The owner's M3 review: a start the leader never saw may have landed while the retention was short, closed, and
    gone, after starting children no one recorded; a longer retention reported since, and later checks, change nothing.
    It keeps every key it could hold: any made after its attempt, too. Only a key whose successor reached every cache
    before its attempt is beyond it."""
    ctx = await tenant(owner_sessionmaker)
    unseen = run_workflow_id(str(ctx["t"]), str(uuid.uuid4()))
    await _root(owner_sessionmaker, ctx["t"], unseen, ago=timedelta(days=3), checked=timedelta(days=2), unproven=True)
    for _ in range(3):  # a longer retention, checked often since
        await sql(owner_sessionmaker, "update execution_evidence set next_check_at = now()")
        await evidence.check_evidence(dispatch_sessionmaker, client, retention=timedelta(days=30))
    assert await _proof(admin_sessionmaker, client, ctx["t"]) == (0, 0, 0, 0, 1)  # every key from before it on
    assert await _proof(admin_sessionmaker, client, ctx["t"], before=timedelta(days=4)) == (0, 0, 0, 0, 0)


async def test_a_run_closing_after_the_floor_keeps_its_key_after_retention_pruned_its_row(
    client, owner_sessionmaker, dispatch_sessionmaker, admin_sessionmaker, retention_sessionmaker, api_settings
) -> None:
    """The owner's M3 timeline: a run started under key 1 closes long after key 2 replaced it, past the payload floor,
    and its tenant's retention deletes its row: no row says it ran, and the floor has passed. Its history is still in
    Temporal: its evidence keeps key 1. Once Temporal shows it gone, the key retires."""
    from dewpoint.core.crypto.kek import KekSet
    from dewpoint.core.crypto.keyring import Keyring
    from dewpoint.core.retention import sweep

    keyring = Keyring(KekSet.from_settings(api_settings))
    ctx = await tenant(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx["t"])
        await keyring.ensure_key(s, ctx["t"])
        await keyring.rotate(s, ctx["t"])
    await sql(owner_sessionmaker, "update data_keys set created_at = now() - interval '100 days' "
              "where tenant_id = :t and version = 2", t=ctx["t"])  # fmt: skip
    await sql(owner_sessionmaker, "insert into run_duration_limits (days) values (1)")
    ran = await tree(owner_sessionmaker, ctx, OLD)  # its row, which wrote its evidence
    await sql(owner_sessionmaker, "update execution_evidence set started_at = now() - interval '101 days' "
              "where tenant_id = :t", t=ctx["t"])  # started before key 2  # fmt: skip
    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])
    assert await count(owner_sessionmaker, TREE_ROWS, r=ran["root"]) == 0  # pruned
    root = run_workflow_id(str(ctx["t"]), str(ran["root"]))
    closed = await client.start_workflow("EvidenceChild", False, id=root, task_queue=QUEUE)
    assert await closed.result() == "done"  # it closes now, past the floor
    await _passes(dispatch_sessionmaker, client, owner_sessionmaker, n=2)

    async def checks() -> dict[str, bool]:
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx["t"])
            before = await retire.candidates_before(s, ctx["t"], 1)
            proof = await evidence.prove(s, client, ctx["t"], before=before)
            found = await retire.checks(s, ctx["t"], 1, namespace_retention=timedelta(days=30), run_histories=proof)
            return {c.name: c.ok for c in found}

    found = await checks()
    assert {name for name, ok in found.items() if not ok} == {"run_histories"}, found
    gone = run_workflow_id(str(ctx["t"]), str(uuid.uuid4()))  # as Temporal deleting its history would show it
    await sql(owner_sessionmaker, "update execution_evidence set workflow_id = :w where tenant_id = :t", w=gone,
              t=ctx["t"])  # fmt: skip
    assert all((await checks()).values())
    assert await _rows(owner_sessionmaker, ctx["t"]) == []  # proven gone: its evidence went


async def test_the_leader_reads_the_namespaces_retention_at_most_every_five_minutes(monkeypatch) -> None:
    """A dispatcher cycle runs every second; the retention its pass schedules the next look by is read once a while."""
    import time

    reads: list[int] = []

    async def read(client: Any) -> timedelta:
        reads.append(1)
        return RETENTION

    monkeypatch.setattr(evidence, "namespace_retention", read)
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    cached = evidence.Retention()
    for step in (0, 60, 239):  # within 5 minutes of the first read
        clock[0] += step
        assert await cached(None) == RETENTION  # type: ignore[arg-type]
    assert len(reads) == 1
    clock[0] += 1
    await cached(None)  # type: ignore[arg-type]
    assert len(reads) == 2
