# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker`'s workers."""

from datetime import timedelta

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.worker.main import engine_worker
from dewpoint.core.config import Settings
from tests.apps.worker.harness import MemoryStore
from tests.support.plugins.testkit import TESTKIT


async def test_a_stopping_worker_lets_running_attempts_finish(own_env: WorkflowEnvironment) -> None:
    """Final review: a worker that stops cancels its running attempts at once by default, so every deploy would end
    the ambiguous ones as `outcome_unknown`. It gives them the configured grace first. (A server of its own: a worker
    holds its task queue on its client until it runs and stops.)"""
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        kek_b64="A" * 43 + "=",
        public_origin="https://dewpoint.test",
        worker_shutdown_grace_s=45,
    )
    worker = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings)
    assert worker.config()["graceful_shutdown_timeout"] == timedelta(seconds=45)
    assert Settings.model_fields["worker_shutdown_grace_s"].default == 30
