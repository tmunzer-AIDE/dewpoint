# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker`'s workers."""

from datetime import timedelta
from typing import Any

import pytest
from temporalio.converter import DefaultFailureConverterWithEncodedAttributes
from temporalio.testing import WorkflowEnvironment

import dewpoint
from dewpoint.apps import cel_client
from dewpoint.apps.codec import FailureConverter, TenantCodec
from dewpoint.apps.worker import main
from dewpoint.apps.worker.health import WorkerUnhealthyError
from dewpoint.apps.worker.main import engine_worker
from dewpoint.core import logs
from dewpoint.core.config import Settings
from dewpoint.engine.runtime.build import build_id
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import MemoryStore
from tests.support.logs import records, rendered
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


async def test_the_engine_worker_serves_this_builds_version_of_the_deployment(own_env: WorkflowEnvironment) -> None:
    """Spec §7: one Worker Deployment, `dewpoint-engine`; this build's version is its build id. The CEL worker isn't
    in it: its queues are routed by profile."""
    config = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings()).config()["deployment_config"]
    assert config.use_worker_versioning
    assert (config.version.deployment_name, config.version.build_id) == (
        "dewpoint-engine",
        build_id(dewpoint.__version__),
    )


async def test_the_worker_connects_with_the_tenant_codec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine 2b spec §6.2: every payload a worker sends or reads goes through the codec, failures too."""
    connected: dict[str, Any] = {}

    class Connected(Exception):
        """Where the test stops the worker: nothing else of it runs."""

    class Engine:
        async def dispose(self) -> None: ...

    async def recorded(*args: object) -> None: ...

    async def connect(*args: object, **kwargs: Any) -> None:
        connected.update(kwargs)
        raise Connected

    monkeypatch.setattr(main.Client, "connect", connect)
    monkeypatch.setattr(main, "make_engine", lambda url, **pool: Engine())
    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
    monkeypatch.setattr(main, "verify_environment", recorded)
    monkeypatch.setattr(main, "reporter", lambda *args: unrecorded)
    monkeypatch.setattr(main, "self_check", proven)
    with pytest.raises(Connected):
        await main.run(settings())
    converter = connected["data_converter"]
    assert isinstance(converter.payload_codec, TenantCodec)
    assert converter.failure_converter_class is FailureConverter  # encoded attributes, a tick's reduced to codes
    assert issubclass(FailureConverter, DefaultFailureConverterWithEncodedAttributes)


async def unrecorded(healthy: bool) -> None:
    """Where a test's worker records its health: nowhere (the record itself: tests/core/platform/test_workers.py)."""


async def proven(*args: object) -> bool:
    """A test worker's self-check, with its stand-in database: passed (the check itself: test_health.py)."""
    return True


async def failed(*args: object) -> bool:
    return False


async def test_a_worker_that_fails_its_self_check_never_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine 2b spec §2.7: it records itself unhealthy and exits before connecting to Temporal."""
    reports: list[bool] = []

    class Engine:
        async def dispose(self) -> None: ...

    async def recorded(*args: object) -> None: ...

    async def report(healthy: bool) -> None:
        reports.append(healthy)

    async def connect(*args: object, **kwargs: Any) -> None:
        raise AssertionError("it connected")

    monkeypatch.setattr(main.Client, "connect", connect)
    monkeypatch.setattr(main, "make_engine", lambda url, **pool: Engine())
    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
    monkeypatch.setattr(main, "verify_environment", recorded)
    monkeypatch.setattr(main, "reporter", lambda *args: report)
    monkeypatch.setattr(main, "self_check", failed)
    with pytest.raises(WorkerUnhealthyError):
        await main.run(settings())
    assert reports == [False]


async def test_an_unavailable_evaluator_is_logged_by_its_type_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """EvaluatorUnavailable carries another error's text, or the evaluator's reply."""
    secret = "reply-secret-2c71"
    answers: list[str | Exception] = [cel_client.EvaluatorUnavailable(f"bad reply {secret}"), "cel-1"]

    async def identity(socket_path: str) -> str:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(cel_client, "identity", identity)
    with rendered() as lines:
        logs.configure()
        assert await main.evaluator_profile("/run/cel.sock", wait_s=0) == "cel-1"
    assert secret not in "\n".join(lines())
    [record] = records(lines())
    assert (record["event"], record["error"]) == ("cel_evaluator_unavailable", "EvaluatorUnavailable")
