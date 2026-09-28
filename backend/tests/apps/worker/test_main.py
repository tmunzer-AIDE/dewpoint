# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker`'s workers."""

from datetime import timedelta
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.worker.main import engine_worker
from dewpoint.core.config import Settings
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import MemoryStore
from tests.support.plugins.testkit import TESTKIT


def settings(**overrides: Any) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        kek_b64="A" * 43 + "=",
        public_origin="https://dewpoint.test",
        **overrides,
    )


async def test_a_stopping_worker_lets_running_attempts_finish(own_env: WorkflowEnvironment) -> None:
    """Final review: a worker that stops cancels its running attempts at once by default, so every deploy would end
    the ambiguous ones as `outcome_unknown`. It gives them the configured grace first. (A server of its own: a worker
    holds its task queue on its client until it runs and stops.)"""
    worker = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings(worker_shutdown_grace_s=45))
    assert worker.config()["graceful_shutdown_timeout"] == timedelta(seconds=45)
    assert Settings.model_fields["worker_shutdown_grace_s"].default == 30


async def test_the_engine_worker_runs_runs_and_loop_batches(own_env: WorkflowEnvironment) -> None:
    """2a-3b: a loop batch is a workflow type of its own, on the same queue as the runs that start it."""
    worker = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings())
    assert worker.config()["workflows"] == [RunGraph, LoopBatch]
