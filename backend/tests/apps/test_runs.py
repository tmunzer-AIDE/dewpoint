# SPDX-License-Identifier: Apache-2.0
"""`start_run` (spec §4.5, §9): admission of the workflow's active version under the lifecycle locks."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps import runs as run_ops
from dewpoint.apps import workflow_ops
from dewpoint.apps.runs import START_FAILED, NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import lifecycle
from dewpoint.core.runs import service
from dewpoint.core.workflows import service as workflows
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, SIMULATE, RunInput
from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
from tests.apps.test_workflow_ops import ECHO, ECHO_GRAPH, actor, create, publish, save, update
from tests.support.registry import sync_test_plugins


@dataclass(frozen=True)
class LostAck:
    """Temporal accepts the start, but its answer never arrives: the client sees `error`."""

    error: BaseException


def rpc(status: RPCStatusCode) -> RPCError:
    return RPCError(status.name.lower(), status, b"")


class FakeClient:
    """Temporal's start, as start_run sees it. Each call takes the next answer: None accepts, an exception refuses,
    and a LostAck accepts but raises. Like the server, it refuses a workflow id it already accepted."""

    def __init__(self, *answers: BaseException | LostAck | None) -> None:
        self.answers = list(answers)
        self.started: list[tuple[RunInput, str, str]] = []
        self.calls: list[tuple[str, WorkflowIDReusePolicy]] = []

    async def start_workflow(
        self, _run: Any, arg: RunInput, *, id: str, task_queue: str, id_reuse_policy: WorkflowIDReusePolicy
    ) -> None:
        self.calls.append((id, id_reuse_policy))
        answer = self.answers.pop(0) if self.answers else None
        if any(started == id for _, started, _ in self.started):
            raise WorkflowAlreadyStartedError(id, "RunGraph")
        if isinstance(answer, BaseException):
            raise answer
        self.started.append((arg, id, task_queue))
        if isinstance(answer, LostAck):
            raise answer.error


@pytest.fixture(autouse=True)
def no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_ops, "START_RETRY_S", (0.0, 0.0))


async def published(owner: Any, api: Any, admin: Any, settings: Any) -> tuple[Any, uuid.UUID, uuid.UUID]:
    await sync_test_plugins(admin)
    ctx = await actor(owner)
    wf = await create(api, ctx, ECHO_GRAPH)
    out = await publish(api, ctx, wf, settings)
    assert out.version is not None
    return ctx, wf, out.version.id


async def run_row(sm: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> Any:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        return await service.get_run(s, run_id)


async def test_the_active_version_starts_with_its_run_id_as_the_workflow_id(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient()
    run_id = await start_run(
        dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
        tenant_id=ctx.tenant_id, version_id=version, trigger={"x": 1}, mode=SIMULATE,
    )  # fmt: skip
    [(arg, workflow_id, queue)] = client.started
    assert (workflow_id, queue) == (str(run_id), ENGINE_QUEUE)
    assert (arg.version_id, arg.trigger, arg.mode) == (str(version), {"x": 1}, SIMULATE)
    assert arg.max_run_duration_s == api_settings.max_run_duration_days * 86_400
    row = await run_row(owner_sessionmaker, ctx.tenant_id, run_id)
    assert (row.status, row.mode, row.workflow_version_id) == ("running", SIMULATE, version)


async def test_only_the_active_version_of_an_enabled_workflow_is_admitted(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, first = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await save(api_sessionmaker, ctx, wf, ECHO_GRAPH)
    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None  # supersedes `first`
    with pytest.raises(NotAdmissibleError, match="active version"):
        await start_run(
            dispatch_sessionmaker, FakeClient(), api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=first, trigger={},
        )  # fmt: skip
    await update(api_sessionmaker, ctx, wf, enabled=False)
    with pytest.raises(NotAdmissibleError, match="disabled"):
        await start_run(
            dispatch_sessionmaker, FakeClient(), api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=first, trigger={},
        )  # fmt: skip


async def only_run(owner: Any, tenant: uuid.UUID) -> Any:
    async with owner() as s, s.begin():
        await tenant_scope(s, tenant)
        [row] = await service.list_runs(s)
    return row


@pytest.mark.parametrize(
    ("answers", "calls"),
    [
        ((rpc(RPCStatusCode.INVALID_ARGUMENT),), 1),  # refused outright: no retry
        ((rpc(RPCStatusCode.RESOURCE_EXHAUSTED),) * 3, 3),  # throttled every time: never accepted
    ],
)
async def test_a_confirmed_refusal_records_the_run_as_failed(
    owner_sessionmaker,
    api_sessionmaker,
    admin_sessionmaker,
    dispatch_sessionmaker,
    api_settings,
    answers: tuple[RPCError, ...],
    calls: int,
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient(*answers)
    with pytest.raises(StartRefusedError):
        await start_run(
            dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=version, trigger={},
        )  # fmt: skip
    row = await only_run(owner_sessionmaker, ctx.tenant_id)
    assert (row.status, row.error_code, len(client.calls)) == ("failed", START_FAILED, calls)


async def test_a_lost_acknowledgement_is_reconciled_by_the_workflow_id(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Review finding: Temporal accepted the run, but the answer was lost. The retry with the same workflow id is
    refused as a duplicate, which confirms the start; the run is running, not failed."""
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient(LostAck(rpc(RPCStatusCode.UNAVAILABLE)))
    run_id = await start_run(
        dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
        tenant_id=ctx.tenant_id, version_id=version, trigger={},
    )  # fmt: skip
    assert len(client.started) == 1  # started once, not twice
    assert client.calls == [(str(run_id), WorkflowIDReusePolicy.REJECT_DUPLICATE)] * 2
    assert (await only_run(owner_sessionmaker, ctx.tenant_id)).status == "running"


async def test_a_start_that_stays_uncertain_leaves_the_run_running(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """No answer ever confirms or refuses: the run may be executing, so it isn't marked failed. 2b's dispatcher
    retries until it knows; here the caller is told."""
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient(ConnectionResetError(), rpc(RPCStatusCode.DEADLINE_EXCEEDED), rpc(RPCStatusCode.UNAVAILABLE))
    with pytest.raises(StartUncertainError) as e:
        await start_run(
            dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=version, trigger={},
        )  # fmt: skip
    row = await only_run(owner_sessionmaker, ctx.tenant_id)
    assert (row.status, row.error_code, len(client.calls), e.value.run_id) == ("running", None, 3, row.id)


async def test_retirement_first_makes_admission_refuse(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    async with admin_sessionmaker() as a:
        async with a.begin():
            await lifecycle.lock_exclusive(a, ECHO)
            starting = asyncio.create_task(
                start_run(
                    dispatch_sessionmaker,
                    FakeClient(),
                    api_settings,  # type: ignore[arg-type]
                    tenant_id=ctx.tenant_id,
                    version_id=version,
                    trigger={},
                )  # fmt: skip
            )
            await until_someone_waits_for_a_lock(owner_sessionmaker)
            await lifecycle.retire(a, ECHO, force=True, confirm=True)
    with pytest.raises(NotAdmissibleError, match="retired"):
        await asyncio.wait_for(starting, 10)


async def test_admission_first_holds_retirement_until_the_run_exists(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(run_ops, "_admission_locked", paused)
    client = FakeClient()
    starting = asyncio.create_task(
        start_run(
            dispatch_sessionmaker,
            client,
            api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id,
            version_id=version,
            trigger={},
        )  # fmt: skip
    )
    await asyncio.wait_for(reached.wait(), 10)

    async def retire() -> Any:
        async with admin_sessionmaker() as a, a.begin():
            return await lifecycle.retire(a, ECHO, force=True, confirm=True)

    retiring = asyncio.create_task(retire())
    await until_someone_waits_for_a_lock(owner_sessionmaker)  # retirement waits for admission's lock
    release.set()
    run_id = await asyncio.wait_for(starting, 10)
    assert (await asyncio.wait_for(retiring, 10)).applied
    assert client.started and (await run_row(owner_sessionmaker, ctx.tenant_id, run_id)).status == "running"


# A change to what admission checks (spec §4.5, "Admissible"), made as the API makes it: in a transaction that locks
# the workflow for update. Each one makes the version admission was asked for inadmissible, and admission says why.
Change = Callable[[Any, Any], Awaitable[object]]
REFUSED = {"disable": "disabled", "activate": "active version", "publish": "active version"}


async def admissible(
    how: str, owner: Any, api: Any, admin: Any, settings: Any
) -> tuple[Any, uuid.UUID, uuid.UUID, Change]:
    """A workflow, the version admission is asked for, and the change `how` that makes that version inadmissible:
    disabling the workflow, activating an older version, or publishing a newer one."""
    ctx, wf, version = await published(owner, api, admin, settings)
    older = version
    if how in ("activate", "publish"):
        await save(api, ctx, wf, ECHO_GRAPH)  # a draft for `publish`, or for the newer version `activate` replaces
    if how == "activate":
        newer = (await publish(api, ctx, wf, settings)).version
        assert newer is not None
        version = newer.id

    async def change(s: Any, row: Any) -> object:
        if how == "disable":
            return await workflow_ops.update(s, ctx, row, name=None, enabled=False)
        if how == "activate":
            return await workflow_ops.activate(s, ctx, row, await workflows.get_version(s, wf, older))
        out = await workflow_ops.publish(s, ctx, row, expected_revision=row.draft_revision, settings=settings)
        assert out.version is not None
        return out

    return ctx, wf, version, change


@asynccontextmanager
async def changing(api: Any, ctx: Any, wf: uuid.UUID, change: Change) -> AsyncIterator[None]:
    """Make the change in a transaction that stays open for the block, and commit it when the block ends."""
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        row = await workflows.get_workflow(s, ctx.tenant_id, wf, for_update=True)
        assert row is not None
        await change(s, row)
        yield


async def change_committed(api: Any, ctx: Any, wf: uuid.UUID, change: Change) -> None:
    async with changing(api, ctx, wf, change):
        pass


async def until_waiting_or_done(task: asyncio.Task[Any], owner: Any) -> None:
    """Until `task` has finished, or someone waits for a lock."""
    waiting = asyncio.create_task(until_someone_waits_for_a_lock(owner))
    done, _ = await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
    if waiting in done:
        waiting.result()  # nobody waited in time: AssertionError
    else:
        waiting.cancel()


@pytest.mark.parametrize("how", REFUSED)
async def test_a_workflow_change_first_makes_admission_refuse(
    how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, version, change = await admissible(
        how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
    )
    client = FakeClient()
    async with changing(api_sessionmaker, ctx, wf, change):
        starting = asyncio.create_task(
            start_run(
                dispatch_sessionmaker,
                client,
                api_settings,  # type: ignore[arg-type]
                tenant_id=ctx.tenant_id,
                version_id=version,
                trigger={},
            )  # fmt: skip
        )
        await until_waiting_or_done(starting, owner_sessionmaker)  # admission waits for the change to commit
    with pytest.raises(NotAdmissibleError, match=REFUSED[how]):
        await asyncio.wait_for(starting, 10)
    assert not client.started


@pytest.mark.parametrize("how", REFUSED)
async def test_admission_first_holds_a_workflow_change_until_the_run_exists(
    how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    ctx, wf, version, change = await admissible(
        how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
    )
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(run_ops, "_admission_locked", paused)
    client = FakeClient()
    starting = asyncio.create_task(
        start_run(
            dispatch_sessionmaker,
            client,
            api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id,
            version_id=version,
            trigger={},
        )  # fmt: skip
    )
    await asyncio.wait_for(reached.wait(), 10)
    changed = asyncio.create_task(change_committed(api_sessionmaker, ctx, wf, change))
    await until_waiting_or_done(changed, owner_sessionmaker)  # the change waits for the run
    changed_first = changed.done()
    release.set()
    run_id = await asyncio.wait_for(starting, 10)
    await asyncio.wait_for(changed, 10)
    assert not changed_first, f"`{how}` committed while a run of the version it makes inadmissible was admitted"
    row = await run_row(owner_sessionmaker, ctx.tenant_id, run_id)
    assert client.started and (row.status, row.workflow_version_id) == ("running", version)


@pytest.mark.parametrize("how", REFUSED)
async def test_admission_reads_the_workflow_afresh_in_a_session_that_loaded_it(
    how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """2b's dispatcher calls `admit` in its own session, which may already hold the workflow: the change committed
    since must still refuse the run."""
    ctx, wf, version, change = await admissible(
        how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
    )
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        held = await workflows.get_workflow(s, ctx.tenant_id, wf)  # the session holds it while this reference lives
        assert held is not None and held.enabled and held.active_version_id == version
        await change_committed(api_sessionmaker, ctx, wf, change)
        with pytest.raises(NotAdmissibleError, match=REFUSED[how]):
            await run_ops.admit(s, tenant_id=ctx.tenant_id, version_id=version)
