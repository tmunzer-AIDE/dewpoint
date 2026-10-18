# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker`'s workers."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from temporalio import activity
from temporalio.converter import DefaultFailureConverterWithEncodedAttributes
from temporalio.testing import WorkflowEnvironment

import dewpoint
from dewpoint.apps import cel_client
from dewpoint.apps.codec import FailureConverter, TenantCodec
from dewpoint.apps.worker import health, main
from dewpoint.apps.worker.health import WorkerUnhealthyError
from dewpoint.apps.worker.main import INTERNAL_SLOTS, SHARED_OVERFLOW, SHARED_POOL, engine_worker, internal_worker
from dewpoint.core import logs
from dewpoint.core.config import Settings
from dewpoint.engine.runtime.activities import (
    CLAIMS_CHILD_INPUT,
    CLAIMS_DERIVE,
    CLAIMS_GRANT,
    CLAIMS_MESSAGE,
    CLAIMS_SPILL,
    CLOSE_BATCH,
    ENGINE_QUEUE,
    INTERNAL_QUEUE,
    LOAD_VERSION,
    PROJECT,
)
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
        temporal_insecure_dev=True,  # §10.4: plaintext, in a deployment recorded as development (`recorded` below)
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


async def test_the_engines_own_activities_have_a_queue_and_slots_of_their_own(own_env: WorkflowEnvironment) -> None:
    """The owner's ruling of 2026-10-18 (option A): a run's steps hold the engine queue's activity slots, never the
    internal queue's. The internal worker serves the projection, a batch's close and the claims crossings, in the same
    version of the deployment, so a pinned run's projection runs on its build; it has a slot for each of the shared
    pool's connections, and stops with the same grace. The engine queue keeps the version loader (a local activity)
    and the steps."""
    engine = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings(worker_shutdown_grace_s=45)).config()
    internal = internal_worker(own_env.client, MemoryStore(), settings(worker_shutdown_grace_s=45)).config()

    def names(config: Any) -> set[str | None]:
        return {activity._Definition.must_from_callable(a).name for a in config["activities"]}

    assert (engine["task_queue"], internal["task_queue"]) == (ENGINE_QUEUE, INTERNAL_QUEUE)
    assert names(internal) == {
        PROJECT, CLOSE_BATCH, CLAIMS_DERIVE, CLAIMS_CHILD_INPUT, CLAIMS_GRANT, CLAIMS_MESSAGE, CLAIMS_SPILL
    }  # fmt: skip
    assert LOAD_VERSION in names(engine) and names(engine).isdisjoint(names(internal))
    assert internal["max_concurrent_activities"] == INTERNAL_SLOTS == SHARED_POOL + SHARED_OVERFLOW == 15
    assert internal["deployment_config"] == engine["deployment_config"]
    assert internal["graceful_shutdown_timeout"] == engine["graceful_shutdown_timeout"] == timedelta(seconds=45)


async def test_the_worker_connects_with_the_tenant_codec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine 2b spec §6.2: every payload a worker sends or reads goes through the codec, failures too."""
    connected: dict[str, Any] = {}

    class Connected(Exception):
        """Where the test stops the worker: nothing else of it runs."""

    class Engine:
        async def dispose(self) -> None: ...

    async def recorded(*args: object) -> object:
        return SimpleNamespace(environment="development")

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

    async def recorded(*args: object) -> object:
        return SimpleNamespace(environment="development")

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


async def test_the_cel_worker_lets_running_evaluations_finish(own_env: WorkflowEnvironment) -> None:
    """The owner's ruling W3 (graceful stop): a stopping worker's evaluations get the same grace as its attempts; one
    cancelled at once would spend one of `cel.evaluate`'s three attempts, and wait for the next worker."""
    worker = main.cel_worker(own_env.client, "/run/cel.sock", "cel-1", MemoryStore(), max_concurrent=2,
                             grace=timedelta(seconds=45))  # fmt: skip
    assert worker.config()["graceful_shutdown_timeout"] == timedelta(seconds=45)


class Serving:
    """The worker process's parts, standing in for its workers, its plugin-call server and its health watch: what each
    did, in order."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[str] = []
        self.polling = asyncio.Event()
        self.refused: Exception | None = None  # what a worker's run() raises before it polls, if anything
        test = self

        class Engine:
            async def dispose(self) -> None:
                test.events.append("disposed")

        class Worker:
            """temporalio 1.33.0's shape: `shutdown()` returns only once `run()` has ended, and never when `run()`
            failed before it polled (its namespace not validated, say)."""

            def __init__(self, *args: object, **kwargs: Any) -> None:
                self.stopping, self.ended = asyncio.Event(), asyncio.Event()

            async def run(self) -> None:
                if test.refused is not None:
                    raise test.refused
                test.events.append("polling")
                test.polling.set()
                await self.stopping.wait()
                test.events.append("worker ended")
                self.ended.set()

            async def shutdown(self) -> None:
                test.events.append("shutdown")
                self.stopping.set()
                await self.ended.wait()

        class PluginCalls:
            def __init__(self, *args: object, **kwargs: Any) -> None:
                self.stopped = asyncio.Event()

            def stop(self) -> None:
                self.stopped.set()

            async def run(self) -> None:
                await self.stopped.wait()
                test.events.append("plugin calls ended")

        async def watch(*args: object) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                test.events.append("watch cancelled")
                raise

        async def recorded(*args: object) -> object:
            return SimpleNamespace(environment="development")

        async def connect(*args: object, **kwargs: Any) -> object:
            test.events.append("connected")
            return SimpleNamespace()

        monkeypatch.setattr(main, "make_engine", lambda url, **pool: Engine())
        monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
        monkeypatch.setattr(main, "verify_environment", recorded)
        monkeypatch.setattr(main, "reporter", lambda *args: unrecorded)
        monkeypatch.setattr(main, "self_check", proven)
        monkeypatch.setattr(main, "temporal_connect", connect)
        monkeypatch.setattr(main, "engine_worker", Worker)
        monkeypatch.setattr(main, "internal_worker", Worker)
        monkeypatch.setattr(main, "PluginCallServer", PluginCalls)
        monkeypatch.setattr(main, "watch", watch)


async def test_a_stop_request_stops_the_workers_then_their_helpers_then_the_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner's ruling W1 (graceful stop): SIGTERM (Compose's stop) does what a failed check does: the workers stop
    polling, running attempts get the shutdown grace and plugin calls their answer; then what only helped them goes,
    and then the engines, which the attempts used to the end."""
    s, requested = Serving(monkeypatch), asyncio.Event()
    running = asyncio.ensure_future(main.run(settings(), stop_requested=requested))
    await asyncio.wait_for(s.polling.wait(), 10)
    requested.set()
    await asyncio.wait_for(running, 10)
    assert s.events[:3] == ["connected", "polling", "polling"]  # the engine worker and the internal one
    assert sorted(s.events[3:8]) == ["plugin calls ended", "shutdown", "shutdown", "worker ended", "worker ended"]
    assert s.events[8:] == ["watch cancelled", "disposed", "disposed"]


async def test_a_stop_while_starting_abandons_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner's ruling W2: a worker still starting (here, its database not answering) has taken nothing; it stops at
    once instead of waiting for Compose's SIGKILL."""
    s, requested = Serving(monkeypatch), asyncio.Event()

    async def unanswered(*args: object) -> object:
        requested.set()
        await asyncio.Event().wait()
        raise AssertionError("never answered")

    monkeypatch.setattr(main, "verify_environment", unanswered)
    await asyncio.wait_for(main.run(settings(), stop_requested=requested), 10)
    assert s.events == ["disposed", "disposed"]


async def test_a_failed_promotion_stops_the_workers_before_the_process_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner's ruling W1: a helper that fails (`promote` out of time) stops the workers first; it no longer leaves
    them polling while the engines are disposed under them."""
    s = Serving(monkeypatch)

    class OutOfTime(Exception):
        """`promote`'s, told apart from a hang's TimeoutError."""

    async def promote(client: object) -> None:
        await s.polling.wait()
        raise OutOfTime

    monkeypatch.setattr(main, "promote", promote)
    with pytest.raises(OutOfTime):
        await asyncio.wait_for(main.run(settings(worker_set_current=True), stop_requested=asyncio.Event()), 10)
    assert s.events[:3] == ["connected", "polling", "polling"]  # the engine worker and the internal one
    assert sorted(s.events[3:8]) == ["plugin calls ended", "shutdown", "shutdown", "worker ended", "worker ended"]
    assert s.events[8:] == ["watch cancelled", "disposed", "disposed"]


async def test_a_failed_self_check_still_ends_the_worker_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine 2b spec §2.7, through the stop's wiring (the fresh review's finding 1): the SDK's `shutdown()` returns
    only once `run()` has ended, so the workers end before the failed check is raised; it's raised all the same, and the
    process exits 3, not as a stop."""
    s = Serving(monkeypatch)
    answers = [True, False]  # at startup, then at its first watch

    async def check(*args: object) -> bool:
        return answers.pop(0)

    monkeypatch.setattr(main, "self_check", check)
    monkeypatch.setattr(main, "watch", lambda check, report: health.watch(check, report, interval_s=0))
    with pytest.raises(WorkerUnhealthyError):
        await asyncio.wait_for(main.run(settings(), stop_requested=asyncio.Event()), 10)
    assert s.events[0] == "connected" and "worker ended" in s.events and s.events[-2:] == ["disposed", "disposed"]


async def test_a_worker_that_fails_before_it_polls_ends_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fresh review's finding 2: the SDK's `run()` can fail before it polls, and its `shutdown()` then never
    returns; the process still ends, with that failure, once its other parts have stopped."""
    s = Serving(monkeypatch)
    s.refused = LookupError("namespace not found")
    with pytest.raises(LookupError, match="namespace"):
        await asyncio.wait_for(main.run(settings(), stop_requested=asyncio.Event()), 10)
    assert s.events[0] == "connected"
    assert sorted(s.events[1:4]) == ["plugin calls ended", "shutdown", "shutdown"]  # at once
    assert s.events[4:] == ["watch cancelled", "disposed", "disposed"]
