# SPDX-License-Identifier: Apache-2.0
"""A run held open until it's released (the pre-versioning query's scenario, preversioning.py). In a module of its
own: the sandbox imports a workflow's module again, and the scenario's own imports aren't sandbox-safe."""

from temporalio import workflow


@workflow.defn(name="PreVersioningHold")
class Hold:
    """No versioning behaviour declared, as builds before Worker Deployments declared none: on a version of the
    engine's deployment, the engine worker's default (pinned) applies."""

    def __init__(self) -> None:
        self._released = False

    @workflow.signal
    def release(self) -> None:
        self._released = True

    @workflow.run
    async def run(self) -> None:
        await workflow.wait_condition(lambda: self._released)
