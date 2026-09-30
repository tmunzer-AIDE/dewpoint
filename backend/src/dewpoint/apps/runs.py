# SPDX-License-Identifier: Apache-2.0
"""Starting runs (spec §9). `start_run` is 2a's admission, and 2b's dispatcher reuses `admit`: the workflow is
enabled, the version is its active one, every version in its closure was published for the engine ABI of the
deployment's current build (a version runs only on a build of its ABI, and a new run starts on the current build,
§7), and nothing in the closure is retired. They're checked in the transaction that inserts the run (§4.5), under
locks the other side takes too:
- the workflow is read under its admission lock (shared), so a disable, publish or activation either commits before
  the read or waits until the run exists;
- the closure is read under the lifecycle locks (shared), so a retirement either sees the run or the run sees the
  retirement.

Then `RunGraph` starts, with the run's id as its workflow id. A lost acknowledgement looks like a failure, so an
uncertain start is repeated with the same id: Temporal refuses a duplicate id (`REJECT_DUPLICATE`, which also covers
a run that has already finished), and that refusal confirms the first start. Only a confirmed refusal records the run
as failed (`start_failed`)."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.worker.deployment import current_abi
from dewpoint.apps.workflow_ops import abi_reasons
from dewpoint.core.config import Settings
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.runs import Run
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
from dewpoint.core.plugins import lifecycle
from dewpoint.core.runs import service as runs
from dewpoint.core.workflows.service import lock_for_admission, other_abi
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, LIVE, RunInput
from dewpoint.engine.runtime.workflow import RunGraph

START_FAILED = "start_failed"
PRODUCTION_RUNS_DISABLED = (
    "Production runs are off in this deployment: no run starts in a production deployment until its gate lifts "
    "(engine 2b spec §2). A development deployment, on its own database and Temporal namespace, runs synthetic "
    "fixtures."
)
NO_CURRENT_BUILD = (
    "No Dewpoint build is current in the `dewpoint-engine` deployment, so no worker would run it: make one current "
    "with `dewpoint deployment set-current`."
)
START_RETRY_S = (0.5, 2.0)  # the waits between three attempts to start a run
# Temporal refused the request itself, so it started nothing. Any other failure may follow an accepted start.
_REFUSED = frozenset(
    {
        RPCStatusCode.INVALID_ARGUMENT,
        RPCStatusCode.NOT_FOUND,
        RPCStatusCode.PERMISSION_DENIED,
        RPCStatusCode.UNAUTHENTICATED,
        RPCStatusCode.FAILED_PRECONDITION,
        RPCStatusCode.OUT_OF_RANGE,
        RPCStatusCode.UNIMPLEMENTED,
    }
)
_THROTTLED = RPCStatusCode.RESOURCE_EXHAUSTED  # refused before it was processed: worth another attempt


class NotAdmissibleError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class StartRefusedError(Exception):
    """Temporal refused the start: the run is recorded as failed (`start_failed`)."""


class StartUncertainError(Exception):
    """No answer confirmed or refused the start: the run may be executing, so it stays `running`."""

    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"Temporal didn't confirm or refuse run {run_id}: it may be running.")
        self.run_id = run_id


async def _admission_locked() -> None:
    """Hook that runs once the workflow's admission lock and the lifecycle locks are held. A no-op; the race tests
    pause here."""


async def admit(
    s: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    abi: int | None,
    mode: str = LIVE,
    started_by: uuid.UUID | None = None,
) -> Run:
    """Insert the run, or raise NotAdmissibleError. Call it inside a READ COMMITTED transaction. `abi` is the engine
    ABI of the deployment's current build, where the run will start (`current_abi`; None: no build is current). The
    admitting process's own build doesn't matter: during a rollout, both builds' processes admit runs.

    First, what this deployment is (engine 2b spec §2.3): with no record, or in production while the gate is off, it
    admits nothing — every start path comes through here, the dev CLI included."""
    platform = await recorded(s)
    if platform is None:
        raise NotAdmissibleError([NOT_RECORDED])
    if platform.environment == PRODUCTION and not platform.production_runs:
        raise NotAdmissibleError([PRODUCTION_RUNS_DISABLED])
    await tenant_scope(s, tenant_id)
    version = await s.get(WorkflowVersion, version_id)
    if version is None:
        raise NotAdmissibleError(["There is no such version."])
    workflow = await lock_for_admission(s, tenant_id, version.workflow_id)  # stands until the run exists
    if workflow is None or not workflow.enabled:
        raise NotAdmissibleError(["The workflow is disabled."])
    if workflow.active_version_id != version.id:
        raise NotAdmissibleError(["Only the workflow's active version can start runs."])
    if abi is None:
        raise NotAdmissibleError([NO_CURRENT_BUILD])
    stale = await other_abi(s, version.closure_version_ids, abi)  # versions never change: no lock needed
    if stale:
        raise NotAdmissibleError(abi_reasons(version.id, stale, abi))
    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
    await lifecycle.lock_shared(s, entries)
    await _admission_locked()
    blocked = lifecycle.not_executable(await lifecycle.states(s, entries))
    if blocked:
        raise NotAdmissibleError([f"{entry} has been retired." for entry in blocked])
    return await runs.insert_run(
        s,
        run_id=uuid.uuid4(),
        tenant_id=tenant_id,
        workflow_id=version.workflow_id,
        version_id=version.id,
        mode=mode,
        started_by=started_by,
    )


async def start_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    client: Client,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    trigger: dict[str, Any],
    mode: str = LIVE,
    started_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """Admit the run and start it. Raises NotAdmissibleError, StartRefusedError (the run is recorded as failed) or
    StartUncertainError (the run stays `running`: it may be executing). A promotion between the admission and the
    start is caught when the run loads its version (§7)."""
    abi = await current_abi(client)  # before the transaction: no lock is held across a call to Temporal
    async with sessionmaker() as s, s.begin():
        run = await admit(s, tenant_id=tenant_id, version_id=version_id, abi=abi, mode=mode, started_by=started_by)
    start = RunInput(
        tenant_id=str(tenant_id),
        run_id=str(run.id),
        version_id=str(version_id),
        trigger=trigger,
        mode=mode,
        max_run_duration_s=settings.max_run_duration_days * 86_400,
        cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
    )
    try:
        await _start(client, start, run.id)
    except StartRefusedError as e:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            await runs.finish_run(
                s, run.id, status="failed", ended_at=datetime.now(UTC), error_code=START_FAILED, error_message=str(e)
            )
        raise
    return run.id


async def _start(client: Client, start: RunInput, run_id: uuid.UUID) -> None:
    uncertain = False
    last: BaseException | None = None
    for wait in (*START_RETRY_S, None):
        try:
            await client.start_workflow(
                RunGraph.run,
                start,
                id=str(run_id),
                task_queue=ENGINE_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            return
        except WorkflowAlreadyStartedError:
            return  # an earlier attempt was accepted; its answer was lost
        except RPCError as e:
            if e.status in _REFUSED and not uncertain:
                raise StartRefusedError(f"Temporal refused the run ({e.status.name}).") from e
            uncertain = uncertain or e.status != _THROTTLED
            last = e
        except Exception as e:  # a lost connection: the request may have been accepted
            uncertain, last = True, e
        if wait is not None:
            await asyncio.sleep(wait)
    if uncertain:
        raise StartUncertainError(run_id) from last
    raise StartRefusedError("Temporal refused the run: it was busy (RESOURCE_EXHAUSTED).") from last


__all__ = [
    "START_FAILED",
    "PRODUCTION_RUNS_DISABLED",
    "NO_CURRENT_BUILD",
    "START_RETRY_S",
    "NotAdmissibleError",
    "StartRefusedError",
    "StartUncertainError",
    "admit",
    "start_run",
]
