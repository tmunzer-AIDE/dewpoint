# SPDX-License-Identifier: Apache-2.0
"""What an erasure asks of Temporal (the 2b-4 outline's "What this asks of the production Temporal"), each call bounded
by `CALL_DEADLINE` and idempotent: describing, pausing and deleting a schedule; describing, cancelling, terminating and
deleting an execution; reading a run's history from the execution store (its chain and its children); listing a
tenant's executions by workflow-id prefix (visibility, which only adds). No payload is decoded: the calls go to the
service directly, so the retention process holds no key."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.enums.v1 import WorkflowExecutionStatus
from temporalio.api.schedule.v1 import SchedulePatch
from temporalio.api.workflowservice.v1 import (
    DeleteScheduleRequest,
    DeleteWorkflowExecutionRequest,
    DescribeScheduleRequest,
    DescribeWorkflowExecutionRequest,
    GetWorkflowExecutionHistoryRequest,
    ListWorkflowExecutionsRequest,
    PatchScheduleRequest,
    RequestCancelWorkflowExecutionRequest,
    TerminateWorkflowExecutionRequest,
)
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

CALL_DEADLINE = timedelta(seconds=10)
IDENTITY = "dewpoint-erasure"
REASON = "tenant_erased"  # a fixed reason: no tenant data


def _gone(e: RPCError) -> bool:
    return e.status == RPCStatusCode.NOT_FOUND


@dataclass(frozen=True)
class ScheduleShown:
    paused: bool
    executions: list[tuple[str, str]]  # its recent actions' and running workflows' (workflow id, run id)


async def schedule(client: Client, schedule_id: str) -> ScheduleShown | None:
    try:
        answer = await client.workflow_service.describe_schedule(
            DescribeScheduleRequest(namespace=client.namespace, schedule_id=schedule_id), timeout=CALL_DEADLINE
        )
    except RPCError as e:
        if _gone(e):
            return None
        raise
    started = [a.start_workflow_result for a in answer.info.recent_actions] + list(answer.info.running_workflows)
    return ScheduleShown(answer.schedule.state.paused, [(w.workflow_id, w.run_id) for w in started])


async def pause_schedule(client: Client, schedule_id: str) -> None:
    try:
        await client.workflow_service.patch_schedule(
            PatchScheduleRequest(namespace=client.namespace, schedule_id=schedule_id,
                                 patch=SchedulePatch(pause=REASON), identity=IDENTITY,
                                 request_id=str(uuid.uuid4())),
            timeout=CALL_DEADLINE,
        )  # fmt: skip
    except RPCError as e:
        if not _gone(e):
            raise


async def delete_schedule(client: Client, schedule_id: str) -> None:
    try:
        await client.workflow_service.delete_schedule(
            DeleteScheduleRequest(namespace=client.namespace, schedule_id=schedule_id, identity=IDENTITY),
            timeout=CALL_DEADLINE,
        )
    except RPCError as e:
        if not _gone(e):
            raise


@dataclass(frozen=True)
class ExecutionShown:
    run_id: str
    open: bool


async def execution(client: Client, workflow_id: str, run_id: str | None) -> ExecutionShown | None:
    """The exact run (the latest of its chain without `run_id`), from the execution store; None: not found."""
    try:
        answer = await client.workflow_service.describe_workflow_execution(
            DescribeWorkflowExecutionRequest(
                namespace=client.namespace, execution=WorkflowExecution(workflow_id=workflow_id, run_id=run_id or "")
            ),
            timeout=CALL_DEADLINE,
        )
    except RPCError as e:
        if _gone(e):
            return None
        raise
    info = answer.workflow_execution_info
    return ExecutionShown(
        info.execution.run_id, info.status == WorkflowExecutionStatus.WORKFLOW_EXECUTION_STATUS_RUNNING
    )


async def cancel(client: Client, workflow_id: str) -> None:
    try:
        await client.workflow_service.request_cancel_workflow_execution(
            RequestCancelWorkflowExecutionRequest(
                namespace=client.namespace, workflow_execution=WorkflowExecution(workflow_id=workflow_id),
                identity=IDENTITY, request_id=str(uuid.uuid4()), reason=REASON,
            ),
            timeout=CALL_DEADLINE,
        )  # fmt: skip
    except RPCError as e:
        if not _gone(e):
            raise


async def terminate(client: Client, workflow_id: str, run_id: str) -> None:
    try:
        await client.workflow_service.terminate_workflow_execution(
            TerminateWorkflowExecutionRequest(
                namespace=client.namespace, reason=REASON, identity=IDENTITY,
                workflow_execution=WorkflowExecution(workflow_id=workflow_id, run_id=run_id),
            ),
            timeout=CALL_DEADLINE,
        )  # fmt: skip
    except RPCError as e:
        if not _gone(e) and e.status != RPCStatusCode.FAILED_PRECONDITION:  # already closed
            raise


async def delete_execution(client: Client, workflow_id: str, run_id: str) -> None:
    try:
        await client.workflow_service.delete_workflow_execution(
            DeleteWorkflowExecutionRequest(
                namespace=client.namespace, workflow_execution=WorkflowExecution(workflow_id=workflow_id, run_id=run_id)
            ),
            timeout=CALL_DEADLINE,
        )
    except RPCError as e:
        if not _gone(e):
            raise


@dataclass(frozen=True)
class RunRead:
    """What a closed run's history names: the run it continued from and the one it continued as, and every child it
    started (its run id when Temporal showed it started; its workflow id alone when only initiated)."""

    previous: str | None
    next: str | None
    children: list[tuple[str, str | None]]


async def read_run(client: Client, workflow_id: str, run_id: str) -> RunRead:
    """A closed run's history, whole, page by page, from the execution store (never visibility)."""
    previous = following = None
    initiated: dict[int, str] = {}
    children: list[tuple[str, str | None]] = []
    token = b""
    while True:
        page = await client.workflow_service.get_workflow_execution_history(
            GetWorkflowExecutionHistoryRequest(
                namespace=client.namespace, execution=WorkflowExecution(workflow_id=workflow_id, run_id=run_id),
                next_page_token=token,
            ),
            timeout=CALL_DEADLINE,
        )  # fmt: skip
        for event in page.history.events:
            if event.HasField("workflow_execution_started_event_attributes"):
                previous = event.workflow_execution_started_event_attributes.continued_execution_run_id or None
            elif event.HasField("start_child_workflow_execution_initiated_event_attributes"):
                initiated[event.event_id] = event.start_child_workflow_execution_initiated_event_attributes.workflow_id
            elif event.HasField("child_workflow_execution_started_event_attributes"):
                started = event.child_workflow_execution_started_event_attributes
                initiated.pop(started.initiated_event_id, None)
                children.append((started.workflow_execution.workflow_id, started.workflow_execution.run_id))
            elif event.HasField("start_child_workflow_execution_failed_event_attributes"):
                initiated.pop(event.start_child_workflow_execution_failed_event_attributes.initiated_event_id, None)
            elif event.HasField("workflow_execution_continued_as_new_event_attributes"):
                following = event.workflow_execution_continued_as_new_event_attributes.new_execution_run_id
        if not page.next_page_token:
            break
        token = page.next_page_token
    children.extend((child, None) for child in initiated.values())  # may have started: its id alone
    return RunRead(previous, following, children)


async def listed(client: Client, prefix: str) -> list[tuple[str, str]]:
    """Every execution visibility shows under the workflow-id prefix (which only adds: no lag is bounded)."""
    found: list[tuple[str, str]] = []
    token = b""
    while True:
        page = await client.workflow_service.list_workflow_executions(
            ListWorkflowExecutionsRequest(namespace=client.namespace, query=f"WorkflowId STARTS_WITH '{prefix}'",
                                          next_page_token=token),
            timeout=CALL_DEADLINE,
        )  # fmt: skip
        found.extend((e.execution.workflow_id, e.execution.run_id) for e in page.executions)
        if not page.next_page_token:
            return found
        token = page.next_page_token
