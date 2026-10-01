# SPDX-License-Identifier: Apache-2.0
"""A pinned workflow with a workflow task the SDK's core completes by itself (test_deployment.py). In a module of its
own: the sandbox imports a workflow's module again, and the test's own imports aren't sandbox-safe."""

import asyncio
import contextlib
from datetime import timedelta

from temporalio import activity, common, workflow
from temporalio.exceptions import ActivityError


@activity.defn(name="deployment-test-echo")
async def echoed(value: str) -> str:
    return value


@workflow.defn(name="CancelsAnUnstartedActivity", versioning_behavior=common.VersioningBehavior.PINNED)
class CancelsAnUnstartedActivity:
    """An activity cancelled before any worker started it, then one that runs. Temporal records the first one
    cancelled at once, after the workflow task that asked: the next workflow task has nothing new for the workflow, and
    the SDK's core completes it by itself, as a cancelled run's steps do (engine 2b-1b §5.3's cancellation race)."""

    @workflow.run
    async def run(self, nobody: str) -> str:
        never = workflow.start_activity(echoed, "never", task_queue=nobody, start_to_close_timeout=timedelta(minutes=1))
        await workflow.sleep(0.1)  # its schedule recorded first: a cancel in the same task would record nothing
        never.cancel()
        with contextlib.suppress(ActivityError, asyncio.CancelledError):
            await never
        return await workflow.execute_activity(echoed, "ran", start_to_close_timeout=timedelta(seconds=10))
