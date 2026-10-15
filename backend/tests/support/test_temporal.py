# SPDX-License-Identifier: Apache-2.0
"""`skips_time`, the check the shared time-skipping server gets after every test (`env`): a run that closes while
one of its activities is still scheduled leaves that server's clock held for good, and the check sees it."""

import uuid
from datetime import timedelta

from temporalio import workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from tests.support.temporal import skips_time


@workflow.defn(sandboxed=False)
class LeavesAnActivity:
    """Schedules an activity that no worker serves and ends in the same task: it is still scheduled as the run
    closes."""

    @workflow.run
    async def run(self) -> None:
        workflow.start_activity("unserved", task_queue="nobody", start_to_close_timeout=timedelta(minutes=1))


async def test_a_run_that_closes_with_an_activity_scheduled_stops_the_server_skipping_time() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as server:
        assert await skips_time(server)
        queue = f"leaves-{uuid.uuid4()}"
        runner = UnsandboxedWorkflowRunner()
        async with Worker(server.client, task_queue=queue, workflows=[LeavesAnActivity], workflow_runner=runner):
            await server.client.execute_workflow(LeavesAnActivity.run, id=queue, task_queue=queue)
        assert not await skips_time(server, within_s=1)
