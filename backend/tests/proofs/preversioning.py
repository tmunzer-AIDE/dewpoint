# SPDX-License-Identifier: Apache-2.0
"""The pre-versioning visibility query (2b-4b M4; the upgrade barrier's check for runs from builds before Worker
Deployments): an open run on the engine's queue with no Worker Deployment version recorded. The barrier gates on it
only once it's proven on a disposable D12 server (d12/test_preversioning.py, run only when the owner authorizes it).
The same scenario runs in the normal suite on a CLI dev server, whose visibility is SQLite, not D12's PostgreSQL: that
rehearsal checks the scenario, not the target.

Temporal v1.32.0 (its source): the server records a run's version in `TemporalWorkerDeploymentVersion` as
`<deployment>:<build>` when a workflow task completes on a version, and removes the attribute when the run has none;
PostgreSQL's visibility keeps it in a column of its own, and its query converter accepts `IS NULL`.

The scenario, on the engine's queue and deployment, on a server of its own (the query's answer is checked whole):
- a worker with no deployment configuration, as builds before Worker Deployments had, starts two runs, holds one open
  and lets the other complete, then stops;
- a worker of a version of the engine's deployment, with the engine's settings, joins, is made current, and a third
  run starts on it and is held open, pinned; it stops too, so no record changes while visibility is read;
- each run's history shows where its workflow tasks completed: the premises;
- visibility is waited for, never read once. Each excluded run is first shown recorded in the state that differs from
  the query in one condition only (the closed run closed, the versioned run with its version), and the open
  unversioned run recorded open. An empty answer is visibility not caught up, never a pass;
- then the query's first answer must be exactly the open unversioned run, and its count one.

Its limit: the unversioned run stays idle once a version is current. What Temporal does with such a run's next
workflow task isn't shown here."""

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from temporalio.api.enums.v1 import VersioningBehavior
from temporalio.client import Client, WorkflowHandle
from temporalio.service import RPCError
from temporalio.worker import Worker

from dewpoint.apps.worker.deployment import DEPLOYMENT, deployment_config, set_current
from dewpoint.engine.runtime.activities import ENGINE_QUEUE
from tests.proofs.hold_workflow import Hold

QUERY = f"ExecutionStatus = 'Running' AND TaskQueue = '{ENGINE_QUEUE}' AND TemporalWorkerDeploymentVersion IS NULL"
VISIBILITY_DEADLINE_S = 60.0
TASK_DEADLINE_S = 30.0
POLL_S = 0.2
ROLES = ("unversioned", "closed", "versioned")


@dataclass(frozen=True)
class Evidence:
    query: str
    runs: dict[str, str]  # role -> workflow id
    build: str  # the versioned run's build
    builds: dict[str, list[str]]  # role -> the builds that completed its workflow tasks ("" for none)
    behaviours: dict[str, list[str]]  # role -> the versioning behaviour each of its workflow tasks reported
    seconds: dict[str, float]  # role -> how long visibility took to show it in its control's state
    found: list[str]  # the query's first answer
    count: int


async def _tasks_completed(handle: WorkflowHandle[Any, Any], at_least: int = 1) -> None:
    until = time.monotonic() + TASK_DEADLINE_S
    while True:
        history = await handle.fetch_history()
        done = sum(1 for e in history.events if e.HasField("workflow_task_completed_event_attributes"))
        if done >= at_least:
            return
        if time.monotonic() > until:
            raise AssertionError(f"{handle.id}: {done} workflow tasks completed within {TASK_DEADLINE_S} s")
        await asyncio.sleep(POLL_S)


async def _placement(handle: WorkflowHandle[Any, Any]) -> tuple[list[str], list[str]]:
    tasks = [
        e.workflow_task_completed_event_attributes
        for e in (await handle.fetch_history()).events
        if e.HasField("workflow_task_completed_event_attributes")
    ]
    return (
        sorted({t.deployment_version.build_id for t in tasks}),
        sorted({VersioningBehavior.Name(t.versioning_behavior) for t in tasks}),
    )


async def _listed(client: Client, query: str) -> list[str]:
    return sorted([execution.id async for execution in client.list_workflows(query)])


async def until_listed(client: Client, query: str, workflow_id: str) -> float:
    """Seconds until visibility lists `workflow_id` for `query`, a query naming that one run. An empty answer is
    visibility not caught up: it's waited for, and past the deadline it fails."""
    start = time.monotonic()
    while (seen := await _listed(client, query)) != [workflow_id]:
        if seen:
            raise AssertionError(f"{query!r} listed {seen}")
        if time.monotonic() - start > VISIBILITY_DEADLINE_S:
            raise AssertionError(f"visibility didn't list {workflow_id} for {query!r} within {VISIBILITY_DEADLINE_S} s")
        await asyncio.sleep(POLL_S)
    return round(time.monotonic() - start, 3)


async def first_answer(client: Client, query: str) -> list[str]:
    """The query's first answer that isn't empty: an empty one is waited for. A wrong one isn't retried."""
    start = time.monotonic()
    while not (seen := await _listed(client, query)):
        if time.monotonic() - start > VISIBILITY_DEADLINE_S:
            raise AssertionError(f"{query!r} listed nothing within {VISIBILITY_DEADLINE_S} s")
        await asyncio.sleep(POLL_S)
    return seen


async def observe(client: Client) -> Evidence:
    """The scenario on `client`'s namespace, on a server of its own: no other run may be on the engine's queue."""
    tag = uuid.uuid4().hex[:8]
    runs = {role: f"pre-versioning-{role}-{tag}" for role in ROLES}
    build = f"pre-versioning-proof-{tag}"
    handles: dict[str, WorkflowHandle[Any, Any]] = {}
    try:
        async with Worker(client, task_queue=ENGINE_QUEUE, workflows=[Hold]):  # no deployment configuration
            for role in ("unversioned", "closed"):
                handles[role] = await client.start_workflow(Hold.run, id=runs[role], task_queue=ENGINE_QUEUE)
            await _tasks_completed(handles["unversioned"])
            await handles["closed"].signal(Hold.release)
            await asyncio.wait_for(handles["closed"].result(), TASK_DEADLINE_S)
        async with Worker(
            client, task_queue=ENGINE_QUEUE, workflows=[Hold], deployment_config=deployment_config(build)
        ):
            await set_current(client, build)
            handles["versioned"] = await client.start_workflow(Hold.run, id=runs["versioned"], task_queue=ENGINE_QUEUE)
            await _tasks_completed(handles["versioned"])
        placements = {role: await _placement(handles[role]) for role in ROLES}
        on_queue = f"TaskQueue = '{ENGINE_QUEUE}'"
        controls = {
            "closed": f"ExecutionStatus = 'Completed' AND {on_queue} AND TemporalWorkerDeploymentVersion IS NULL",
            "versioned": f"ExecutionStatus = 'Running' AND {on_queue} AND "
            f"TemporalWorkerDeploymentVersion = '{DEPLOYMENT}:{build}'",
            "unversioned": f"ExecutionStatus = 'Running' AND {on_queue}",
        }
        seconds = {
            role: await until_listed(client, f"WorkflowId = '{runs[role]}' AND {control}", runs[role])
            for role, control in controls.items()
        }
        found = await first_answer(client, QUERY)
        count = (await client.count_workflows(QUERY)).count
        return Evidence(
            query=QUERY,
            runs=runs,
            build=build,
            builds={role: placements[role][0] for role in ROLES},
            behaviours={role: placements[role][1] for role in ROLES},
            seconds=seconds,
            found=found,
            count=count,
        )
    finally:
        for role in ("unversioned", "versioned"):
            if role in handles:
                with contextlib.suppress(RPCError):
                    await handles[role].terminate()  # the held runs aren't left open


def check(evidence: Evidence) -> None:
    """The premises (where each run's workflow tasks completed), then the query's answer."""
    unversioned = (["VERSIONING_BEHAVIOR_UNSPECIFIED"], [""])
    assert (evidence.behaviours["unversioned"], evidence.builds["unversioned"]) == unversioned
    assert (evidence.behaviours["closed"], evidence.builds["closed"]) == unversioned
    assert evidence.builds["versioned"] == [evidence.build]
    assert evidence.behaviours["versioned"] == ["VERSIONING_BEHAVIOR_PINNED"]
    assert evidence.found == [evidence.runs["unversioned"]]
    assert evidence.count == 1
