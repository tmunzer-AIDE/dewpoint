# SPDX-License-Identifier: Apache-2.0
"""A run's evidence reads its history a bounded number of pages a visit (the owner's D16 ruling on the 2b-4b M1
checkpoint: `PAGES`, an experimental cap, not a time budget), keeping where it stopped in its row: Temporal's
next-page token, the run it reads, the children it saw initiated but not yet started, the latest event's time. The
next visit, from any process, reads on from there. A history at Temporal's limit (51,200 events, about 205 pages of
250) takes 26 visits, none of them more than one describe and `PAGES` pages; every child it started is recorded once.
Counted in calls, against a history served page by page; and once against the dev server, a real page token read on by
a client connected afresh."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy import text
from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.history.v1 import (
    ChildWorkflowExecutionStartedEventAttributes,
    History,
    HistoryEvent,
    StartChildWorkflowExecutionInitiatedEventAttributes,
    WorkflowExecutionContinuedAsNewEventAttributes,
)
from temporalio.api.workflowservice.v1 import GetWorkflowExecutionHistoryResponse
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.dispatcher import evidence
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.test_leader_deadlines import recorded
from tests.apps.dispatcher.test_run_evidence import _root
from tests.core.retention.support import tenant
from tests.support.keys import FIXTURE_CONVERTER

RETENTION = timedelta(days=1)
LIMIT_PAGES = 205  # Temporal's 51,200 events a history, 250 a page
START = datetime(2026, 1, 1, tzinfo=UTC)


def _at(n: int) -> Timestamp:
    stamp = Timestamp()
    stamp.FromDatetime(START + timedelta(seconds=n))
    return stamp


@dataclass
class Served:
    """A closed run's history as Temporal serves it, a page a call, each call counted: every eighth page ends with a
    child's start initiated and the next starts with it started (a visit's last page and the next visit's first split
    them); its last page initiates a child that never starts, then continues the run as new."""

    tenant: str
    workflow_id: str
    run_id: str
    pages: int
    calls: list[str] = field(default_factory=list)
    gone: bool = False
    children: dict[int, str] = field(default_factory=dict)  # the page initiating it: its id
    continued: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        for page in [*range(7, self.pages - 1, 8), self.pages - 1]:
            self.children[page] = run_workflow_id(self.tenant, str(uuid.uuid4()))

    def page(self, n: int) -> list[HistoryEvent]:
        events = [HistoryEvent(event_id=n * 10 + 1, event_time=_at(n))]
        if n - 1 in self.children and n - 1 != self.pages - 1:  # started, the page after its initiation
            started = ChildWorkflowExecutionStartedEventAttributes(
                initiated_event_id=(n - 1) * 10 + 9,
                workflow_execution=WorkflowExecution(workflow_id=self.children[n - 1], run_id=f"run-{n - 1}"),
            )
            events.append(HistoryEvent(event_id=n * 10 + 2, event_time=_at(n),
                                       child_workflow_execution_started_event_attributes=started))  # fmt: skip
        if n in self.children:
            begun = StartChildWorkflowExecutionInitiatedEventAttributes(workflow_id=self.children[n])
            events.append(HistoryEvent(event_id=n * 10 + 9, event_time=_at(n),
                                       start_child_workflow_execution_initiated_event_attributes=begun))  # fmt: skip
        if n == self.pages - 1:
            continued = WorkflowExecutionContinuedAsNewEventAttributes(new_execution_run_id=self.continued)
            events.append(HistoryEvent(event_id=n * 10 + 10, event_time=_at(n),
                                       workflow_execution_continued_as_new_event_attributes=continued))  # fmt: skip
        return events


class _Service:
    def __init__(self, served: Served) -> None:
        self.served = served

    async def get_workflow_execution_history(self, req: Any, **kw: Any) -> GetWorkflowExecutionHistoryResponse:
        assert kw.get("timeout") == evidence.CALL_DEADLINE and req.execution.run_id == self.served.run_id
        n = int(req.next_page_token or b"0")
        self.served.calls.append(f"page {n}")
        if self.served.gone:
            raise RPCError("gone", RPCStatusCode.NOT_FOUND, b"")
        following = b"" if n + 1 == self.served.pages else str(n + 1).encode()
        return GetWorkflowExecutionHistoryResponse(history=History(events=self.served.page(n)),
                                                   next_page_token=following)  # fmt: skip


class _Handle:
    def __init__(self, served: Served) -> None:
        self.served = served

    async def describe(self, **kw: Any) -> Any:
        self.served.calls.append("describe")
        info = SimpleNamespace(first_run_id=self.served.run_id)
        return SimpleNamespace(
            status=WorkflowExecutionStatus.TERMINATED, run_id=self.served.run_id, close_time=START,
            raw_description=SimpleNamespace(workflow_execution_info=info),
        )  # fmt: skip


class Process:
    """A dispatcher's client, as a process started afresh has it: nothing of a read but what its row keeps."""

    namespace = "default"

    def __init__(self, served: Served) -> None:
        self.served, self.workflow_service = served, _Service(served)

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None) -> _Handle:
        return _Handle(self.served)


async def _row(owner: Any, tenant_id: uuid.UUID, workflow_id: str) -> int:
    await _root(owner, tenant_id, workflow_id)
    async with owner() as s:
        found: int = (await s.execute(text("select id from execution_evidence where workflow_id = :w and run_id is "
                                           "null"), {"w": workflow_id})).scalar_one()  # fmt: skip
    return found


async def _recorded_children(owner: Any, tenant_id: uuid.UUID, root: str) -> dict[str, list[str | None]]:
    async with owner() as s:
        query = text("select workflow_id, run_id from execution_evidence where tenant_id = :t and workflow_id <> :r "
                     "order by workflow_id, run_id")
        found = await s.execute(query, {"t": tenant_id, "r": root})
    children: dict[str, list[str | None]] = {}
    for workflow_id, run_id in found:
        children.setdefault(workflow_id, []).append(run_id)
    return children


async def test_a_history_at_temporals_limit_is_read_in_bounded_visits_each_from_where_the_last_stopped(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx = await tenant(owner_sessionmaker)
    root = run_workflow_id(str(ctx["t"]), str(uuid.uuid4()))
    row = await _row(owner_sessionmaker, ctx["t"], root)
    served = Served(str(ctx["t"]), root, str(uuid.uuid4()), LIMIT_PAGES)
    visits: list[tuple[str, list[str]]] = []
    while not visits or visits[-1][0] == "reading":
        assert len(visits) < 100
        served.calls.clear()
        outcome = await evidence._check(dispatch_sessionmaker, Process(served), ctx["t"], row, RETENTION)
        visits.append((outcome, list(served.calls)))
    assert [outcome for outcome, _ in visits] == ["reading"] * 25 + ["read"]
    assert all(len(calls) <= 1 + evidence.PAGES for _, calls in visits)
    assert [c for _, calls in visits for c in calls] == ["describe", *(f"page {n}" for n in range(LIMIT_PAGES))]
    children = await _recorded_children(owner_sessionmaker, ctx["t"], root)
    never_started = served.children[LIMIT_PAGES - 1]
    expected = {child: [f"run-{page}"] for page, child in served.children.items() if child != never_started}
    assert children == {**expected, never_started: [None]}
    async with owner_sessionmaker() as s:
        read = (await s.execute(text("select run_id, read_at is not null, read_token, read_pending from "
                                     "execution_evidence where id = :i"), {"i": row})).one()  # fmt: skip
        continued = (await s.execute(text("select count(*) from execution_evidence where workflow_id = :w and "
                                          "run_id = :r"), {"w": root, "r": served.continued})).scalar_one()  # fmt: skip
    assert tuple(read) == (served.run_id, True, None, None) and continued == 1


async def test_a_history_gone_in_the_middle_of_its_read_is_lost(owner_sessionmaker, dispatch_sessionmaker) -> None:
    """Seen, its read begun, then gone (retention deleted it): what it started past the pages read is unknown."""
    ctx = await tenant(owner_sessionmaker)
    root = run_workflow_id(str(ctx["t"]), str(uuid.uuid4()))
    row = await _row(owner_sessionmaker, ctx["t"], root)
    served = Served(str(ctx["t"]), root, str(uuid.uuid4()), 20)
    assert await evidence._check(dispatch_sessionmaker, Process(served), ctx["t"], row, RETENTION) == "reading"
    served.gone = True
    assert await evidence._check(dispatch_sessionmaker, Process(served), ctx["t"], row, RETENTION) == "lost"
    async with owner_sessionmaker() as s:
        lost = (await s.execute(text("select lost_at is not null, read_token from execution_evidence where id = :i"),
                                {"i": row})).one()  # fmt: skip
    assert tuple(lost) == (True, None)


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


async def test_a_real_page_token_is_read_on_by_a_client_connected_afresh(
    server, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """Against the dev server: a closed execution of 2,600 events (11 pages); the first visit reads `PAGES` of them,
    the second, from a client connected anew (a restarted dispatcher), reads the rest from the token its row kept."""
    ctx = await tenant(owner_sessionmaker)
    root = run_workflow_id(str(ctx["t"]), str(uuid.uuid4()))
    row = await _row(owner_sessionmaker, ctx["t"], root)
    handle = await server.client.start_workflow("Nothing", id=root, task_queue="evidence-paged-nowhere")
    for i in range(2_600):
        await handle.signal("probe", i)
    await handle.terminate()
    with recorded(server.client) as seen:
        assert await evidence._check(dispatch_sessionmaker, server.client, ctx["t"], row, RETENTION) == "reading"
    pages = [rpc for rpc, _ in seen if rpc == "get_workflow_execution_history"]
    assert len(pages) == evidence.PAGES and len(seen) == 1 + evidence.PAGES
    afresh = await Client.connect(server.client.service_client.config.target_host, namespace=server.client.namespace,
                                  data_converter=FIXTURE_CONVERTER)  # fmt: skip
    with recorded(afresh) as seen:
        assert await evidence._check(dispatch_sessionmaker, afresh, ctx["t"], row, RETENTION) == "read"
    assert [rpc for rpc, _ in seen] == ["get_workflow_execution_history"] * (11 - evidence.PAGES)
