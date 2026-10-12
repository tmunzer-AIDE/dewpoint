# SPDX-License-Identifier: Apache-2.0
"""A blocker moves only by the rulings' evidence (2b-4b M4 recovery, task 4). An absence then requeue, or a collision,
makes it `unresolved`. It becomes `identified`, with that run, only where the recorded start request id is on the
chain's first run's started event (`verify`, `started_by`, the evidence cadence's sighting); a sighting whose first run
carries another id leaves it as it was, alerted. Nothing else moves it: not the request's end, a NOT_FOUND, time, nor a
key's retirement (none of them writes the store). `gone` removes only an `identified`, not legacy-unknown blocker with
no send open; the dispatcher never calls it."""

import ast
import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.client import WorkflowExecutionStatus

from dewpoint.apps.dispatcher import dispatch, evidence, start_call
from dewpoint.core import blockers
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.activities import ENGINE_QUEUE
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import begin
from tests.apps.dispatcher.test_blocker_store import requeued, store
from tests.apps.dispatcher.test_reconcile import aged, once

pytestmark = pytest.mark.usefixtures("development_deployment")
SRC = Path(__file__).resolve().parents[3] / "src"
RETENTION = timedelta(days=1)
Outcome, Sent = dispatch.Outcome, dispatch.Sent


async def _late_started(dsm: Any, owner: Any, request: Any, settings: Any) -> dispatch.Starting:
    """A send whose `started` reply came after its request ended: its blocker `unresolved`, the reply's run kept on its
    own row."""
    first = await begin(dsm, request, settings)
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set status = 'cancelled', reason = 'test', ended_at = now() "
                             "where id = :i"), {"i": request.id})  # fmt: skip
    assert await dispatch.settle(dsm, first, Outcome("started", answer="started", run_id="the-reply"),
                                 sent=Sent(1, "started", "the-reply")) == "moved"  # fmt: skip
    return first


async def _landed(env: Any, starting: dispatch.Starting, request_id: uuid.UUID | None) -> Any:
    """The execution the send started, its started event carrying `request_id` (None: the SDK's own, another id)."""
    workflow_id = run_workflow_id(starting.start.tenant_id, starting.start.run_id)
    if request_id is None:
        return await env.client.start_workflow(RunGraph.run, starting.start, id=workflow_id, task_queue=ENGINE_QUEUE)
    with start_call.sending(request_id):
        return await env.client.start_workflow(RunGraph.run, starting.start, id=workflow_id, task_queue=ENGINE_QUEUE)


async def test_an_absence_then_requeue_makes_the_blocker_unresolved(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    await begin(dispatch_sessionmaker, request, api_settings)  # a crash left it unanswered
    assert (await store(owner_sessionmaker, request.id))[0] == ("pending", False, None)
    await requeued(dispatch_sessionmaker, request)
    assert await store(owner_sessionmaker, request.id) == (("unresolved", False, None), [(1, None, None, False)])


async def test_a_reconcilers_collision_makes_the_blocker_unresolved(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    described = dispatch.Starting(first.request_id, first.tenant_id, first.start, first.start_request_id)
    assert await dispatch.settle(dispatch_sessionmaker, described, Outcome("collision"), audited=True) == "dead"
    assert await store(owner_sessionmaker, request.id) == (("unresolved", False, None), [(1, None, None, False)])


async def test_a_sighting_carrying_the_recorded_id_identifies_the_blocker_with_its_first_run(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """Even after a late `started` reply: the run identified is the first run's, read from Temporal, never the
    reply's."""
    _, _, request = queued
    first = await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    handle = await _landed(env, first, first.start_request_id)
    try:
        await evidence.check_evidence(dispatch_sessionmaker, env.client, retention=RETENTION)
        assert await store(owner_sessionmaker, request.id) == (
            ("identified", False, handle.first_execution_run_id), [(1, "started", "the-reply", True)])  # fmt: skip
    finally:
        if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:  # a late start's: terminated (task 5)
            await handle.terminate()


async def test_a_sighting_carrying_another_id_changes_nothing_and_is_alerted(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """Its request still `starting` (an ended one's live execution is a late start: task 5)."""
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None))
    before = await store(owner_sessionmaker, request.id)
    handle = await _landed(env, first, None)
    try:
        with structlog.testing.capture_logs() as logs:
            await evidence.check_evidence(dispatch_sessionmaker, env.client, retention=RETENTION)
        assert await store(owner_sessionmaker, request.id) == before == (
            ("unresolved", False, None), [(1, None, None, False)])  # fmt: skip
        assert [e["log_level"] for e in logs if e["event"] == "start_unidentified"] == ["error"]
    finally:
        await handle.terminate()


async def test_the_reconcilers_verified_start_identifies_the_blocker(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None))
    handle = await _landed(env, first, first.start_request_id)
    try:
        await aged(owner_sessionmaker, request.id)
        assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
        assert await store(owner_sessionmaker, request.id) == (
            ("identified", False, handle.first_execution_run_id), [(1, None, None, False)])  # fmt: skip
    finally:
        await handle.terminate()


async def test_the_requests_end_a_not_found_and_time_leave_the_blocker_as_it_is(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """Abandonment (`abandon_start`) is phase C's: its own task tests it."""
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None))
    before = await store(owner_sessionmaker, request.id)
    async with owner_sessionmaker() as s, s.begin():  # its end, and every check due long ago
        await s.execute(text("update run_requests set status = 'dead', reason = 'test', ended_at = now() "
                             "where id = :i"), {"i": request.id})  # fmt: skip
        await s.execute(text("update execution_evidence set next_check_at = now() - interval '30 days', "
                             "checked_at = now() - interval '30 days'"))  # fmt: skip

    async def unshown(client: object, workflow_id: str, run_id: str | None) -> None:
        return None  # NOT_FOUND

    monkeypatch.setattr(evidence, "_described", unshown)
    for _ in range(3):
        await evidence.check_evidence(dispatch_sessionmaker, None, retention=RETENTION)  # type: ignore[arg-type]
    assert await store(owner_sessionmaker, request.id) == before


def test_only_the_store_module_writes_the_store() -> None:
    """A key's retirement, the erasure, retention, the API: none writes `unresolved_sends` or `start_sends`. (The API
    reads counts through `unresolved_sends_counts`, a function of its own name, task 9: never the tables.)"""
    writers = []
    tables = re.compile(r"\b(unresolved_sends|start_sends)\b")
    for path in sorted(SRC.rglob("*.py")):
        if tables.search(path.read_text()) and path.name != "blockers.py":
            writers.append(str(path.relative_to(SRC)))
    assert writers == []


def test_the_dispatcher_never_removes_an_identified_blocker() -> None:
    """`gone` is the erasure's (task 13: step 60, `stages.py`), and `identified` is called only behind the first run's
    check (the dispatcher's, and step 60's identity read)."""
    calls: dict[str, list[str]] = {"gone": [], "identified": []}
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in calls and (
                    isinstance(node.func.value, ast.Name) and node.func.value.id == "blockers"):  # fmt: skip
                calls[node.func.attr].append(path.name)
    assert calls == {"gone": ["stages.py"], "identified": ["dispatch.py", "evidence.py", "stages.py"]}


async def test_gone_removes_only_an_identified_blocker_with_nothing_open_and_never_a_legacy_one(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    await dispatch.settle(dispatch_sessionmaker, first, Outcome("uncertain"), sent=Sent(1, None, None))

    async def gone() -> bool:
        async with owner_sessionmaker() as s, s.begin():
            await tenant_scope(s, request.tenant_id)  # its audit entry is the tenant's (task 13)
            return await blockers.gone(s, request.id)

    assert not await gone()  # unresolved
    async with owner_sessionmaker() as s, s.begin():
        await blockers.identified(s, request.id, "run-1")
    assert not await gone()  # identified, but its send is open
    assert (await store(owner_sessionmaker, request.id))[0] == ("identified", False, "run-1")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update start_sends set answer = 'refused', answered_at = now() where request_id = :r"),
                        {"r": request.id})  # fmt: skip
        await s.execute(text("update unresolved_sends set legacy_unknown = true where request_id = :r"),
                        {"r": request.id})  # fmt: skip
    assert not await gone()  # legacy-unknown: never
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update unresolved_sends set legacy_unknown = false where request_id = :r"),
                        {"r": request.id})  # fmt: skip
    assert await gone()
    assert await store(owner_sessionmaker, request.id) == (None, [])


async def test_deleted_open_keeps_an_identified_blocker_whose_send_is_open(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    await begin(dispatch_sessionmaker, request, api_settings)
    async with owner_sessionmaker() as s, s.begin():
        await blockers.identified(s, request.id, "run-1")
        await blockers.deleted_open(s, request.id)
    assert await store(owner_sessionmaker, request.id) == (("deleted_open", False, "run-1"), [(1, None, None, False)])


async def test_a_legacy_unknown_blocker_can_be_identified_but_never_leaves(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into unresolved_sends (request_id, tenant_id, workflow_id, legacy_unknown, "
                             "state) values (:r, :t, :w, true, 'unresolved')"),
                        {"r": request.id, "t": request.tenant_id, "w": run_workflow_id(str(request.tenant_id),
                                                                                      str(request.id))})  # fmt: skip
    first = await begin(dispatch_sessionmaker, request, api_settings)  # a later recorded send: its identity
    handle = await _landed(env, first, first.start_request_id)
    try:
        await evidence.check_evidence(dispatch_sessionmaker, env.client, retention=RETENTION)
        assert (await store(owner_sessionmaker, request.id))[0] == ("identified", True, handle.first_execution_run_id)
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update start_sends set answer = 'refused', answered_at = now() "
                                 "where request_id = :r"), {"r": request.id})  # fmt: skip
            assert not await blockers.gone(s, request.id)
        assert (await store(owner_sessionmaker, request.id))[0] is not None
    finally:
        await handle.terminate()
