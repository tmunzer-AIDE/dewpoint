# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker` (spec §6, §7): `RunGraph` and the engine activities on `dewpoint-engine`. When an evaluator is
configured, it also serves `cel.evaluate`, only on the queue of the profile the evaluator reports: it waits for the
evaluator, then asks its identity. Worker Versioning (the pinned deployment) comes with plan 2a-3c."""

import asyncio
from collections.abc import Iterable
from datetime import timedelta

import structlog
from temporalio.client import Client
from temporalio.worker import Worker

from dewpoint.apps import cel_client
from dewpoint.apps.plugin_loader import installed_plugins
from dewpoint.apps.worker.activities import RunStore, cel_activity, engine_activities, remote_evaluator
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.config import Settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
from dewpoint.engine.runtime.workflow import RunGraph
from dewpoint.sdk import Plugin

log = structlog.get_logger("dewpoint.worker")


async def evaluator_profile(socket_path: str, *, wait_s: float = 2.0) -> str:
    """The profile the evaluator serves; retried until it answers (Compose starts it healthy first)."""
    while True:
        try:
            return await cel_client.identity(socket_path)
        except cel_client.EvaluatorUnavailable as e:
            log.warning("cel_evaluator_unavailable", error=str(e))
            await asyncio.sleep(wait_s)


def engine_worker(client: Client, store: RunStore, plugins: Iterable[Plugin], settings: Settings) -> Worker:
    """A stopping worker lets running attempts finish for `worker_shutdown_grace_s`: one it cancels ends as it would
    on a lost worker, `outcome_unknown` for an ambiguous node."""
    return Worker(
        client,
        task_queue=ENGINE_QUEUE,
        workflows=[RunGraph],
        activities=engine_activities(store, plugins),
        graceful_shutdown_timeout=timedelta(seconds=settings.worker_shutdown_grace_s),
    )


def cel_worker(client: Client, socket_path: str, profile: str, *, max_concurrent: int) -> Worker:
    return Worker(
        client,
        task_queue=cel_queue(profile),
        activities=[cel_activity(remote_evaluator(socket_path, profile))],
        max_concurrent_activities=max_concurrent,
    )


async def run(settings: Settings) -> None:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    engine = make_engine(settings.database_url)
    try:
        workers = [engine_worker(client, DbRunStore(make_sessionmaker(engine)), installed_plugins(), settings)]
        if settings.cel_socket:
            profile = await evaluator_profile(settings.cel_socket)
            log.info("cel_queue", profile=profile)
            workers.append(cel_worker(client, settings.cel_socket, profile, max_concurrent=settings.cel_max_concurrent))
        await asyncio.gather(*(w.run() for w in workers))
    finally:
        await engine.dispose()
