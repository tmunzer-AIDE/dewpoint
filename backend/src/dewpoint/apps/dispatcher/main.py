# SPDX-License-Identifier: Apache-2.0
"""The dispatcher process (engine 2b spec §7.3), role `dewpoint_dispatch`. It checks the deployment's environment
before it connects to Temporal (§2.1), encrypts every start with the tenant's key (§6.2), and each cycle observes the
current build, dispatches what's due, and reports; the one that leads the reconciler (§7.6) also settles what starts
left uncertain, and reports that apart."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker

from dewpoint.apps.codec import KeyringKeys, data_converter
from dewpoint.apps.dispatcher.cancels import send_cancels
from dewpoint.apps.dispatcher.dispatch import Rotation, dispatch_once
from dewpoint.apps.dispatcher.observe import observe, report
from dewpoint.apps.dispatcher.reconcile import Leader, reconcile_once
from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE, Ticker
from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
from dewpoint.apps.environment import verify_environment
from dewpoint.apps.worker.deployment import describe, this_build
from dewpoint.core.config import Settings
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import make_engine, make_sessionmaker

log = structlog.get_logger("dewpoint.dispatcher")
CYCLE_S = 1.0  # between cycles


async def current_build(client: Client) -> str | None:
    """The build new runs start on, as Temporal reports it; None when none is current yet."""
    try:
        return (await describe(client)).current
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return None
        raise


async def cycle(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings, *,
    instance: uuid.UUID, reconciler: uuid.UUID, leader: Leader, rotation: Rotation,
) -> None:  # fmt: skip
    """One cycle: observe the current build, dispatch what's due, report; the leader also reconciles and sends
    cancels. An observation that fails (Temporal, or the database, briefly unavailable) dispatches nothing this cycle,
    and the next one asks again; the record it didn't refresh ages out for admission (§7.2)."""
    try:
        build = await observe(sessionmaker, await current_build(client))
    except Exception as e:
        log.error("dispatcher_observe_failed", error=type(e).__name__)
        build = None
    build_id = build.build_id if build else ""
    done = await dispatch_once(sessionmaker, client, keys, settings, build, rotation) if build else {}
    await report(sessionmaker, instance, build_id, {"current_build": bool(build), **done})
    if await leader.leading():
        settled = await reconcile_once(sessionmaker, client, keys, settings)
        settled.update({f"cancel_{k}": v for k, v in (await send_cancels(sessionmaker, client)).items()})
        await report(sessionmaker, reconciler, build_id, {**settled}, kind="reconciler")


async def serve(one: Callable[[], Awaitable[None]], *, cycles: int | None = None) -> None:
    """Cycles, `CYCLE_S` apart, forever (or `cycles` of them). A cycle that fails is logged by type, never by message,
    and the next one runs: the process outlives what it can't control (the whole-branch review)."""
    done = 0
    while cycles is None or done < cycles:
        try:
            await one()
        except Exception as e:
            log.error("dispatcher_cycle_failed", error=type(e).__name__)
        done += 1
        await asyncio.sleep(CYCLE_S)


def admission_worker(client: Client, sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource) -> Worker:
    """The dispatcher's own worker for `ScheduleTick` (engine 2b spec §8.2): `dewpoint-admission`, unversioned, outside
    the engine's Worker Deployment, admitting each tick as the dispatch role."""
    return Worker(
        client, task_queue=ADMISSION_QUEUE, workflows=[ScheduleTick], activities=[Ticker(sessionmaker, keys).tick]
    )


async def run(settings: Settings) -> None:
    """Raises EnvironmentNotRecordedError or EnvironmentMismatchError before connecting to Temporal."""
    engine = make_engine(settings.database_url)
    try:
        sessionmaker = make_sessionmaker(engine)
        await verify_environment(sessionmaker, settings)
        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
        client = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter(keys)
        )
        instance = uuid.uuid4()
        reconciler, leader = uuid.uuid5(instance, "reconciler"), Leader(engine)
        log.info("dispatcher_started", instance=str(instance), build=this_build())
        rotation = Rotation()

        async def one() -> None:
            await cycle(sessionmaker, client, keys, settings, instance=instance, reconciler=reconciler, leader=leader,
                        rotation=rotation)  # fmt: skip

        try:
            async with admission_worker(
                client, sessionmaker, keys
            ):  # ends the process if it fails: Compose restarts it
                await serve(one)
        finally:
            await leader.close()
    finally:
        await engine.dispose()
